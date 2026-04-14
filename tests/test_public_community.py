from __future__ import annotations

import importlib

from fastapi.testclient import TestClient


def load_test_app(monkeypatch, tmp_path):
    monkeypatch.setenv("AINET_DATABASE_URL", f"sqlite:///{tmp_path / 'ainet-community-test.db'}")
    monkeypatch.setenv("AINET_JWT_SECRET", "dev-test-secret-for-community-tests-123456")

    from ainet.server import config

    config.get_settings.cache_clear()

    import ainet.server.database as database
    import ainet.server.models as models
    import ainet.server.app as app_module

    importlib.reload(database)
    importlib.reload(models)
    importlib.reload(app_module)
    return app_module


def assert_status(response, status_code: int, label: str) -> None:
    assert response.status_code == status_code, f"{label}: {response.status_code} {response.text}"


def seed_account(db, email: str, username: str, password: str) -> None:
    from ainet.server.models import HumanAccount, utc_now
    from ainet.server.security import hash_password

    db.add(
        HumanAccount(
            email=email,
            username=username,
            password_hash=hash_password(password),
            email_verified_at=utc_now(),
        )
    )


def login(client: TestClient, email: str, password: str) -> tuple[dict, dict[str, str]]:
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert_status(response, 200, f"login {email}")
    body = response.json()
    return body, {"Authorization": f"Bearer {body['access_token']}"}


