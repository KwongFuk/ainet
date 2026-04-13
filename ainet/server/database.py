from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


def make_engine():
    settings = get_settings()
    connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    return create_engine(settings.database_url, connect_args=connect_args, future=True)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)


def init_db() -> None:
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    apply_sqlite_compat_migrations()


def apply_sqlite_compat_migrations() -> None:
    """Keep existing local SQLite development databases usable before Alembic."""
    if engine.dialect.name != "sqlite":
        return
    additions = {
        "agent_accounts": {
            "public_key": "TEXT",
            "key_id": "VARCHAR(120)",
            "key_rotated_at": "DATETIME",
            "verification_status": "VARCHAR(40) DEFAULT 'unverified' NOT NULL",
        },
        "contacts": {
            "contact_type": "VARCHAR(40) DEFAULT 'agent' NOT NULL",
            "trust_level": "VARCHAR(40) DEFAULT 'known' NOT NULL",
            "permissions_json": "TEXT DEFAULT '[\"dm\"]' NOT NULL",
            "muted": "BOOLEAN DEFAULT 0 NOT NULL",
            "blocked": "BOOLEAN DEFAULT 0 NOT NULL",
        },
    }
    with engine.begin() as conn:
        for table, columns in additions.items():
            existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
            if not existing:
                continue
            for column, ddl in columns.items():
                if column not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
