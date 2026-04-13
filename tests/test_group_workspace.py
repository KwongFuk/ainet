from __future__ import annotations

import importlib

from fastapi.testclient import TestClient


def load_test_app(monkeypatch, tmp_path):
    monkeypatch.setenv("AINET_DATABASE_URL", f"sqlite:///{tmp_path / 'ainet-group-test.db'}")
    monkeypatch.setenv("AINET_JWT_SECRET", "dev-test-secret-for-group-workspace-tests-123456")

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


def test_group_workspace_links_members_messages_memory_and_tasks(monkeypatch, tmp_path):
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
            alice_session.scopes = " ".join(sorted(app_module.PRE_GROUP_DEFAULT_SESSION_SCOPES))
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
        assert_status(client.get("/groups", headers=limited_headers), 403, "limited token cannot read groups")

        alice_agent = client.post(
            "/agents",
            headers=alice_headers,
            json={"handle": "alice.agent", "runtime_type": "codex-cli"},
        )
        assert_status(alice_agent, 201, "alice agent")
        bob_agent = client.post(
            "/agents",
            headers=bob_headers,
            json={"handle": "bob.agent", "runtime_type": "openclaw"},
        )
        assert_status(bob_agent, 201, "bob agent")
        bob_agent_id = bob_agent.json()["agent_id"]

        blocked_invite = client.post(
            "/groups",
            headers=alice_headers,
            json={"handle": "blocked.workspace", "title": "Blocked Workspace"},
        )
        assert_status(blocked_invite, 201, "group before contact")
        assert_status(
            client.post(
                f"/groups/{blocked_invite.json()['group_id']}/members",
                headers=alice_headers,
                json={"handle": "bob.agent"},
            ),
            403,
            "group invite requires contact permission",
        )

        contact = client.post(
            "/contacts",
            headers=alice_headers,
            json={
                "handle": "bob.agent",
                "permissions": ["dm", "group_invite", "service_request"],
                "trust_level": "trusted",
            },
        )
        assert_status(contact, 201, "alice contact bob")

        group = client.post(
            "/groups",
            headers=alice_headers,
            json={"handle": "lab.workspace", "title": "Lab Workspace", "description": "GPU task coordination"},
        )
        assert_status(group, 201, "create group")
        group_id = group.json()["group_id"]
        assert "group_invite" not in group.json()["default_permissions"]

        member = client.post(
            f"/groups/{group_id}/members",
            headers=alice_headers,
            json={"handle": "bob.agent"},
        )
        assert_status(member, 201, "invite bob agent")
        assert member.json()["agent_id"] == bob_agent_id
        assert "group_read" in member.json()["permissions"]
        assert "group_invite" not in member.json()["permissions"]

        bob_groups = client.get("/groups", headers=bob_headers)
        assert_status(bob_groups, 200, "bob list groups")
        assert [row["handle"] for row in bob_groups.json()] == ["lab.workspace"]
        assert_status(client.get(f"/groups/{group_id}/members", headers=bob_headers), 200, "bob read members")

        message = client.post(
            f"/groups/{group_id}/messages",
            headers=alice_headers,
            json={
                "body": "assign GPU training smoke test to bob.agent",
                "from_agent_id": alice_agent.json()["agent_id"],
                "metadata": {"intent": "resource-task"},
            },
        )
        assert_status(message, 201, "alice send group message")
        messages = client.get(f"/groups/{group_id}/messages", headers=bob_headers)
        assert_status(messages, 200, "bob read group messages")
        assert messages.json()[0]["metadata"] == {"intent": "resource-task"}

        memory = client.post(f"/groups/{group_id}/memory/refresh?limit=20", headers=alice_headers)
        assert_status(memory, 200, "alice refresh group memory")
        assert "assign GPU training smoke test" in memory.json()["summary"]
        assert_status(
            client.post(f"/groups/{group_id}/memory/refresh?limit=20", headers=bob_headers),
            403,
            "member without memory_write cannot refresh group memory",
        )

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
                "title": "GPU Task Runner",
                "category": "resource",
                "capabilities": [{"name": "gpu_train"}],
            },
        )
        assert_status(service, 201, "bob service")
        task = client.post(
            "/tasks",
            headers=alice_headers,
            json={"service_id": service.json()["service_id"], "input": {"goal": "train a tiny smoke model"}},
        )
        assert_status(task, 201, "alice create service task")

        attached = client.post(
            f"/groups/{group_id}/tasks",
            headers=alice_headers,
            json={"task_id": task.json()["task_id"], "note": "resource protocol smoke task"},
        )
        assert_status(attached, 201, "attach task to group")
        assert attached.json()["task"]["input"]["goal"] == "train a tiny smoke model"

        bob_tasks = client.get(f"/groups/{group_id}/tasks", headers=bob_headers)
        assert_status(bob_tasks, 200, "bob list group tasks")
        assert bob_tasks.json()[0]["task_id"] == task.json()["task_id"]