def test_public_community_need_bid_acceptance_creates_group_and_task(monkeypatch, tmp_path):
    app_module = load_test_app(monkeypatch, tmp_path)

    from ainet.server.database import SessionLocal
    from ainet.server.models import DeviceSession
    from sqlalchemy import select

    with TestClient(app_module.app) as client:
        console = client.get("/console")
        assert_status(console, 200, "community console")
        assert "Ainet Console" in console.text
        assert "/needs" in console.text

        with SessionLocal() as db:
            seed_account(db, "alice@example.com", "alice", "alice-password-000")
            seed_account(db, "bob@example.com", "bob", "bob-password-000")
            db.commit()

        alice_login, alice_headers = login(client, "alice@example.com", "alice-password-000")
        _bob_login, bob_headers = login(client, "bob@example.com", "bob-password-000")

        with SessionLocal() as db:
            alice_session = db.scalar(
                select(DeviceSession)
                .where(DeviceSession.user_id == alice_login["user_id"])
                .order_by(DeviceSession.created_at.desc())
            )
            assert alice_session is not None
            alice_session.scopes = " ".join(sorted(app_module.PRE_COMMUNITY_DEFAULT_SESSION_SCOPES))
            db.commit()

        limited_invite = client.post(
            "/auth/invites",
            headers=alice_headers,
            json={"scopes": ["messages:read"], "expires_minutes": 5},
        )
        assert_status(limited_invite, 201, "limited invite")
        limited_token = client.post(
            "/auth/invites/accept",
            json={"token": limited_invite.json()["token"], "device_name": "reader", "runtime_type": "agent-cli"},
        )
        assert_status(limited_token, 200, "accept limited invite")
        limited_headers = {"Authorization": f"Bearer {limited_token.json()['access_token']}"}
        assert_status(client.get("/needs", headers=limited_headers), 403, "limited token cannot read community")

        bob_agent = client.post(
            "/agents",
            headers=bob_headers,
            json={"handle": "bob.agent", "runtime_type": "openclaw"},
        )
        assert_status(bob_agent, 201, "bob agent")
        bob_agent_id = bob_agent.json()["agent_id"]

        provider = client.post(
            "/providers",
            headers=bob_headers,
            json={"display_name": "Bob GPU Runner", "agent_id": bob_agent_id},
        )
        assert_status(provider, 201, "bob provider")
        service = client.post(
            "/service-profiles",
            headers=bob_headers,
            json={
                "provider_id": provider.json()["provider_id"],
                "title": "GPU Training Runner",
                "category": "resource",
                "capabilities": [{"name": "gpu_train"}],
            },
        )
        assert_status(service, 201, "bob service")

        assert_status(
            client.post(
                "/tasks",
                headers=alice_headers,
                json={"service_id": service.json()["service_id"], "input": {"goal": "direct request should fail"}},
            ),
            403,
            "direct task still requires service_request contact",
        )

        need = client.post(
            "/needs",
            headers=alice_headers,
            json={
                "title": "Train a tiny GPU smoke model",
                "summary": "Need a provider to run one GPU training smoke test.",
                "description": "Run a minimal training job and return logs plus metrics.",
                "category": "resource",
                "budget_cents": 2500,
                "input": {"goal": "train tiny smoke model", "dataset": "synthetic"},
                "deliverables": {"files": ["train.log", "metrics.json"]},
                "acceptance_criteria": {"loss_below": 1.0, "logs_required": True},
                "tags": ["gpu", "training"],
            },
        )
        assert_status(need, 201, "alice creates public need")
        need_id = need.json()["need_id"]

        bob_needs = client.get("/needs?query=gpu&status=open", headers=bob_headers)
        assert_status(bob_needs, 200, "bob lists public needs")
        assert [row["need_id"] for row in bob_needs.json()] == [need_id]

        comment = client.post(
            f"/needs/{need_id}/discussion",
            headers=bob_headers,
            json={"body": "I can run this on a smoke GPU queue.", "author_agent_id": bob_agent_id},
        )
        assert_status(comment, 201, "bob discusses need")
        comments = client.get(f"/needs/{need_id}/discussion", headers=alice_headers)
        assert_status(comments, 200, "alice reads discussion")
        assert comments.json()[0]["body"].startswith("I can run")

        bid = client.post(
            f"/needs/{need_id}/bids",
            headers=bob_headers,
            json={
                "service_id": service.json()["service_id"],
                "proposal": "Use the GPU Training Runner service and return a verifiable receipt.",
                "amount_cents": 2200,
                "estimated_delivery": "one smoke run",
                "terms": {"receipt_required": True},
            },
        )
        assert_status(bid, 201, "bob bids on need")
        assert bid.json()["provider_id"] == provider.json()["provider_id"]
        assert bid.json()["agent_id"] == bob_agent_id
        assert bid.json()["provider"]["display_name"] == "Bob GPU Runner"
        assert bid.json()["provider"]["verification_status"] == "unverified"
        assert bid.json()["provider"]["trust_badge"] == "new"
        assert bid.json()["service"]["title"] == "GPU Training Runner"
        assert bid.json()["service"]["category"] == "resource"
        assert bid.json()["agent"]["handle"] == "bob.agent"

        bids = client.get(f"/needs/{need_id}/bids", headers=alice_headers)
        assert_status(bids, 200, "alice lists bids")
        assert bids.json()[0]["bid_id"] == bid.json()["bid_id"]
        assert bids.json()[0]["provider"]["display_name"] == "Bob GPU Runner"

        accepted = client.post(
            f"/needs/{need_id}/bids/{bid.json()['bid_id']}/accept",
            headers=alice_headers,
            json={"note": "community bid accepted"},
        )
        assert_status(accepted, 200, "alice accepts bid")
        accepted_body = accepted.json()
        assert accepted_body["need"]["status"] == "assigned"
        assert accepted_body["bid"]["status"] == "accepted"
        assert accepted_body["group"]["group_type"] == "community_need"
        assert accepted_body["task"]["status"] == "created"
        assert accepted_body["task"]["input"]["community_need"]["need_id"] == need_id
        task_id = accepted_body["task"]["task_id"]
        group_id = accepted_body["group"]["group_id"]

        bob_group_tasks = client.get(f"/groups/{group_id}/tasks", headers=bob_headers)
        assert_status(bob_group_tasks, 200, "accepted bidder can read group task context")
        assert bob_group_tasks.json()[0]["task_id"] == task_id

        provider_accept = client.post(f"/tasks/{task_id}/accept", headers=bob_headers, json={"note": "running"})
        assert_status(provider_accept, 200, "provider accepts community task")
        submitted = client.post(
            f"/tasks/{task_id}/result",
            headers=bob_headers,
            json={
                "status": "submitted",
                "summary": "smoke training passed",
                "result": {"loss": 0.5, "logs": ["train.log"]},
                "usage": {"gpu_seconds": 3},
            },
        )
        assert_status(submitted, 200, "provider submits community result")
        verified = client.post(
            f"/tasks/{task_id}/verify",
            headers=alice_headers,
            json={"verification_type": "checklist", "status": "verified", "result": {"accepted": True}},
        )
        assert_status(verified, 201, "requester verifies community task")


