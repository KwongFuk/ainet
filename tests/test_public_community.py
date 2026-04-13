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

        bids = client.get(f"/needs/{need_id}/bids", headers=alice_headers)
        assert_status(bids, 200, "alice lists bids")
        assert bids.json()[0]["bid_id"] == bid.json()["bid_id"]

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
