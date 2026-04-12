from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class HumanAccount(Base):
    __tablename__ = "human_accounts"

    user_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("usr"))
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    agents: Mapped[list["AgentAccount"]] = relationship(back_populates="owner")
    sessions: Mapped[list["DeviceSession"]] = relationship(back_populates="user")


class AgentAccount(Base):
    __tablename__ = "agent_accounts"

    agent_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("agt"))
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("human_accounts.user_id"), index=True)
    handle: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    runtime_type: Mapped[str] = mapped_column(String(80), default="agent")
    service_profile_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    owner: Mapped[HumanAccount] = relationship(back_populates="agents")


class DeviceSession(Base):
    __tablename__ = "device_sessions"

    session_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("sess"))
    user_id: Mapped[str] = mapped_column(ForeignKey("human_accounts.user_id"), index=True)
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("agent_accounts.agent_id"), nullable=True, index=True)
    device_name: Mapped[str] = mapped_column(String(160))
    runtime_type: Mapped[str] = mapped_column(String(80), default="agent")
    access_token_hash: Mapped[str] = mapped_column(String(128), index=True)
    scopes: Mapped[str] = mapped_column(Text, default="")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    user: Mapped[HumanAccount] = relationship(back_populates="sessions")


class EmailVerificationCode(Base):
    __tablename__ = "email_verification_codes"

    code_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("code"))
    user_id: Mapped[str] = mapped_column(ForeignKey("human_accounts.user_id"), index=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    code_hash: Mapped[str] = mapped_column(String(128), index=True)
    purpose: Mapped[str] = mapped_column(String(40), default="signup")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Invite(Base):
    __tablename__ = "invites"

    invite_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("inv"))
    invite_type: Mapped[str] = mapped_column(String(40), index=True)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("human_accounts.user_id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    scopes: Mapped[str] = mapped_column(Text, default="")
    max_uses: Mapped[int] = mapped_column(Integer, default=1)
    use_count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class QueuedEvent(Base):
    __tablename__ = "queued_events"
    __table_args__ = (UniqueConstraint("event_id", name="uq_queued_events_event_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(40), default=lambda: new_id("evt"), index=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    account_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