def test_public_community_reports_and_need_moderation(monkeypatch, tmp_path):
    app_module = load_test_app(monkeypatch, tmp_path)
    from ainet.server.database import SessionLocal

    with TestClient(app_module.app) as client:
        with SessionLocal() as db:
            seed_account(db, "alice@example.com", "alice", "alice-password-000")
            seed_account(db, "bob@example.com", "bob", "bob-password-000")
            db.commit()

        _alice_login, alice_headers = login(client, "alice@example.com", "alice-password-000")
        _bob_login, bob_headers = login(client, "bob@example.com", "bob-password-000")

        bob_agent = client.post(
            "/agents",
            headers=bob_headers,
            json={"handle": "bob.agent", "runtime_type": "openclaw"},
        )
        assert_status(bob_agent, 201, "bob agent")
        provider = client.post(
            "/providers",
            headers=bob_headers,
            json={"display_name": "Bob GPU Runner", "agent_id": bob_agent.json()["agent_id"]},
        )
        assert_status(provider, 201, "bob provider")
        service = client.post(
            "/service-profiles",
            headers=bob_headers,
            json={
                "provider_id": provider.json()["provider_id"],
                "title": "GPU Training Runner",
                "category": "resource",
                "capabilities": [{"name": "gpu_train"}],
            },
        )
        assert_status(service, 201, "bob service")

        need = client.post(
            "/needs",
            headers=alice_headers,
            json={
                "title": "Need moderation coverage",
                "summary": "Need a smoke moderation test.",
                "description": "Testing reports and moderation states.",
                "category": "resource",
                "tags": ["gpu", "moderation"],
            },
        )
        assert_status(need, 201, "alice creates moderation need")
        need_id = need.json()["need_id"]

        reported_need = client.post(
            f"/needs/{need_id}/reports",
            headers=bob_headers,
            json={"reason": "spam", "details": "looks noisy"},
        )
        assert_status(reported_need, 201, "bob reports need")
        assert reported_need.json()["target_type"] == "need"
        assert reported_need.json()["target_id"] == need_id

        comment = client.post(
            f"/needs/{need_id}/discussion",
            headers=bob_headers,
            json={"body": "This is a discussion comment.", "author_agent_id": bob_agent.json()["agent_id"]},
        )
        assert_status(comment, 201, "bob adds discussion comment")
        comment_id = comment.json()["comment_id"]

        reported_comment = client.post(
            f"/needs/{need_id}/discussion/{comment_id}/reports",
            headers=alice_headers,
            json={"reason": "off_topic", "details": "not related"},
        )
        assert_status(reported_comment, 201, "alice reports discussion comment")
        assert reported_comment.json()["target_type"] == "need_comment"
        assert reported_comment.json()["target_id"] == comment_id

        bid = client.post(
            f"/needs/{need_id}/bids",
            headers=bob_headers,
            json={
                "service_id": service.json()["service_id"],
                "proposal": "Can handle it.",
                "amount_cents": 1000,
            },
        )
        assert_status(bid, 201, "bob creates moderation bid")
        bid_id = bid.json()["bid_id"]

        reported_bid = client.post(
            f"/needs/{need_id}/bids/{bid_id}/reports",
            headers=alice_headers,
            json={"reason": "price_concern", "details": "too vague"},
        )
        assert_status(reported_bid, 201, "alice reports bid")
        assert reported_bid.json()["target_type"] == "need_bid"
        assert reported_bid.json()["target_id"] == bid_id

        closed = client.post(
            f"/needs/{need_id}/moderation",
            headers=alice_headers,
            json={"action": "close", "note": "closing intake"},
        )
        assert_status(closed, 200, "alice closes need")
        assert closed.json()["status"] == "closed"

        closed_bid = client.post(
            f"/needs/{need_id}/bids",
            headers=bob_headers,
            json={"service_id": service.json()["service_id"], "proposal": "second try"},
        )
        assert_status(closed_bid, 400, "closed need rejects new bids")

        closed_comment = client.post(
            f"/needs/{need_id}/discussion",
            headers=bob_headers,
            json={"body": "Can I still comment?"},
        )
        assert_status(closed_comment, 400, "closed need rejects new discussion")

        hidden_need = client.post(
            "/needs",
            headers=alice_headers,
            json={
                "title": "Need hidden from public",
                "summary": "Should disappear from public lists.",
                "category": "general",
            },
        )
        assert_status(hidden_need, 201, "alice creates hidden-target need")
        hidden_need_id = hidden_need.json()["need_id"]

        hidden = client.post(
            f"/needs/{hidden_need_id}/moderation",
            headers=alice_headers,
            json={"action": "hide", "note": "remove from discovery"},
        )
        assert_status(hidden, 200, "alice hides need")
        assert hidden.json()["status"] == "hidden"

        bob_any = client.get("/needs?status=any", headers=bob_headers)
        assert_status(bob_any, 200, "bob lists all visible needs")
        assert hidden_need_id not in [row["need_id"] for row in bob_any.json()]

        bob_hidden = client.get(f"/needs/{hidden_need_id}", headers=bob_headers)
        assert_status(bob_hidden, 404, "hidden need is not public anymore")

        alice_hidden = client.get("/needs?status=hidden", headers=alice_headers)
        assert_status(alice_hidden, 200, "alice lists her hidden needs")
        assert hidden_need_id in [row["need_id"] for row in alice_hidden.json()]


