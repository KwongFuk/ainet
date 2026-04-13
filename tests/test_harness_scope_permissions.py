from __future__ import annotations

import importlib

from fastapi.testclient import TestClient


def load_test_app(monkeypatch, tmp_path):
    monkeypatch.setenv("AINET_DATABASE_URL", f"sqlite:///{tmp_path / 'ainet-test.db'}")
    monkeypatch.setenv("AINET_JWT_SECRET", "dev-test-secret-for-harness-scope-tests-123456")

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


def test_session_scopes_and_contact_permissions_are_enforced(monkeypatch, tmp_path):
    app_module = load_test_app(monkeypatch, tmp_path)

    from ainet.server.database import SessionLocal
    from ainet.server.models import DeviceSession, HumanAccount, utc_now
    from ainet.server.security import hash_password
    from sqlalchemy import select

    with TestClient(app_module.app) as client:
        with SessionLocal() as db:
            db.add(
                HumanAccount(
                    email="alice@example.com",
                    username="alice",
                    password_hash=hash_password("alice-password-000"),
                    email_verified_at=utc_now(),
                )
            )
            db.add(
                HumanAccount(
                    email="bob@example.com",
                    username="bob",
                    password_hash=hash_password("bob-password-000"),
                    email_verified_at=utc_now(),
                )
            )
            db.commit()

        alice_login = client.post(
            "/auth/login",
            json={"email": "alice@example.com", "password": "alice-password-000"},
        )
        assert_status(alice_login, 200, "alice login")
        alice_headers = {"Authorization": f"Bearer {alice_login.json()['access_token']}"}
        bob_login = client.post(
            "/auth/login",
            json={"email": "bob@example.com", "password": "bob-password-000"},
        )
        assert_status(bob_login, 200, "bob login")
        bob_headers = {"Authorization": f"Bearer {bob_login.json()['access_token']}"}

        with SessionLocal() as db:
            session = db.scalar(
                select(DeviceSession)
                .where(DeviceSession.user_id == alice_login.json()["user_id"])
                .order_by(DeviceSession.created_at.desc())
            )
            assert session is not None
            session.scopes = " ".join(sorted(app_module.LEGACY_FULL_SESSION_SCOPES))
            db.commit()

        assert_status(client.get("/identity", headers=alice_headers), 200, "legacy full token identity")
        alice_agent = client.post(
            "/agents",
            headers=alice_headers,
            json={"handle": "alice.agent", "runtime_type": "agent-cli", "key_id": "alice-key-v1"},
        )
        assert_status(alice_agent, 201, "legacy full token create agent")
        bob_agent = client.post(
            "/agents",
            headers=bob_headers,
            json={"handle": "bob.agent", "runtime_type": "agent-cli", "key_id": "bob-key-v1"},
        )
        assert_status(bob_agent, 201, "bob agent")
        bob_agent_id = bob_agent.json()["agent_id"]

        assert_status(
            client.post(
                "/messages",
                headers=alice_headers,
                json={"to_handle": "bob.agent", "body": "blocked without contact"},
            ),
            403,
            "message without contact",
        )

        contact = client.post(
            "/contacts",
            headers=alice_headers,
            json={"handle": "bob.agent", "permissions": ["dm"], "trust_level": "known"},
        )
        assert_status(contact, 201, "add dm contact")
        assert_status(
            client.post(
                "/messages",
                headers=alice_headers,
                json={"to_handle": "bob.agent", "body": "hello"},
            ),
            202,
            "send message with dm permission",
        )

        provider = client.post(
            "/providers",
            headers=bob_headers,
            json={"display_name": "Bob Service", "agent_id": bob_agent_id},
        )
        assert_status(provider, 201, "provider")
        service = client.post(
            "/service-profiles",
            headers=bob_headers,
            json={
                "provider_id": provider.json()["provider_id"],
                "title": "Bob Code Review",
                "capabilities": [{"name": "code_review"}],
            },
        )
        assert_status(service, 201, "service")

        assert_status(
            client.post(
                "/tasks",
                headers=alice_headers,
                json={"service_id": service.json()["service_id"], "input": {"goal": "review"}},
            ),
            403,
            "task without service_request permission",
        )
        updated_contact = client.patch(
            "/contacts/bob.agent",
            headers=alice_headers,
            json={"permissions": ["dm", "service_request"], "trust_level": "trusted"},
        )
        assert_status(updated_contact, 200, "grant service_request")
        assert_status(
            client.post(
                "/tasks",
                headers=alice_headers,
                json={"service_id": service.json()["service_id"], "input": {"goal": "review"}},
            ),
            201,
            "task with service_request permission",
        )

        invite = client.post(
            "/auth/invites",
            headers=alice_headers,
            json={"scopes": ["messages:read"], "expires_minutes": 5},
        )
        assert_status(invite, 201, "limited invite")
        accepted = client.post(
            "/auth/invites/accept",
            json={"token": invite.json()["token"], "device_name": "reader", "runtime_type": "agent-cli"},
        )
        assert_status(accepted, 200, "accept limited invite")
        limited_headers = {"Authorization": f"Bearer {accepted.json()['access_token']}"}
        assert accepted.json()["scopes"] == ["messages:read"]

        assert_status(
            client.get("/messages/search?query=hello", headers=limited_headers),
            200,
            "limited token can read messages",
        )
        assert_status(
            client.post(
                "/messages",
                headers=limited_headers,
                json={"to_handle": "bob.agent", "body": "should fail"},
            ),
            403,
            "limited token cannot send messages",
        )
        assert_status(client.get("/contacts", headers=limited_headers), 403, "limited token cannot read contacts")
        assert_status(
            client.post("/agents", headers=limited_headers, json={"handle": "evil.agent"}),
            403,
            "limited token cannot create agents",
        )
        assert_status(
            client.post(
                "/tasks",
                headers=limited_headers,
                json={"service_id": service.json()["service_id"], "input": {}},
            ),
            403,
            "limited token cannot create tasks",
        )
        assert_status(client.get("/events", headers=limited_headers), 403, "limited token cannot read events")
