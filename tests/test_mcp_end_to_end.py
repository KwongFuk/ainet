from __future__ import annotations

import importlib
import urllib.parse

from fastapi.testclient import TestClient


def load_test_app(monkeypatch, tmp_path):
    monkeypatch.setenv("AINET_DATABASE_URL", f"sqlite:///{tmp_path / 'ainet-mcp-e2e.db'}")
    monkeypatch.setenv("AINET_JWT_SECRET", "dev-test-secret-for-mcp-e2e-tests-123456")

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


class BackendMcpClient:
    def __init__(self, test_client: TestClient, headers_state: dict[str, dict[str, str]]) -> None:
        self._client = test_client
        self._headers_state = headers_state

    def request(self, method: str, path: str, payload=None, query=None):
        query = {key: value for key, value in (query or {}).items() if value is not None}
        url = path
        if query:
            url = f"{url}?{urllib.parse.urlencode(query, doseq=True)}"
        response = self._client.request(method, url, json=payload, headers=self._headers_state["headers"])
        assert response.status_code < 400, f"MCP backend call failed: {response.status_code} {response.text}"
        return response.json() if response.text else {}


def test_mcp_service_quote_payment_flow(monkeypatch, tmp_path):
    app_module = load_test_app(monkeypatch, tmp_path)

    from ainet.server.database import SessionLocal
    import ainet.protocols.mcp_server as mcp_server

    with TestClient(app_module.app) as client:
        with SessionLocal() as db:
            seed_account(db, "alice@example.com", "alice", "alice-password-000")
            seed_account(db, "bob@example.com", "bob", "bob-password-000")
            db.commit()

        alice_headers = login(client, "alice@example.com", "alice-password-000")
        bob_headers = login(client, "bob@example.com", "bob-password-000")

        bob_agent = client.post(
            "/agents",
            headers=bob_headers,
            json={"handle": "bob.agent", "runtime_type": "runtime"},
        )
        assert_status(bob_agent, 201, "bob agent")

        contact = client.post(
            "/contacts",
            headers=alice_headers,
            json={"handle": "bob.agent", "permissions": ["service_request"], "trust_level": "trusted"},
        )
        assert_status(contact, 201, "alice adds bob contact")

        provider = client.post(
            "/providers",
            headers=bob_headers,
            json={"display_name": "Bob MCP Runner", "agent_id": bob_agent.json()["agent_id"]},
        )
        assert_status(provider, 201, "bob provider")

        service = client.post(
            "/service-profiles",
            headers=bob_headers,
            json={
                "provider_id": provider.json()["provider_id"],
                "title": "MCP Verifiable Runner",
                "category": "resource",
                "capabilities": [{"name": "gpu_train"}],
            },
        )
        assert_status(service, 201, "bob service")

        task = client.post(
            "/tasks",
            headers=alice_headers,
            json={"service_id": service.json()["service_id"], "input": {"goal": "mcp quoted task"}},
        )
        assert_status(task, 201, "alice task")

        current = {"headers": alice_headers}
        monkeypatch.setattr(mcp_server, "client", lambda: BackendMcpClient(client, current))

        me = mcp_server.get_me()
        assert me["account"]["email"] == "alice@example.com"

        service_search = mcp_server.search_services(query="MCP", limit=10)
        assert service_search["services"][0]["service_id"] == service.json()["service_id"]

        current["headers"] = bob_headers
        quote = mcp_server.create_quote(task.json()["task_id"], 1900, terms={"delivery": "same day"})
        assert quote["quote"]["amount_cents"] == 1900
        quote_id = quote["quote"]["quote_id"]

        current["headers"] = alice_headers
        order = mcp_server.accept_quote(quote_id, settlement_mode="internal_credit")
        assert order["order"]["payment"]["status"] == "authorized"

        payments = mcp_server.list_payments(limit=10)
        assert payments["payments"][0]["status"] == "authorized"

        events = mcp_server.poll_events(after_id=0, limit=20)
        assert any(row["event_type"] == "quote.created" for row in events["events"])
