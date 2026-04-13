from __future__ import annotations

import importlib

from fastapi.testclient import TestClient


def load_test_app(monkeypatch, tmp_path):
    monkeypatch.setenv("AINET_DATABASE_URL", f"sqlite:///{tmp_path / 'ainet-verification-test.db'}")
    monkeypatch.setenv("AINET_JWT_SECRET", "dev-test-secret-for-verification-tests-123456")

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


def login(client: TestClient, email: str, password: str) -> dict[str, str]:
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert_status(response, 200, f"login {email}")
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def create_task_setup(client: TestClient, alice_headers: dict[str, str], bob_headers: dict[str, str]) -> tuple[str, str]:
    bob_agent = client.post(
        "/agents",
        headers=bob_headers,
        json={"handle": "bob.agent", "runtime_type": "runtime"},
    )
    if bob_agent.status_code == 409:
        bob_agent_id = client.get("/agents", headers=bob_headers).json()[0]["agent_id"]
    else:
        assert_status(bob_agent, 201, "bob agent")
        bob_agent_id = bob_agent.json()["agent_id"]

    contact = client.post(
        "/contacts",
        headers=alice_headers,
        json={"handle": "bob.agent", "permissions": ["service_request"], "trust_level": "trusted"},
    )
    assert_status(contact, 201, "alice contact bob")

    provider = client.post(
        "/providers",
        headers=bob_headers,
        json={"display_name": "Bob Verifiable Runner", "agent_id": bob_agent_id},
    )
    assert_status(provider, 201, "bob provider")
    service = client.post(
        "/service-profiles",
        headers=bob_headers,
        json={
            "provider_id": provider.json()["provider_id"],
            "title": "Verifiable Runner",
            "capabilities": [{"name": "run_check"}],
        },
    )
    assert_status(service, 201, "bob service")
    return bob_agent_id, service.json()["service_id"]


def test_service_task_verification_receipts_and_rating_gate(monkeypatch, tmp_path):
    app_module = load_test_app(monkeypatch, tmp_path)

    from ainet.server.database import SessionLocal

    with TestClient(app_module.app) as client:
        with SessionLocal() as db:
            seed_account(db, "alice@example.com", "alice", "alice-password-000")
            seed_account(db, "bob@example.com", "bob", "bob-password-000")
            db.commit()

        alice_headers = login(client, "alice@example.com", "alice-password-000")
        bob_headers = login(client, "bob@example.com", "bob-password-000")
        _bob_agent_id, service_id = create_task_setup(client, alice_headers, bob_headers)

        task = client.post(
            "/tasks",
            headers=alice_headers,
            json={"service_id": service_id, "input": {"goal": "run smoke checks"}},
        )
        assert_status(task, 201, "alice create task")
        task_id = task.json()["task_id"]
        assert task.json()["status"] == "created"

        assert_status(
            client.post(f"/tasks/{task_id}/accept", headers=alice_headers, json={"note": "not provider"}),
            403,
            "requester cannot accept provider task",
        )
        accepted = client.post(f"/tasks/{task_id}/accept", headers=bob_headers, json={"note": "accepted"})
        assert_status(accepted, 200, "provider accepts task")
        assert accepted.json()["status"] == "accepted"

        assert_status(
            client.post(f"/tasks/{task_id}/status", headers=alice_headers, json={"status": "in_progress"}),
            400,
            "requester cannot set provider execution status",
        )
        in_progress = client.post(f"/tasks/{task_id}/status", headers=bob_headers, json={"status": "in_progress"})
        assert_status(in_progress, 200, "provider marks task in progress")
        assert in_progress.json()["status"] == "in_progress"

        assert_status(
            client.post(f"/tasks/{task_id}/rating", headers=alice_headers, json={"score": 5, "comment": "too early"}),
            400,
            "task cannot be rated before verification",
        )

        artifact = client.post(
            "/artifacts",
            headers=bob_headers,
            json={
                "task_id": task_id,
                "filename": "smoke-result.json",
                "content_type": "application/json",
                "size_bytes": 42,
            },
        )
        assert_status(artifact, 201, "provider creates result artifact")
        artifact_id = artifact.json()["artifact_id"]

        submitted = client.post(
            f"/tasks/{task_id}/result",
            headers=bob_headers,
            json={
                "status": "submitted",
                "summary": "smoke checks passed",
                "artifact_ids": [artifact_id],
                "usage": {"gpu_seconds": 0},
                "result": {"passed": True},
            },
        )
        assert_status(submitted, 200, "provider submits result")
        assert submitted.json()["status"] == "submitted"

        receipts = client.get(f"/tasks/{task_id}/receipts", headers=alice_headers)
        assert_status(receipts, 200, "requester can list receipts")
        assert receipts.json()[0]["artifact_ids"] == [artifact_id]
        assert receipts.json()[0]["result"] == {"passed": True}

        assert_status(
            client.post(
                f"/tasks/{task_id}/verify",
                headers=bob_headers,
                json={"status": "verified", "result": {"passed": True}},
            ),
            403,
            "provider cannot verify own delivery",
        )
        verified = client.post(
            f"/tasks/{task_id}/verify",
            headers=alice_headers,
            json={
                "verification_type": "checklist",
                "status": "verified",
                "rubric": {"requires_artifact": True},
                "result": {"all_checks_passed": True},
                "evidence_artifact_ids": [artifact_id],
                "comment": "accepted",
            },
        )
        assert_status(verified, 201, "requester verifies task")
        assert verified.json()["status"] == "verified"
        assert verified.json()["evidence_artifact_ids"] == [artifact_id]

        final_task = client.get(f"/tasks/{task_id}", headers=bob_headers)
        assert_status(final_task, 200, "provider can read final task")
        assert final_task.json()["status"] == "verified"
        assert_status(
            client.post(f"/tasks/{task_id}/rating", headers=alice_headers, json={"score": 5, "comment": "verified"}),
            201,
            "rating allowed after verification",
        )
        reputation = client.get(f"/providers/{submitted.json()['provider_id']}/reputation", headers=alice_headers)
        assert_status(reputation, 200, "provider reputation")
        assert reputation.json()["completed_tasks"] == 1
        assert reputation.json()["average_score"] == 5.0

        rejected_task = client.post(
            "/tasks",
            headers=alice_headers,
            json={"service_id": service_id, "input": {"goal": "run failing checks"}},
        )
        assert_status(rejected_task, 201, "alice create second task")
        rejected_task_id = rejected_task.json()["task_id"]
        assert_status(client.post(f"/tasks/{rejected_task_id}/accept", headers=bob_headers, json={}), 200, "accept second")
        assert_status(
            client.post(
                f"/tasks/{rejected_task_id}/result",
                headers=bob_headers,
                json={"status": "submitted", "summary": "needs review", "result": {"passed": False}},
            ),
            200,
            "submit second",
        )
        rejected = client.post(
            f"/tasks/{rejected_task_id}/reject",
            headers=alice_headers,
            json={"verification_type": "human_approval", "result": {"reason": "missing evidence"}, "comment": "missing evidence"},
        )
        assert_status(rejected, 201, "requester rejects task")
        assert rejected.json()["status"] == "rejected"
        verifications = client.get(f"/tasks/{rejected_task_id}/verifications", headers=bob_headers)
        assert_status(verifications, 200, "provider lists verification records")
        assert verifications.json()[0]["status"] == "rejected"
