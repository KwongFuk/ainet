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


class Contact(Base):
    __tablename__ = "contacts"
    __table_args__ = (UniqueConstraint("owner_user_id", "agent_id", name="uq_contacts_owner_agent"),)

    contact_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("ctc"))
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("human_accounts.user_id"), index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agent_accounts.agent_id"), index=True)
    handle_snapshot: Mapped[str] = mapped_column(String(120), index=True)
    label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class Conversation(Base):
    __tablename__ = "conversations"

    conversation_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("conv"))
    initiator_user_id: Mapped[str] = mapped_column(ForeignKey("human_accounts.user_id"), index=True)
    target_user_id: Mapped[str] = mapped_column(ForeignKey("human_accounts.user_id"), index=True)
    target_agent_id: Mapped[str] = mapped_column(ForeignKey("agent_accounts.agent_id"), index=True)
    target_handle_snapshot: Mapped[str] = mapped_column(String(120), index=True)
    conversation_type: Mapped[str] = mapped_column(String(40), default="dm", index=True)
    subject: Mapped[str | None] = mapped_column(String(200), nullable=True)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SocialMessage(Base):
    __tablename__ = "social_messages"

    message_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("msg"))
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.conversation_id"), index=True)
    from_user_id: Mapped[str] = mapped_column(ForeignKey("human_accounts.user_id"), index=True)
    from_agent_id: Mapped[str | None] = mapped_column(ForeignKey("agent_accounts.agent_id"), nullable=True, index=True)
    from_handle: Mapped[str] = mapped_column(String(120), index=True)
    to_agent_id: Mapped[str] = mapped_column(ForeignKey("agent_accounts.agent_id"), index=True)
    to_handle: Mapped[str] = mapped_column(String(120), index=True)
    message_type: Mapped[str] = mapped_column(String(40), default="text", index=True)
    body: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ConversationMemory(Base):
    __tablename__ = "conversation_memories"
    __table_args__ = (UniqueConstraint("conversation_id", "owner_user_id", name="uq_conversation_memories_conversation_owner"),)

    memory_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("mem"))
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.conversation_id"), index=True)
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("human_accounts.user_id"), index=True)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    key_facts_json: Mapped[str] = mapped_column(Text, default="[]")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class Provider(Base):
    __tablename__ = "providers"

    provider_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("prov"))
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("human_accounts.user_id"), index=True)
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("agent_accounts.agent_id"), nullable=True, index=True)
    display_name: Mapped[str] = mapped_column(String(160))
    provider_type: Mapped[str] = mapped_column(String(40), default="agent")
    verification_status: Mapped[str] = mapped_column(String(40), default="unverified", index=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class ServiceProfile(Base):
    __tablename__ = "service_profiles"

    service_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("svc"))
    provider_id: Mapped[str] = mapped_column(ForeignKey("providers.provider_id"), index=True)
    title: Mapped[str] = mapped_column(String(200), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(80), default="general", index=True)
    pricing_model: Mapped[str] = mapped_column(String(60), default="quote")
    currency: Mapped[str] = mapped_column(String(12), default="credits")
    base_price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_schema_json: Mapped[str] = mapped_column(Text, default="{}")
    output_schema_json: Mapped[str] = mapped_column(Text, default="{}")
    sla_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(40), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class Capability(Base):
    __tablename__ = "capabilities"

    capability_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("cap"))
    service_id: Mapped[str] = mapped_column(ForeignKey("service_profiles.service_id"), index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    input_schema_json: Mapped[str] = mapped_column(Text, default="{}")
    output_schema_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ServiceTask(Base):
    __tablename__ = "service_tasks"

    task_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("task"))
    requester_user_id: Mapped[str] = mapped_column(ForeignKey("human_accounts.user_id"), index=True)
    service_id: Mapped[str] = mapped_column(ForeignKey("service_profiles.service_id"), index=True)
    capability_id: Mapped[str | None] = mapped_column(ForeignKey("capabilities.capability_id"), nullable=True, index=True)
    provider_id: Mapped[str] = mapped_column(ForeignKey("providers.provider_id"), index=True)
    status: Mapped[str] = mapped_column(String(40), default="submitted", index=True)
    input_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class Artifact(Base):
    __tablename__ = "artifacts"

    artifact_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("art"))
    task_id: Mapped[str | None] = mapped_column(ForeignKey("service_tasks.task_id"), nullable=True, index=True)
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("human_accounts.user_id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    storage_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Quote(Base):
    __tablename__ = "quotes"

    quote_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("quote"))
    task_id: Mapped[str] = mapped_column(ForeignKey("service_tasks.task_id"), index=True)
    provider_id: Mapped[str] = mapped_column(ForeignKey("providers.provider_id"), index=True)
    amount_cents: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(12), default="credits")
    status: Mapped[str] = mapped_column(String(40), default="offered", index=True)
    terms_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ServiceOrder(Base):
    __tablename__ = "service_orders"

    order_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("ord"))
    task_id: Mapped[str] = mapped_column(ForeignKey("service_tasks.task_id"), index=True)
    quote_id: Mapped[str | None] = mapped_column(ForeignKey("quotes.quote_id"), nullable=True, index=True)
    buyer_user_id: Mapped[str] = mapped_column(ForeignKey("human_accounts.user_id"), index=True)
    provider_id: Mapped[str] = mapped_column(ForeignKey("providers.provider_id"), index=True)
    status: Mapped[str] = mapped_column(String(40), default="created", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class PaymentRecord(Base):
    __tablename__ = "payment_records"

    payment_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("pay"))
    order_id: Mapped[str] = mapped_column(ForeignKey("service_orders.order_id"), index=True)
    amount_cents: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(12), default="credits")
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    provider_reference: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Rating(Base):
    __tablename__ = "ratings"

    rating_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("rate"))
    task_id: Mapped[str] = mapped_column(ForeignKey("service_tasks.task_id"), index=True)
    reviewer_user_id: Mapped[str] = mapped_column(ForeignKey("human_accounts.user_id"), index=True)
    provider_id: Mapped[str] = mapped_column(ForeignKey("providers.provider_id"), index=True)
    score: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    audit_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("audit"))
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("human_accounts.user_id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(120), index=True)
    target_type: Mapped[str] = mapped_column(String(80), index=True)
    target_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
