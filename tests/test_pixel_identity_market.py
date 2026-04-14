from __future__ import annotations

import importlib

from fastapi.testclient import TestClient


def load_test_app(monkeypatch, tmp_path):
    monkeypatch.setenv("AINET_DATABASE_URL", f"sqlite:///{tmp_path / 'ainet-pixel-market.db'}")
    monkeypatch.setenv("AINET_JWT_SECRET", "dev-test-secret-for-pixel-market-123456")

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


def test_agent_identity_defaults_and_updates_include_pixel_profile(monkeypatch, tmp_path):
    app_module = load_test_app(monkeypatch, tmp_path)

    from ainet.server.database import SessionLocal

    with TestClient(app_module.app) as client:
        with SessionLocal() as db:
            seed_account(db, "alice@example.com", "alice", "alice-password-000")
            db.commit()

        alice_headers = login(client, "alice@example.com", "alice-password-000")
        created = client.post(
            "/agents",
            headers=alice_headers,
            json={"handle": "alice.agent", "runtime_type": "codex-cli"},
        )
        assert_status(created, 201, "create agent")
        body = created.json()
        assert body["avatar"]["style"] == "pixel"
        assert body["avatar"]["seed"] == "alice.agent"
        assert body["space_profile"]["office_theme"] == "terminal_den"
        assert body["space_profile"]["world_status"] == "available"

        updated = client.patch(
            f"/agents/{body['agent_id']}/identity",
            headers=alice_headers,
            json={
                "display_name": "Alice Pixel Smith",
                "persona_title": "Patch Smith",
                "avatar_palette": "rose",
                "avatar_layers": {"body": "pixel_core", "headgear": "runner_cap"},
                "office_theme": "blueprint_lab",
                "world_status": "building",
            },
        )
        assert_status(updated, 200, "update agent identity")
        updated_body = updated.json()
        assert updated_body["display_name"] == "Alice Pixel Smith"
        assert updated_body["persona_title"] == "Patch Smith"
        assert updated_body["avatar"]["palette"] == "rose"
        assert updated_body["avatar"]["layers"]["headgear"] == "runner_cap"
        assert updated_body["space_profile"]["office_theme"] == "blueprint_lab"
        assert updated_body["space_profile"]["world_status"] == "building"

        identity = client.get("/identity", headers=alice_headers)
        assert_status(identity, 200, "identity includes pixel profile")
        assert identity.json()["agents"][0]["persona_title"] == "Patch Smith"


def test_wallet_catalog_purchase_and_equip_cosmetic(monkeypatch, tmp_path):
    app_module = load_test_app(monkeypatch, tmp_path)

    from ainet.server.database import SessionLocal
    from ainet.server.models import WalletAccount
    from sqlalchemy import select

    with TestClient(app_module.app) as client:
        with SessionLocal() as db:
            seed_account(db, "alice@example.com", "alice", "alice-password-000")
            db.commit()

        alice_headers = login(client, "alice@example.com", "alice-password-000")
        agent = client.post(
            "/agents",
            headers=alice_headers,
            json={"handle": "alice.agent", "runtime_type": "codex-cli"},
        )
        assert_status(agent, 201, "create agent")
        agent_id = agent.json()["agent_id"]

        wallet = client.get("/wallet", headers=alice_headers)
        assert_status(wallet, 200, "wallet auto-created")
        assert wallet.json()["balance_credits"] == 0

        with SessionLocal() as db:
            row = db.scalar(select(WalletAccount).where(WalletAccount.owner_user_id == wallet.json()["owner_user_id"]))
            assert row is not None
            row.balance_credits = 300
            db.commit()

        catalog = client.get("/cosmetics/catalog", headers=alice_headers)
        assert_status(catalog, 200, "catalog")
        assert any(item["slug"] == "frame-neon-grid" for item in catalog.json())

        purchased = client.post("/cosmetics/purchase", headers=alice_headers, json={"slug": "frame-neon-grid"})
        assert_status(purchased, 200, "purchase cosmetic")
        purchase_body = purchased.json()
        assert purchase_body["wallet"]["balance_credits"] == 180
        assert purchase_body["inventory_item"]["item"]["slug"] == "frame-neon-grid"
        item_id = purchase_body["inventory_item"]["item"]["item_id"]

        inventory = client.get("/cosmetics/inventory", headers=alice_headers)
        assert_status(inventory, 200, "inventory after purchase")
        assert inventory.json()[0]["item"]["slug"] == "frame-neon-grid"
        assert inventory.json()[0]["equipped"] is False

        equipped = client.post(
            f"/agents/{agent_id}/appearance/equip",
            headers=alice_headers,
            json={"item_id": item_id},
        )
        assert_status(equipped, 200, "equip cosmetic")
        assert equipped.json()["equipped_cosmetics"][0]["slot"] == "frame"
        assert equipped.json()["equipped_cosmetics"][0]["slug"] == "frame-neon-grid"

        repurchased = client.post("/cosmetics/purchase", headers=alice_headers, json={"slug": "frame-neon-grid"})
        assert_status(repurchased, 200, "repurchase already-owned cosmetic")
        assert repurchased.json()["wallet"]["balance_credits"] == 180

        ledger = client.get("/wallet/ledger", headers=alice_headers)
        assert_status(ledger, 200, "wallet ledger")
        assert ledger.json()[0]["entry_type"] in {"cosmetic_reuse", "cosmetic_purchase"}
        assert any(entry["entry_type"] == "cosmetic_purchase" for entry in ledger.json())