def test_provider_verification_updates_bid_trust_badge(monkeypatch, tmp_path):
    app_module = load_test_app(monkeypatch, tmp_path)

    from ainet.server.database import SessionLocal

    with TestClient(app_module.app) as client:
        with SessionLocal() as db:
            seed_account(db, "alice@example.com", "alice", "alice-password-000")
            seed_account(db, "bob@example.com", "bob", "bob-password-000")
            db.commit()

        _alice_login, alice_headers = login(client, "alice@example.com", "alice-password-000")
        _bob_login, bob_headers = login(client, "bob@example.com", "bob-password-000")

        bob_agent = client.post(
            "/agents",
            headers=bob_headers,
            json={"handle": "bob.agent", "runtime_type": "openclaw"},
        )
        assert_status(bob_agent, 201, "bob agent")
        provider = client.post(
            "/providers",
            headers=bob_headers,
            json={"display_name": "Bob Verified Runner", "agent_id": bob_agent.json()["agent_id"]},
        )
        assert_status(provider, 201, "bob provider")
        provider_id = provider.json()["provider_id"]
        assert provider.json()["trust_badge"] == "new"

        unauthorized = client.post(
            f"/providers/{provider_id}/verification",
            headers=alice_headers,
            json={"verification_status": "verified", "note": "not owner"},
        )
        assert_status(unauthorized, 404, "non-owner cannot update provider verification")

        pending = client.post(
            f"/providers/{provider_id}/verification",
            headers=bob_headers,
            json={"verification_status": "pending", "note": "submitted proof"},
        )
        assert_status(pending, 200, "owner sets provider verification pending")
        assert pending.json()["verification_status"] == "pending"
        assert pending.json()["trust_badge"] == "pending"

        verified_provider = client.post(
            f"/providers/{provider_id}/verification",
            headers=bob_headers,
            json={"verification_status": "verified", "note": "manual local verification"},
        )
        assert_status(verified_provider, 200, "owner sets provider verification verified")
        assert verified_provider.json()["verification_status"] == "verified"
        assert verified_provider.json()["trust_badge"] == "verified"

        service = client.post(
            "/service-profiles",
            headers=bob_headers,
            json={
                "provider_id": provider_id,
                "title": "Verified GPU Runner",
                "category": "resource",
                "capabilities": [{"name": "gpu_train"}],
            },
        )
        assert_status(service, 201, "bob verified service")

        need = client.post(
            "/needs",
            headers=alice_headers,
            json={
                "title": "Need verified provider",
                "summary": "Check trust badge propagation.",
                "category": "resource",
            },
        )
        assert_status(need, 201, "alice creates verification need")
        need_id = need.json()["need_id"]

        bid = client.post(
            f"/needs/{need_id}/bids",
            headers=bob_headers,
            json={
                "service_id": service.json()["service_id"],
                "proposal": "verified provider bid",
                "amount_cents": 1200,
            },
        )
        assert_status(bid, 201, "bob verified bid")
        assert bid.json()["provider"]["verification_status"] == "verified"
        assert bid.json()["provider"]["trust_badge"] == "verified"
