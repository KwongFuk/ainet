from __future__ import annotations

import json
import sqlite3
import tarfile

import pytest

from ainet.cli import main


def test_server_bootstrap_generates_self_hosted_scaffold(tmp_path):
    home = tmp_path / "home"
    output_dir = tmp_path / "deploy" / "agents.example.com"

    rc = main(
        [
            "--home",
            str(home),
            "server",
            "bootstrap",
            "--domain",
            "agents.example.com",
            "--email",
            "admin@example.com",
            "--output-dir",
            str(output_dir),
        ]
    )

    assert rc == 0
    assert (output_dir / ".env").exists()
    assert (output_dir / "compose.yaml").exists()
    assert (output_dir / "Caddyfile").exists()
    assert (output_dir / "README.md").exists()
    assert (output_dir / ".gitignore").exists()
    assert (output_dir / "data").is_dir()
    assert (output_dir / "caddy_data").is_dir()
    assert (output_dir / "caddy_config").is_dir()

    env_text = (output_dir / ".env").read_text(encoding="utf-8")
    assert "AINET_ENVIRONMENT=production" in env_text
    assert "AINET_DATABASE_URL=sqlite:////data/ainet.db" in env_text
    assert "AINET_SMTP_FROM=no-reply@agents.example.com" in env_text
    assert "dev-change-me" not in env_text

    jwt_line = next(line for line in env_text.splitlines() if line.startswith("AINET_JWT_SECRET="))
    assert len(jwt_line.split("=", 1)[1]) >= 32

    compose_text = (output_dir / "compose.yaml").read_text(encoding="utf-8")
    assert "services:" in compose_text
    assert "caddy" in compose_text
    assert "AINET API" not in compose_text

    readme_text = (output_dir / "README.md").read_text(encoding="utf-8")
    assert "docker compose up -d --build" in readme_text


def test_server_bootstrap_requires_force_for_non_empty_output(tmp_path):
    home = tmp_path / "home"
    output_dir = tmp_path / "deploy"
    output_dir.mkdir(parents=True)
    (output_dir / "note.txt").write_text("occupied\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="use --force to overwrite"):
        main(
            [
                "--home",
                str(home),
                "server",
                "bootstrap",
                "--domain",
                "agents.example.com",
                "--email",
                "admin@example.com",
                "--output-dir",
                str(output_dir),
            ]
        )


def test_server_bootstrap_generates_postgresql_scaffold(tmp_path):
    home = tmp_path / "home"
    output_dir = tmp_path / "deploy" / "agents.example.com"

    rc = main(
        [
            "--home",
            str(home),
            "server",
            "bootstrap",
            "--domain",
            "agents.example.com",
            "--email",
            "admin@example.com",
            "--database-backend",
            "postgresql",
            "--output-dir",
            str(output_dir),
        ]
    )

    assert rc == 0
    assert (output_dir / "postgres_data").is_dir()

    env_text = (output_dir / ".env").read_text(encoding="utf-8")
    assert "AINET_DATABASE_URL=postgresql://ainet:" in env_text
    assert "AINET_POSTGRES_DB=ainet" in env_text
    assert "AINET_POSTGRES_USER=ainet" in env_text
    assert "AINET_POSTGRES_PASSWORD=" in env_text

    compose_text = (output_dir / "compose.yaml").read_text(encoding="utf-8")
    assert "postgres:" in compose_text
    assert "postgres:16" in compose_text
    assert "condition: service_healthy" in compose_text
    assert "postgres_data:/var/lib/postgresql/data" in compose_text

    readme_text = (output_dir / "README.md").read_text(encoding="utf-8")
    assert "PostgreSQL" in readme_text


def test_mcp_install_writes_json_config(tmp_path):
    home = tmp_path / "home"
    output = tmp_path / "mcp.json"

    rc = main(
        [
            "--home",
            str(home),
            "mcp",
            "install",
            "--target",
            "json",
            "--output",
            str(output),
            "--command",
            "ainet-mcp",
            "--arg=--transport=stdio",
        ]
    )

    assert rc == 0
    config = json.loads(output.read_text(encoding="utf-8"))
    server = config["mcpServers"]["ainet"]
    assert server["command"] == "ainet-mcp"
    assert server["args"] == ["--transport=stdio"]
    assert server["env"]["AINET_API_URL"] == "http://127.0.0.1:8787"


def test_server_backup_and_restore_round_trip_for_sqlite(tmp_path, monkeypatch):
    db_path = tmp_path / "ainet.db"
    backup_path = tmp_path / "ainet-backup.tar.gz"
    monkeypatch.setenv("AINET_DATABASE_URL", f"sqlite:///{db_path}")

    conn = sqlite3.connect(db_path)
    conn.execute("create table demo (id integer primary key, value text)")
    conn.execute("insert into demo(value) values ('before-backup')")
    conn.commit()
    conn.close()

    rc = main(["server", "backup", "--output", str(backup_path)])
    assert rc == 0
    assert backup_path.exists()

    with tarfile.open(backup_path, "r:gz") as archive:
        names = archive.getnames()
        assert "manifest.json" in names
        assert "db/ainet.db" in names

    conn = sqlite3.connect(db_path)
    conn.execute("delete from demo")
    conn.execute("insert into demo(value) values ('after-backup')")
    conn.commit()
    conn.close()

    rc = main(["server", "restore", "--input", str(backup_path), "--force"])
    assert rc == 0

    conn = sqlite3.connect(db_path)
    rows = conn.execute("select value from demo order by id").fetchall()
    conn.close()
    assert rows == [("before-backup",)]
