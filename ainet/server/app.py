from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import timedelta
from datetime import datetime, timezone

import jwt
import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .console import community_console_html
from .database import get_db, init_db
from .emailer import send_verification_code
from .models import (
    AgentAccount,
    Artifact,
    AuditLog,
    Capability,
    CommunityReport,
    Contact,
    Conversation,
    ConversationMemory,
    DeviceSession,
    EmailVerificationCode,
    Group,
    GroupMember,
    GroupMemory,
    GroupMessage,
    GroupTaskContext,
    HumanAccount,
    Invite,
    NeedBid,
    NeedDiscussion,
    NeedPost,
    PaymentRecord,
    Provider,
    QueuedEvent,
    Quote,
    Rating,
    ServiceProfile,
    ServiceOrder,
    ServiceTask,
    SocialMessage,
    TaskReceipt,
    VerificationRecord,
    utc_now,
)
from .queue import EventBus
from .schemas import (
    AgentCreateRequest,
    AgentIdentityUpdateRequest,
    AgentResponse,
    AgentSummaryResponse,
    AuditLogResponse,
    ArtifactCreateRequest,
    ArtifactResponse,
    CapabilityInput,
    CommunityReportCreateRequest,
    CommunityReportResponse,
    ContactCreateRequest,
    ContactResponse,
    ContactUpdateRequest,
    ConversationCreateRequest,
    ConversationMemoryRequest,
    ConversationMemoryResponse,
    ConversationResponse,
    EventResponse,
    GroupCreateRequest,
    GroupMemoryRequest,
    GroupMemoryResponse,
    GroupMemberAddRequest,
    GroupMemberResponse,
    GroupMessageRequest,
    GroupMessageResponse,
    GroupResponse,
    GroupTaskAttachRequest,
    GroupTaskContextResponse,
    IdentityResponse,
    InviteAcceptRequest,
    InviteCreateRequest,
    InviteResponse,
    LoginRequest,
    MeResponse,
    MessageResponse,
    MessageRequest,
    NeedAcceptBidRequest,
    NeedAcceptBidResponse,
    NeedBidCreateRequest,
    NeedBidResponse,
    NeedDiscussionCreateRequest,
    NeedDiscussionResponse,
    NeedModerationRequest,
    NeedPostCreateRequest,
    NeedPostResponse,
    OrderResponse,
    PaymentResponse,
    ProviderCreateRequest,
    ProviderCardResponse,
    ProviderReputationResponse,
    ProviderResponse,
    ProviderVerificationUpdateRequest,
    QuoteAcceptRequest,
    QuoteCreateRequest,
    QuoteResponse,
    RatingCreateRequest,
    RatingResponse,
    ServiceProfileCreateRequest,
    ServiceCardResponse,
    ServiceProfileResponse,
    SignupRequest,
    SignupResponse,
    SessionResponse,
    TaskCreateRequest,
    TaskAcceptRequest,
    TaskResponse,
    TaskReceiptResponse,
    TaskResultRequest,
    TaskStatusUpdateRequest,
    TokenResponse,
    VerificationRecordRequest,
    VerificationRecordResponse,
    VerifyEmailRequest,
)
from .security import (
    create_access_token,
    decode_access_token,
    hash_password,
    hash_secret,
    random_code,
    secrets_equal,
    verify_password,
)

logger = logging.getLogger(__name__)

LEGACY_FULL_SESSION_SCOPES = {
    "profile:read",
    "profile:write",
    "messages:read",
    "messages:send",
    "contacts:read",
    "contacts:write",
}
PRE_GROUP_DEFAULT_SESSION_SCOPES = {
    "profile:read",
    "profile:write",
    "sessions:read",
    "sessions:write",
    "messages:read",
    "messages:send",
    "contacts:read",
    "contacts:write",
    "services:read",
    "services:write",
    "events:read",
    "audit:read",
}
PRE_COMMUNITY_DEFAULT_SESSION_SCOPES = {
    "profile:read",
    "profile:write",
    "sessions:read",
    "sessions:write",
    "messages:read",
    "messages:send",
    "contacts:read",
    "contacts:write",
    "services:read",
    "services:write",
    "groups:read",
    "groups:write",
    "events:read",
    "audit:read",
}
DEFAULT_SESSION_SCOPES = [
    "profile:read",
    "profile:write",
    "sessions:read",
    "sessions:write",
    "messages:read",
    "messages:send",
    "contacts:read",
    "contacts:write",
    "services:read",
    "services:write",
    "groups:read",
    "groups:write",
    "community:read",
    "community:write",
    "events:read",
    "audit:read",
]
KNOWN_SESSION_SCOPES = set(DEFAULT_SESSION_SCOPES)
KNOWN_CONTACT_PERMISSIONS = {
    "dm",
    "group_invite",
    "service_request",
    "artifact_read",
    "artifact_write",
    "memory_read",
    "memory_write",
    "requires_human_approval",
}
DEFAULT_GROUP_PERMISSIONS = [
    "group_read",
    "group_write",
    "group_invite",
    "task_create",
    "memory_read",
    "memory_write",
]
KNOWN_GROUP_PERMISSIONS = set(DEFAULT_GROUP_PERMISSIONS)
KNOWN_TRUST_LEVELS = {"unknown", "known", "trusted", "privileged", "blocked"}
KNOWN_TASK_STATUSES = {
    "created",
    "quoted",
    "accepted",
    "in_progress",
    "submitted",
    "verification_running",
    "verified",
    "rejected",
    "failed",
    "cancelled",
    "completed",
}
PROVIDER_WRITABLE_TASK_STATUSES = {"accepted", "in_progress", "submitted", "verification_running", "failed", "cancelled", "completed"}
REQUESTER_WRITABLE_TASK_STATUSES = {"cancelled"}
FINAL_TASK_STATUSES = {"verified", "rejected", "failed", "cancelled", "completed"}
VERIFICATION_TASK_STATUSES = {"verified", "rejected"}
KNOWN_NEED_VISIBILITIES = {"public", "private"}
KNOWN_NEED_STATUSES = {"open", "assigned", "completed", "cancelled", "closed", "hidden"}
KNOWN_BID_STATUSES = {"proposed", "accepted", "rejected", "withdrawn"}
KNOWN_COMMUNITY_REPORT_TARGETS = {"need", "need_comment", "need_bid"}
KNOWN_COMMUNITY_MODERATION_ACTIONS = {"close", "hide"}
KNOWN_PROVIDER_VERIFICATION_STATUSES = {"unverified", "pending", "verified", "suspended"}


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def dump_json(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def parse_json(value: str) -> dict:
    return json.loads(value or "{}")


def parse_json_list(value: str) -> list:
    parsed = json.loads(value or "[]")
    return parsed if isinstance(parsed, list) else []


def normalize_contact_permissions(permissions: list[str] | None) -> list[str]:
    if permissions is None:
        permissions = ["dm"]
    normalized: list[str] = []
    for permission in permissions:
        item = permission.strip().lower()
        if not item:
            continue
        if item not in KNOWN_CONTACT_PERMISSIONS and not item.startswith("service:"):
            raise HTTPException(status_code=400, detail=f"unsupported contact permission: {permission}")
        if item not in normalized:
            normalized.append(item)
    return normalized


def normalize_group_permissions(permissions: list[str] | None, *, default_full: bool = False) -> list[str]:
    if not permissions:
        permissions = DEFAULT_GROUP_PERMISSIONS if default_full else ["group_read", "group_write", "task_create", "memory_read"]
    normalized: list[str] = []
    for permission in permissions:
        item = permission.strip().lower()
        if not item:
            continue
        if item not in KNOWN_GROUP_PERMISSIONS:
            raise HTTPException(status_code=400, detail=f"unsupported group permission: {permission}")
        if item not in normalized:
            normalized.append(item)
    return normalized


def normalize_trust_level(trust_level: str) -> str:
    normalized = trust_level.strip().lower()
    if normalized not in KNOWN_TRUST_LEVELS:
        raise HTTPException(status_code=400, detail=f"unsupported trust level: {trust_level}")
    return normalized


def normalize_task_status(status_value: str) -> str:
    normalized = status_value.strip().lower()
    if normalized not in KNOWN_TASK_STATUSES:
        raise HTTPException(status_code=400, detail=f"unsupported task status: {status_value}")
    return normalized


def normalize_need_visibility(visibility: str) -> str:
    normalized = visibility.strip().lower()
    if normalized not in KNOWN_NEED_VISIBILITIES:
        raise HTTPException(status_code=400, detail=f"unsupported need visibility: {visibility}")
    return normalized


def normalize_need_status(status_value: str) -> str:
    normalized = status_value.strip().lower()
    if normalized not in KNOWN_NEED_STATUSES:
        raise HTTPException(status_code=400, detail=f"unsupported need status: {status_value}")
    return normalized


def normalize_community_report_reason(reason: str) -> str:
    normalized = reason.strip().lower().replace(" ", "_")
    if len(normalized) < 2:
        raise HTTPException(status_code=400, detail="report reason must be at least 2 characters")
    return normalized


def normalize_provider_verification_status(status_value: str) -> str:
    normalized = status_value.strip().lower()
    if normalized not in KNOWN_PROVIDER_VERIFICATION_STATUSES:
        raise HTTPException(status_code=400, detail=f"unsupported provider verification status: {status_value}")
    return normalized


def normalize_need_tags(tags: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for tag in tags or []:
        item = tag.strip().lower()
        if not item:
            continue
        if len(item) > 80:
            raise HTTPException(status_code=400, detail=f"need tag is too long: {tag}")
        if item not in normalized:
            normalized.append(item)
    if len(normalized) > 25:
        raise HTTPException(status_code=400, detail="need tags are limited to 25 entries")
    return normalized


def effective_session_scopes(scopes_text: str) -> set[str]:
    scopes = set(scopes_text.split())
    if scopes in (LEGACY_FULL_SESSION_SCOPES, PRE_GROUP_DEFAULT_SESSION_SCOPES, PRE_COMMUNITY_DEFAULT_SESSION_SCOPES):
        return set(DEFAULT_SESSION_SCOPES)
    return scopes


def contains_pattern(value: str) -> str:
    escaped = value.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return as_utc(value).isoformat()


def capability_response(capability: Capability) -> CapabilityInput:
    return CapabilityInput(
        name=capability.name,
        description=capability.description,
        input_schema=parse_json(capability.input_schema_json),
        output_schema=parse_json(capability.output_schema_json),
    )


def agent_response(agent: AgentAccount) -> AgentResponse:
    return AgentResponse(
        agent_id=agent.agent_id,
        handle=agent.handle,
        display_name=agent.display_name,
        runtime_type=agent.runtime_type,
        public_key=agent.public_key,
        key_id=agent.key_id,
        key_rotated_at=iso(agent.key_rotated_at),
        verification_status=agent.verification_status,
    )


def agent_summary_response(agent: AgentAccount) -> AgentSummaryResponse:
    return AgentSummaryResponse(
        agent_id=agent.agent_id,
        handle=agent.handle,
        runtime_type=agent.runtime_type,
        verification_status=agent.verification_status,
    )


def provider_reputation_stats(db: Session, provider_id: str) -> tuple[int, float | None, int, int]:
    ratings = db.scalars(select(Rating).where(Rating.provider_id == provider_id)).all()
    completed_tasks = db.scalars(
        select(ServiceTask)
        .where(ServiceTask.provider_id == provider_id)
        .where(ServiceTask.status.in_(["verified", "completed"]))
    ).all()
    orders_count = len(db.scalars(select(ServiceOrder).where(ServiceOrder.provider_id == provider_id)).all())
    average_score = sum(rating.score for rating in ratings) / len(ratings) if ratings else None
    return len(ratings), average_score, len(completed_tasks), orders_count


def provider_trust_badge(provider: Provider, *, rating_count: int, average_score: float | None, completed_tasks: int) -> str:
    if provider.verification_status == "suspended":
        return "suspended"
    if provider.verification_status == "verified":
        return "verified"
    if provider.verification_status == "pending":
        return "pending"
    if completed_tasks >= 3 and average_score is not None and average_score >= 4.5:
        return "trusted"
    if rating_count > 0:
        return "rated"
    return "new"


def provider_card_response(db: Session, provider: Provider) -> ProviderCardResponse:
    rating_count, average_score, completed_tasks, orders_count = provider_reputation_stats(db, provider.provider_id)
    return ProviderCardResponse(
        provider_id=provider.provider_id,
        display_name=provider.display_name,
        provider_type=provider.provider_type,
        verification_status=provider.verification_status,
        trust_badge=provider_trust_badge(
            provider,
            rating_count=rating_count,
            average_score=average_score,
            completed_tasks=completed_tasks,
        ),
        agent_id=provider.agent_id,
        rating_count=rating_count,
        average_score=round(average_score, 2) if average_score is not None else None,
        completed_tasks=completed_tasks,
        orders_count=orders_count,
    )


def provider_response(db: Session, provider: Provider) -> ProviderResponse:
    card = provider_card_response(db, provider)
    return ProviderResponse(
        provider_id=provider.provider_id,
        display_name=provider.display_name,
        provider_type=provider.provider_type,
        verification_status=provider.verification_status,
        agent_id=provider.agent_id,
        trust_badge=card.trust_badge,
    )


def service_profile_response(db: Session, service: ServiceProfile) -> ServiceProfileResponse:
    capabilities = db.scalars(select(Capability).where(Capability.service_id == service.service_id)).all()
    return ServiceProfileResponse(
        service_id=service.service_id,
        provider_id=service.provider_id,
        title=service.title,
        description=service.description,
        category=service.category,
        pricing_model=service.pricing_model,
        currency=service.currency,
        base_price_cents=service.base_price_cents,
        status=service.status,
        capabilities=[capability_response(capability) for capability in capabilities],
    )


def service_card_response(service: ServiceProfile) -> ServiceCardResponse:
    return ServiceCardResponse(
        service_id=service.service_id,
        provider_id=service.provider_id,
        title=service.title,
        description=service.description,
        category=service.category,
        pricing_model=service.pricing_model,
        currency=service.currency,
        base_price_cents=service.base_price_cents,
        status=service.status,
    )


def task_response(task: ServiceTask) -> TaskResponse:
    return TaskResponse(
        task_id=task.task_id,
        service_id=task.service_id,
        provider_id=task.provider_id,
        capability_id=task.capability_id,
        status=task.status,
        input=parse_json(task.input_json),
        result=parse_json(task.result_json),
    )


def task_receipt_response(receipt: TaskReceipt) -> TaskReceiptResponse:
    return TaskReceiptResponse(
        receipt_id=receipt.receipt_id,
        task_id=receipt.task_id,
        provider_id=receipt.provider_id,
        provider_user_id=receipt.provider_user_id,
        provider_agent_id=receipt.provider_agent_id,
        receipt_type=receipt.receipt_type,
        status=receipt.status,
        summary=receipt.summary,
        artifact_ids=parse_json_list(receipt.artifact_ids_json),
        usage=parse_json(receipt.usage_json),
        result=parse_json(receipt.result_json),
        created_at=iso(receipt.created_at) or "",
    )


def verification_record_response(record: VerificationRecord) -> VerificationRecordResponse:
    return VerificationRecordResponse(
        verification_id=record.verification_id,
        task_id=record.task_id,
        verifier_user_id=record.verifier_user_id,
        verifier_agent_id=record.verifier_agent_id,
        verification_type=record.verification_type,
        status=record.status,
        rubric=parse_json(record.rubric_json),
        result=parse_json(record.result_json),
        evidence_artifact_ids=parse_json_list(record.evidence_artifact_ids_json),
        comment=record.comment,
        created_at=iso(record.created_at) or "",
    )


def contact_response(contact: Contact) -> ContactResponse:
    return ContactResponse(
        contact_id=contact.contact_id,
        agent_id=contact.agent_id,
        handle=contact.handle_snapshot,
        label=contact.label,
        contact_type=contact.contact_type,
        trust_level=contact.trust_level,
        permissions=parse_json_list(contact.permissions_json),
        status=contact.status,
        muted=contact.muted,
        blocked=contact.blocked,
        created_at=iso(contact.created_at) or "",
    )


def conversation_response(conversation: Conversation) -> ConversationResponse:
    return ConversationResponse(
        conversation_id=conversation.conversation_id,
        target_agent_id=conversation.target_agent_id,
        target_handle=conversation.target_handle_snapshot,
        conversation_type=conversation.conversation_type,
        subject=conversation.subject,
        last_message_at=iso(conversation.last_message_at),
        created_at=iso(conversation.created_at) or "",
    )


def message_response(message: SocialMessage) -> MessageResponse:
    return MessageResponse(
        message_id=message.message_id,
        conversation_id=message.conversation_id,
        from_handle=message.from_handle,
        to_handle=message.to_handle,
        message_type=message.message_type,
        body=message.body,
        metadata=parse_json(message.metadata_json),
        created_at=iso(message.created_at) or "",
    )


def memory_response(memory: ConversationMemory) -> ConversationMemoryResponse:
    return ConversationMemoryResponse(
        memory_id=memory.memory_id,
        conversation_id=memory.conversation_id,
        title=memory.title,
        summary=memory.summary,
        key_facts=json.loads(memory.key_facts_json or "[]"),
        pinned=memory.pinned,
        updated_at=iso(memory.updated_at) or "",
    )


def group_response(group: Group) -> GroupResponse:
    return GroupResponse(
        group_id=group.group_id,
        handle=group.handle,
        title=group.title,
        description=group.description,
        group_type=group.group_type,
        default_permissions=parse_json_list(group.default_permissions_json),
        owner_user_id=group.owner_user_id,
        created_at=iso(group.created_at) or "",
    )


def group_member_response(member: GroupMember) -> GroupMemberResponse:
    return GroupMemberResponse(
        member_id=member.member_id,
        group_id=member.group_id,
        user_id=member.user_id,
        agent_id=member.agent_id,
        handle=member.handle_snapshot,
        role=member.role,
        permissions=parse_json_list(member.permissions_json),
        status=member.status,
        created_at=iso(member.created_at) or "",
    )


def group_message_response(message: GroupMessage) -> GroupMessageResponse:
    return GroupMessageResponse(
        group_message_id=message.group_message_id,
        group_id=message.group_id,
        from_handle=message.from_handle,
        from_user_id=message.from_user_id,
        from_agent_id=message.from_agent_id,
        message_type=message.message_type,
        body=message.body,
        metadata=parse_json(message.metadata_json),
        created_at=iso(message.created_at) or "",
    )


def group_memory_response(memory: GroupMemory) -> GroupMemoryResponse:
    return GroupMemoryResponse(
        group_memory_id=memory.group_memory_id,
        group_id=memory.group_id,
        title=memory.title,
        summary=memory.summary,
        key_facts=parse_json_list(memory.key_facts_json),
        pinned=memory.pinned,
        updated_at=iso(memory.updated_at) or "",
    )


def group_task_context_response(context: GroupTaskContext, task: ServiceTask) -> GroupTaskContextResponse:
    return GroupTaskContextResponse(
        context_id=context.context_id,
        group_id=context.group_id,
        task_id=context.task_id,
        note=context.note,
        created_at=iso(context.created_at) or "",
        task=task_response(task).model_dump(),
    )


def need_response(need: NeedPost) -> NeedPostResponse:
    return NeedPostResponse(
        need_id=need.need_id,
        author_user_id=need.author_user_id,
        title=need.title,
        summary=need.summary,
        description=need.description,
        category=need.category,
        visibility=need.visibility,
        status=need.status,
        budget_cents=need.budget_cents,
        currency=need.currency,
        input=parse_json(need.input_json),
        deliverables=parse_json(need.deliverables_json),
        acceptance_criteria=parse_json(need.acceptance_criteria_json),
        tags=parse_json_list(need.tags_json),
        selected_bid_id=need.selected_bid_id,
        group_id=need.group_id,
        task_id=need.task_id,
        created_at=iso(need.created_at) or "",
        updated_at=iso(need.updated_at) or "",
    )


def need_discussion_response(comment: NeedDiscussion) -> NeedDiscussionResponse:
    return NeedDiscussionResponse(
        comment_id=comment.comment_id,
        need_id=comment.need_id,
        author_user_id=comment.author_user_id,
        author_agent_id=comment.author_agent_id,
        body=comment.body,
        metadata=parse_json(comment.metadata_json),
        created_at=iso(comment.created_at) or "",
    )


def need_bid_response(db: Session, bid: NeedBid) -> NeedBidResponse:
    provider = db.get(Provider, bid.provider_id) if bid.provider_id else None
    service = db.get(ServiceProfile, bid.service_id) if bid.service_id else None
    agent = db.get(AgentAccount, bid.agent_id) if bid.agent_id else None
    return NeedBidResponse(
        bid_id=bid.bid_id,
        need_id=bid.need_id,
        bidder_user_id=bid.bidder_user_id,
        provider_id=bid.provider_id,
        service_id=bid.service_id,
        agent_id=bid.agent_id,
        status=bid.status,
        proposal=bid.proposal,
        amount_cents=bid.amount_cents,
        currency=bid.currency,
        estimated_delivery=bid.estimated_delivery,
        terms=parse_json(bid.terms_json),
        provider=provider_card_response(db, provider) if provider else None,
        service=service_card_response(service) if service else None,
        agent=agent_summary_response(agent) if agent else None,
        created_at=iso(bid.created_at) or "",
        updated_at=iso(bid.updated_at) or "",
    )


def community_report_response(report: CommunityReport) -> CommunityReportResponse:
    return CommunityReportResponse(
        report_id=report.report_id,
        reporter_user_id=report.reporter_user_id,
        target_type=report.target_type,
        target_id=report.target_id,
        reason=report.reason,
        details=report.details,
        metadata=parse_json(report.metadata_json),
        status=report.status,
        created_at=iso(report.created_at) or "",
        updated_at=iso(report.updated_at) or "",
    )


def payment_response(payment: PaymentRecord) -> PaymentResponse:
    return PaymentResponse(
        payment_id=payment.payment_id,
        order_id=payment.order_id,
        amount_cents=payment.amount_cents,
        currency=payment.currency,
        status=payment.status,
        provider_reference=payment.provider_reference,
        created_at=iso(payment.created_at) or "",
    )


def order_response(db: Session, order: ServiceOrder) -> OrderResponse:
    payment = db.scalar(select(PaymentRecord).where(PaymentRecord.order_id == order.order_id).order_by(PaymentRecord.created_at.desc()))
    return OrderResponse(
        order_id=order.order_id,
        task_id=order.task_id,
        quote_id=order.quote_id,
        buyer_user_id=order.buyer_user_id,
        provider_id=order.provider_id,
        status=order.status,
        created_at=iso(order.created_at) or "",
        payment=payment_response(payment) if payment else None,
    )


def session_response(session: DeviceSession) -> SessionResponse:
    return SessionResponse(
        session_id=session.session_id,
        device_name=session.device_name,
        runtime_type=session.runtime_type,
        scopes=session.scopes.split(),
        expires_at=iso(session.expires_at) or "",
        revoked_at=iso(session.revoked_at),
        created_at=iso(session.created_at) or "",
    )


def queued_event_response(event: QueuedEvent) -> EventResponse:
    return EventResponse(
        cursor_id=event.id,
        event_id=event.event_id,
        event_type=event.event_type,
        account_id=event.account_id,
        payload=json.loads(event.payload_json),
    )


def audit_log_response(row: AuditLog) -> AuditLogResponse:
    return AuditLogResponse(
        audit_id=row.audit_id,
        actor_user_id=row.actor_user_id,
        action=row.action,
        target_type=row.target_type,
        target_id=row.target_id,
        payload=parse_json(row.payload_json),
        created_at=iso(row.created_at) or "",
    )


def audit(db: Session, user: HumanAccount, action: str, target_type: str, target_id: str | None, payload: dict) -> None:
    db.add(
        AuditLog(
            actor_user_id=user.user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            payload_json=dump_json(payload),
        )
    )


def readable_conversation(db: Session, conversation_id: str, user: HumanAccount) -> Conversation:
    conversation = db.scalar(
        select(Conversation)
        .where(Conversation.conversation_id == conversation_id)
        .where((Conversation.initiator_user_id == user.user_id) | (Conversation.target_user_id == user.user_id))
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="conversation not found")
    return conversation


def find_contact(db: Session, user: HumanAccount, contact_id_or_handle: str) -> Contact:
    contact = db.scalar(
        select(Contact)
        .where(Contact.owner_user_id == user.user_id)
        .where((Contact.contact_id == contact_id_or_handle) | (Contact.handle_snapshot == contact_id_or_handle))
    )
    if not contact:
        raise HTTPException(status_code=404, detail="contact not found")
    return contact


def active_contact_for_agent(db: Session, user: HumanAccount, agent: AgentAccount) -> Contact | None:
    return db.scalar(
        select(Contact)
        .where(Contact.owner_user_id == user.user_id)
        .where(Contact.agent_id == agent.agent_id)
        .where(Contact.status == "active")
    )


def require_contact_permission(
    db: Session,
    user: HumanAccount,
    agent: AgentAccount,
    permission: str,
    *,
    allow_self: bool = True,
) -> Contact | None:
    if allow_self and agent.owner_user_id == user.user_id:
        return None
    contact = active_contact_for_agent(db, user, agent)
    if not contact:
        raise HTTPException(status_code=403, detail=f"contact permission required: {permission}")
    permissions = set(parse_json_list(contact.permissions_json))
    trust_level = normalize_trust_level(contact.trust_level)
    if contact.blocked or trust_level == "blocked":
        raise HTTPException(status_code=403, detail="contact is blocked")
    if permission not in permissions:
        raise HTTPException(status_code=403, detail=f"contact does not allow {permission}")
    return contact


def get_or_create_conversation(
    db: Session,
    user: HumanAccount,
    target_agent: AgentAccount,
    conversation_id: str | None = None,
    subject: str | None = None,
) -> Conversation:
    if conversation_id:
        conversation = readable_conversation(db, conversation_id, user)
        if conversation.target_agent_id != target_agent.agent_id:
            raise HTTPException(status_code=400, detail="conversation target does not match message target")
        return conversation
    conversation = db.scalar(
        select(Conversation)
        .where(Conversation.initiator_user_id == user.user_id)
        .where(Conversation.target_agent_id == target_agent.agent_id)
        .where(Conversation.conversation_type == "dm")
        .order_by(Conversation.created_at.desc())
    )
    if conversation:
        return conversation
    conversation = Conversation(
        initiator_user_id=user.user_id,
        target_user_id=target_agent.owner_user_id,
        target_agent_id=target_agent.agent_id,
        target_handle_snapshot=target_agent.handle,
        conversation_type="dm",
        subject=subject,
    )
    db.add(conversation)
    db.flush()
    return conversation


def find_group(db: Session, group_id_or_handle: str) -> Group:
    group = db.scalar(
        select(Group).where((Group.group_id == group_id_or_handle) | (Group.handle == group_id_or_handle))
    )
    if not group:
        raise HTTPException(status_code=404, detail="group not found")
    return group


def active_group_member(db: Session, group: Group, user: HumanAccount) -> GroupMember | None:
    return db.scalar(
        select(GroupMember)
        .where(GroupMember.group_id == group.group_id)
        .where(GroupMember.user_id == user.user_id)
        .where(GroupMember.status == "active")
        .order_by(GroupMember.role.asc(), GroupMember.created_at.asc())
    )


def require_group_permission(
    db: Session,
    user: HumanAccount,
    group_id_or_handle: str,
    permission: str,
) -> tuple[Group, GroupMember]:
    group = find_group(db, group_id_or_handle)
    member = active_group_member(db, group, user)
    if not member:
        raise HTTPException(status_code=404, detail="group not found")
    if group.owner_user_id == user.user_id or member.role in {"owner", "admin"}:
        return group, member
    if permission not in set(parse_json_list(member.permissions_json)):
        raise HTTPException(status_code=403, detail=f"group permission required: {permission}")
    return group, member


def visible_need(db: Session, need_id: str, user: HumanAccount) -> NeedPost:
    need = db.get(NeedPost, need_id)
    if not need:
        raise HTTPException(status_code=404, detail="need not found")
    if need.status == "hidden" and need.author_user_id != user.user_id:
        raise HTTPException(status_code=404, detail="need not found")
    if need.visibility == "public" or need.author_user_id == user.user_id:
        return need
    bid = db.scalar(
        select(NeedBid)
        .where(NeedBid.need_id == need.need_id)
        .where(NeedBid.bidder_user_id == user.user_id)
        .limit(1)
    )
    if not bid:
        raise HTTPException(status_code=404, detail="need not found")
    return need


def author_owned_need(db: Session, need_id: str, user: HumanAccount) -> NeedPost:
    need = db.get(NeedPost, need_id)
    if not need or need.author_user_id != user.user_id:
        raise HTTPException(status_code=404, detail="need not found")
    return need


def ensure_need_discussion_open_for_updates(need: NeedPost) -> None:
    if need.status not in {"open", "assigned"}:
        raise HTTPException(status_code=400, detail=f"need does not allow discussion updates: {need.status}")


def validate_community_report_target(
    db: Session,
    user: HumanAccount,
    *,
    need_id: str,
    target_type: str,
    target_id: str,
) -> tuple[NeedPost, str]:
    if target_type not in KNOWN_COMMUNITY_REPORT_TARGETS:
        raise HTTPException(status_code=400, detail=f"unsupported report target: {target_type}")
    need = visible_need(db, need_id, user)
    if target_type == "need":
        if target_id != need.need_id:
            raise HTTPException(status_code=404, detail="need not found")
        return need, need.need_id
    if target_type == "need_comment":
        comment = db.get(NeedDiscussion, target_id)
        if not comment or comment.need_id != need.need_id:
            raise HTTPException(status_code=404, detail="discussion comment not found for this need")
        return need, comment.comment_id
    bid = db.get(NeedBid, target_id)
    if not bid or bid.need_id != need.need_id:
        raise HTTPException(status_code=404, detail="bid not found for this need")
    return need, bid.bid_id


def validate_need_bid_party(
    db: Session,
    user: HumanAccount,
    payload: NeedBidCreateRequest,
) -> tuple[str | None, str | None, str | None]:
    provider_id = payload.provider_id
    service_id = payload.service_id
    agent_id = validate_agent_owner(db, user, payload.agent_id)
    provider: Provider | None = None
    if service_id:
        service = db.get(ServiceProfile, service_id)
        if not service or service.status != "active":
            raise HTTPException(status_code=404, detail="service profile not found")
        provider = db.get(Provider, service.provider_id)
        if not provider or provider.owner_user_id != user.user_id:
            raise HTTPException(status_code=404, detail="service profile not found for this account")
        if provider_id and provider_id != provider.provider_id:
            raise HTTPException(status_code=400, detail="service does not belong to provider")
        provider_id = provider.provider_id
        if agent_id and provider.agent_id and agent_id != provider.agent_id:
            raise HTTPException(status_code=400, detail="bid agent does not match service provider agent")
        agent_id = agent_id or provider.agent_id
    elif provider_id:
        provider = db.get(Provider, provider_id)
        if not provider or provider.owner_user_id != user.user_id:
            raise HTTPException(status_code=404, detail="provider not found for this account")
        if agent_id and provider.agent_id and agent_id != provider.agent_id:
            raise HTTPException(status_code=400, detail="bid agent does not match provider agent")
        agent_id = agent_id or provider.agent_id
    if not provider_id and not service_id and not agent_id:
        raise HTTPException(status_code=400, detail="bid requires provider_id, service_id, or agent_id")
    return provider_id, service_id, agent_id


def generated_need_group_handle(db: Session, need: NeedPost) -> str:
    seed = "".join(ch if ch.isalnum() else "-" for ch in need.title.lower()).strip("-") or "need"
    seed = seed[:40].strip("-") or "need"
    suffix = need.need_id.removeprefix("need_")[:8]
    base = f"need-{suffix}-{seed}"[:90].strip("-")
    candidate = base
    counter = 2
    while db.scalar(select(Group).where(Group.handle == candidate)):
        candidate = f"{base}-{counter}"[:120]
        counter += 1
    return candidate


def ensure_need_group(
    db: Session,
    user: HumanAccount,
    need: NeedPost,
    payload: NeedAcceptBidRequest,
) -> Group:
    if need.group_id:
        group = db.get(Group, need.group_id)
        if group:
            return group
    handle = payload.group_handle or generated_need_group_handle(db, need)
    if db.scalar(select(Group).where(Group.handle == handle)):
        raise HTTPException(status_code=409, detail="group handle already exists")
    permissions = normalize_group_permissions(DEFAULT_GROUP_PERMISSIONS, default_full=True)
    group = Group(
        owner_user_id=user.user_id,
        handle=handle,
        title=payload.group_title or f"Need: {need.title}",
        description=need.summary or need.description[:8000],
        group_type="community_need",
        default_permissions_json=json.dumps(normalize_group_permissions([]), sort_keys=True),
    )
    db.add(group)
    db.flush()
    db.add(
        GroupMember(
            group_id=group.group_id,
            user_id=user.user_id,
            handle_snapshot=user.username,
            role="owner",
            permissions_json=json.dumps(permissions, sort_keys=True),
        )
    )
    need.group_id = group.group_id
    return group


def visible_task(db: Session, task_id: str, user: HumanAccount) -> ServiceTask:
    task = db.get(ServiceTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    provider = db.get(Provider, task.provider_id)
    if task.requester_user_id != user.user_id and (not provider or provider.owner_user_id != user.user_id):
        raise HTTPException(status_code=403, detail="only requester or provider owner can read this task")
    return task


def provider_owned_task(db: Session, task_id: str, user: HumanAccount) -> tuple[ServiceTask, Provider]:
    task = db.get(ServiceTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    provider = db.get(Provider, task.provider_id)
    if not provider or provider.owner_user_id != user.user_id:
        raise HTTPException(status_code=403, detail="only provider owner can update this task")
    return task, provider


def requester_owned_task(db: Session, task_id: str, user: HumanAccount) -> tuple[ServiceTask, Provider | None]:
    task = db.get(ServiceTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    if task.requester_user_id != user.user_id:
        raise HTTPException(status_code=403, detail="only requester can verify this task")
    provider = db.get(Provider, task.provider_id)
    return task, provider


def validate_agent_owner(db: Session, user: HumanAccount, agent_id: str | None) -> str | None:
    if not agent_id:
        return None
    agent = db.get(AgentAccount, agent_id)
    if not agent or agent.owner_user_id != user.user_id:
        raise HTTPException(status_code=404, detail="agent not found for this account")
    return agent.agent_id


def validate_task_artifacts(db: Session, task: ServiceTask, artifact_ids: list[str]) -> list[str]:
    normalized: list[str] = []
    for artifact_id in artifact_ids:
        clean = artifact_id.strip()
        if not clean:
            continue
        if clean in normalized:
            continue
        artifact = db.get(Artifact, clean)
        if not artifact or artifact.task_id != task.task_id:
            raise HTTPException(status_code=404, detail=f"artifact not found for this task: {artifact_id}")
        normalized.append(clean)
    return normalized


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db()
        try:
            yield
        finally:
            await app.state.event_bus.close()

    app = FastAPI(title="Ainet Enterprise Backend", version="0.1.0", lifespan=lifespan)
    app.state.event_bus = EventBus(settings)

    @app.get("/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/console", response_class=HTMLResponse, include_in_schema=False)
    def community_console() -> HTMLResponse:
        return HTMLResponse(community_console_html())

    def issue_device_session(
        db: Session,
        settings: Settings,
        user: HumanAccount,
        device_name: str,
        runtime_type: str,
        scopes: list[str],
    ) -> tuple[TokenResponse, DeviceSession]:
        session = DeviceSession(
            user_id=user.user_id,
            device_name=device_name,
            runtime_type=runtime_type,
            access_token_hash="pending",
            scopes=" ".join(scopes),
            expires_at=utc_now() + timedelta(minutes=settings.access_token_minutes),
        )
        db.add(session)
        db.flush()
        token, expires_at = create_access_token(settings, user.user_id, session.session_id, scopes)
        session.access_token_hash = hash_secret(token)
        session.expires_at = expires_at
        response = TokenResponse(
            access_token=token,
            expires_at=expires_at.isoformat(),
            user_id=user.user_id,
            scopes=scopes,
        )
        return response, session

    @app.post("/auth/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED)
    async def signup(payload: SignupRequest, db: Session = Depends(get_db)) -> SignupResponse:
        email = payload.email.lower()
        username = payload.username.lower()
        exists = db.scalar(select(HumanAccount).where((HumanAccount.email == email) | (HumanAccount.username == username)))
        if exists:
            raise HTTPException(status_code=409, detail="email or username already registered")

        user = HumanAccount(email=email, username=username, password_hash=hash_password(payload.password))
        db.add(user)
        db.flush()

        code = random_code()
        code_record = EmailVerificationCode(
            user_id=user.user_id,
            email=email,
            code_hash=hash_secret(code),
            purpose="signup",
            expires_at=utc_now() + timedelta(minutes=settings.email_code_minutes),
        )
        db.add(code_record)
        db.commit()
        db.refresh(user)
        await send_verification_code(settings, email, code)
        await app.state.event_bus.publish(db, "auth.signup", {"user_id": user.user_id, "email": email}, user.user_id)
        return SignupResponse(user_id=user.user_id, email=email)

    @app.post("/auth/verify-email")
    async def verify_email(payload: VerifyEmailRequest, db: Session = Depends(get_db)) -> dict[str, bool]:
        email = payload.email.lower()
        user = db.scalar(select(HumanAccount).where(HumanAccount.email == email))
        if not user:
            raise HTTPException(status_code=404, detail="account not found")
        code = db.scalar(
            select(EmailVerificationCode)
            .where(EmailVerificationCode.user_id == user.user_id)
            .where(EmailVerificationCode.email == email)
            .where(EmailVerificationCode.consumed_at.is_(None))
            .order_by(EmailVerificationCode.created_at.desc())
        )
        if not code or as_utc(code.expires_at) < utc_now() or not secrets_equal(payload.code, code.code_hash):
            raise HTTPException(status_code=400, detail="invalid or expired verification code")
        code.consumed_at = utc_now()
        user.email_verified_at = utc_now()
        db.commit()
        await app.state.event_bus.publish(db, "auth.email_verified", {"user_id": user.user_id}, user.user_id)
        return {"ok": True}

    @app.post("/auth/login", response_model=TokenResponse)
    async def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
        settings = get_settings()
        email = payload.email.lower()
        user = db.scalar(select(HumanAccount).where(HumanAccount.email == email))
        if not user or user.disabled or not verify_password(payload.password, user.password_hash):
            raise HTTPException(status_code=401, detail="invalid credentials")
        if not user.email_verified_at:
            raise HTTPException(status_code=403, detail="email verification required")

        scopes = DEFAULT_SESSION_SCOPES
        response, session = issue_device_session(db, settings, user, payload.device_name, payload.runtime_type, scopes)
        db.commit()
        await app.state.event_bus.publish(db, "auth.login", {"user_id": user.user_id, "session_id": session.session_id}, user.user_id)
        return response

    def current_user(
        db: Session = Depends(get_db),
        authorization: str | None = Header(default=None),
        settings: Settings = Depends(get_settings),
    ) -> HumanAccount:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="missing bearer token")
        token = authorization.removeprefix("Bearer ").strip()
        try:
            claims = decode_access_token(settings, token)
        except jwt.PyJWTError as exc:
            raise HTTPException(status_code=401, detail="invalid token") from exc
        session = db.get(DeviceSession, claims.get("sid"))
        if not session or session.revoked_at or as_utc(session.expires_at) < utc_now() or not secrets_equal(token, session.access_token_hash):
            raise HTTPException(status_code=401, detail="session expired or revoked")
        if claims.get("sub") != session.user_id:
            raise HTTPException(status_code=401, detail="token subject does not match session")
        user = db.get(HumanAccount, claims.get("sub"))
        if not user or user.disabled:
            raise HTTPException(status_code=401, detail="account disabled or missing")
        user._ainet_session_scopes = effective_session_scopes(session.scopes)
        return user

    def scoped_user(scope: str):
        def dependency(user: HumanAccount = Depends(current_user)) -> HumanAccount:
            scopes = set(getattr(user, "_ainet_session_scopes", set()))
            if scope not in scopes:
                raise HTTPException(status_code=403, detail=f"token scope required: {scope}")
            return user

        return dependency

    @app.post("/auth/invites", response_model=InviteResponse, status_code=status.HTTP_201_CREATED)
    async def create_invite(
        payload: InviteCreateRequest,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("sessions:write")),
    ) -> InviteResponse:
        if payload.invite_type != "device":
            raise HTTPException(status_code=400, detail="unsupported invite type")
        token = secrets.token_urlsafe(32)
        scopes = payload.scopes or DEFAULT_SESSION_SCOPES
        unknown_scopes = sorted(set(scopes) - KNOWN_SESSION_SCOPES)
        if unknown_scopes:
            raise HTTPException(status_code=400, detail=f"unsupported invite scopes: {', '.join(unknown_scopes)}")
        invite = Invite(
            invite_type=payload.invite_type,
            created_by_user_id=user.user_id,
            token_hash=hash_secret(token),
            scopes=" ".join(scopes),
            max_uses=payload.max_uses,
            expires_at=utc_now() + timedelta(minutes=payload.expires_minutes),
        )
        db.add(invite)
        db.flush()
        audit(db, user, "invite.create", "invite", invite.invite_id, {"invite_type": invite.invite_type})
        db.commit()
        db.refresh(invite)
        await app.state.event_bus.publish(
            db,
            "invite.created",
            {"invite_id": invite.invite_id, "invite_type": invite.invite_type, "expires_at": iso(invite.expires_at)},
            user.user_id,
        )
        return InviteResponse(
            invite_id=invite.invite_id,
            invite_type=invite.invite_type,
            token=token,
            scopes=invite.scopes.split(),
            expires_at=iso(invite.expires_at) or "",
            max_uses=invite.max_uses,
        )

    @app.post("/auth/invites/accept", response_model=TokenResponse)
    async def accept_invite(
        payload: InviteAcceptRequest,
        db: Session = Depends(get_db),
        settings: Settings = Depends(get_settings),
    ) -> TokenResponse:
        invite = db.scalar(select(Invite).where(Invite.token_hash == hash_secret(payload.token)))
        if (
            not invite
            or invite.invite_type != "device"
            or as_utc(invite.expires_at) < utc_now()
            or invite.use_count >= invite.max_uses
        ):
            raise HTTPException(status_code=400, detail="invalid or expired invite")
        user = db.get(HumanAccount, invite.created_by_user_id)
        if not user or user.disabled:
            raise HTTPException(status_code=400, detail="invite owner is unavailable")
        scopes = invite.scopes.split()
        response, session = issue_device_session(db, settings, user, payload.device_name, payload.runtime_type, scopes)
        invite.use_count += 1
        db.add(
            AuditLog(
                actor_user_id=user.user_id,
                action="invite.accept",
                target_type="invite",
                target_id=invite.invite_id,
                payload_json=dump_json({"session_id": session.session_id, "device_name": payload.device_name}),
            )
        )
        db.commit()
        await app.state.event_bus.publish(
            db,
            "invite.accepted",
            {"invite_id": invite.invite_id, "session_id": session.session_id, "device_name": payload.device_name},
            user.user_id,
        )
        return response

    @app.get("/account/me", response_model=MeResponse)
    def me(user: HumanAccount = Depends(scoped_user("profile:read"))) -> MeResponse:
        return MeResponse(
            user_id=user.user_id,
            email=user.email,
            username=user.username,
            email_verified=bool(user.email_verified_at),
        )

    @app.get("/identity", response_model=IdentityResponse)
    def identity(
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("profile:read")),
    ) -> IdentityResponse:
        agents = db.scalars(
            select(AgentAccount).where(AgentAccount.owner_user_id == user.user_id).order_by(AgentAccount.created_at.asc())
        ).all()
        sessions = db.scalars(
            select(DeviceSession)
            .where(DeviceSession.user_id == user.user_id)
            .where(DeviceSession.revoked_at.is_(None))
        ).all()
        return IdentityResponse(
            user=MeResponse(
                user_id=user.user_id,
                email=user.email,
                username=user.username,
                email_verified=bool(user.email_verified_at),
            ),
            agents=[agent_response(agent) for agent in agents],
            session_count=len(sessions),
        )

    @app.get("/account/sessions", response_model=list[SessionResponse])
    def list_sessions(
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("sessions:read")),
        include_revoked: bool = False,
    ) -> list[SessionResponse]:
        stmt = select(DeviceSession).where(DeviceSession.user_id == user.user_id)
        if not include_revoked:
            stmt = stmt.where(DeviceSession.revoked_at.is_(None))
        sessions = db.scalars(stmt.order_by(DeviceSession.created_at.desc()).limit(100)).all()
        return [session_response(session) for session in sessions]

    @app.post("/account/sessions/{session_id}/revoke")
    async def revoke_session(
        session_id: str,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("sessions:write")),
    ) -> dict[str, bool]:
        session = db.get(DeviceSession, session_id)
        if not session or session.user_id != user.user_id:
            raise HTTPException(status_code=404, detail="session not found")
        if not session.revoked_at:
            session.revoked_at = utc_now()
            audit(db, user, "session.revoke", "session", session.session_id, {"device_name": session.device_name})
            db.commit()
            await app.state.event_bus.publish(db, "session.revoked", {"session_id": session.session_id}, user.user_id)
        return {"ok": True}

    @app.post("/agents", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
    async def create_agent(
        payload: AgentCreateRequest,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("profile:write")),
    ) -> AgentResponse:
        existing = db.scalar(select(AgentAccount).where(AgentAccount.handle == payload.handle))
        if existing:
            raise HTTPException(status_code=409, detail="handle already exists")
        agent = AgentAccount(
            owner_user_id=user.user_id,
            handle=payload.handle,
            display_name=payload.display_name,
            runtime_type=payload.runtime_type,
            public_key=payload.public_key,
            key_id=payload.key_id,
            key_rotated_at=utc_now() if payload.public_key or payload.key_id else None,
        )
        db.add(agent)
        db.commit()
        db.refresh(agent)
        await app.state.event_bus.publish(db, "agent.created", {"agent_id": agent.agent_id, "handle": agent.handle}, user.user_id)
        return agent_response(agent)

    @app.get("/agents", response_model=list[AgentResponse])
    def list_agents(
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("profile:read")),
    ) -> list[AgentResponse]:
        agents = db.scalars(
            select(AgentAccount).where(AgentAccount.owner_user_id == user.user_id).order_by(AgentAccount.created_at.asc())
        ).all()
        return [agent_response(agent) for agent in agents]

    @app.patch("/agents/{agent_id}/identity", response_model=AgentResponse)
    async def update_agent_identity(
        agent_id: str,
        payload: AgentIdentityUpdateRequest,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("profile:write")),
    ) -> AgentResponse:
        agent = db.get(AgentAccount, agent_id)
        if not agent or agent.owner_user_id != user.user_id:
            raise HTTPException(status_code=404, detail="agent not found for this account")
        if payload.public_key is not None:
            agent.public_key = payload.public_key
            agent.key_rotated_at = utc_now()
        if payload.key_id is not None:
            agent.key_id = payload.key_id
            if agent.key_rotated_at is None:
                agent.key_rotated_at = utc_now()
        audit(db, user, "agent_identity.update", "agent", agent.agent_id, {"key_id": agent.key_id})
        db.commit()
        db.refresh(agent)
        await app.state.event_bus.publish(
            db,
            "agent_identity.updated",
            {"agent_id": agent.agent_id, "handle": agent.handle, "key_id": agent.key_id},
            user.user_id,
        )
        return agent_response(agent)

    @app.post("/contacts", response_model=ContactResponse, status_code=status.HTTP_201_CREATED)
    async def create_contact(
        payload: ContactCreateRequest,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("contacts:write")),
    ) -> ContactResponse:
        agent = db.scalar(select(AgentAccount).where(AgentAccount.handle == payload.handle))
        if not agent:
            raise HTTPException(status_code=404, detail="target handle not found")
        contact = db.scalar(
            select(Contact).where(Contact.owner_user_id == user.user_id).where(Contact.agent_id == agent.agent_id)
        )
        if contact:
            contact.label = payload.label or contact.label
            contact.contact_type = payload.contact_type
            contact.trust_level = normalize_trust_level(payload.trust_level)
            contact.permissions_json = json.dumps(normalize_contact_permissions(payload.permissions), sort_keys=True)
            contact.blocked = False
            contact.status = "active"
        else:
            contact = Contact(
                owner_user_id=user.user_id,
                agent_id=agent.agent_id,
                handle_snapshot=agent.handle,
                label=payload.label,
                contact_type=payload.contact_type,
                trust_level=normalize_trust_level(payload.trust_level),
                permissions_json=json.dumps(normalize_contact_permissions(payload.permissions), sort_keys=True),
            )
            db.add(contact)
        db.flush()
        audit(
            db,
            user,
            "contact.create",
            "contact",
            contact.contact_id,
            {"handle": agent.handle, "permissions": parse_json_list(contact.permissions_json), "trust_level": contact.trust_level},
        )
        db.commit()
        db.refresh(contact)
        await app.state.event_bus.publish(
            db,
            "contact.created",
            {
                "contact_id": contact.contact_id,
                "handle": contact.handle_snapshot,
                "permissions": parse_json_list(contact.permissions_json),
                "trust_level": contact.trust_level,
            },
            user.user_id,
        )
        return contact_response(contact)

    @app.get("/contacts", response_model=list[ContactResponse])
    def list_contacts(
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("contacts:read")),
        limit: int = 100,
    ) -> list[ContactResponse]:
        contacts = db.scalars(
            select(Contact)
            .where(Contact.owner_user_id == user.user_id)
            .where(Contact.status == "active")
            .order_by(Contact.created_at.desc())
            .limit(min(limit, 200))
        ).all()
        return [contact_response(contact) for contact in contacts]

    @app.get("/contacts/{contact_id_or_handle}", response_model=ContactResponse)
    def get_contact(
        contact_id_or_handle: str,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("contacts:read")),
    ) -> ContactResponse:
        return contact_response(find_contact(db, user, contact_id_or_handle))

    @app.patch("/contacts/{contact_id_or_handle}", response_model=ContactResponse)
    async def update_contact(
        contact_id_or_handle: str,
        payload: ContactUpdateRequest,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("contacts:write")),
    ) -> ContactResponse:
        contact = find_contact(db, user, contact_id_or_handle)
        if payload.label is not None:
            contact.label = payload.label
        if payload.trust_level is not None:
            contact.trust_level = normalize_trust_level(payload.trust_level)
        if payload.permissions is not None:
            contact.permissions_json = json.dumps(normalize_contact_permissions(payload.permissions), sort_keys=True)
        if payload.muted is not None:
            contact.muted = payload.muted
        if payload.blocked is not None:
            contact.blocked = payload.blocked
            if payload.blocked:
                contact.trust_level = "blocked"
        db.flush()
        audit(
            db,
            user,
            "contact.update",
            "contact",
            contact.contact_id,
            {
                "handle": contact.handle_snapshot,
                "permissions": parse_json_list(contact.permissions_json),
                "trust_level": contact.trust_level,
                "muted": contact.muted,
                "blocked": contact.blocked,
            },
        )
        db.commit()
        db.refresh(contact)
        await app.state.event_bus.publish(
            db,
            "contact.updated",
            {
                "contact_id": contact.contact_id,
                "handle": contact.handle_snapshot,
                "permissions": parse_json_list(contact.permissions_json),
                "trust_level": contact.trust_level,
                "muted": contact.muted,
                "blocked": contact.blocked,
            },
            user.user_id,
        )
        return contact_response(contact)

    @app.post("/conversations", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
    def create_conversation(
        payload: ConversationCreateRequest,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("messages:send")),
    ) -> ConversationResponse:
        target_agent = db.scalar(select(AgentAccount).where(AgentAccount.handle == payload.target_handle))
        if not target_agent:
            raise HTTPException(status_code=404, detail="target handle not found")
        require_contact_permission(db, user, target_agent, "dm")
        conversation = get_or_create_conversation(db, user, target_agent, subject=payload.subject)
        db.commit()
        db.refresh(conversation)
        return conversation_response(conversation)

    @app.get("/conversations", response_model=list[ConversationResponse])
    def list_conversations(
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("messages:read")),
        limit: int = 100,
    ) -> list[ConversationResponse]:
        conversations = db.scalars(
            select(Conversation)
            .where((Conversation.initiator_user_id == user.user_id) | (Conversation.target_user_id == user.user_id))
            .order_by(Conversation.last_message_at.desc().nullslast(), Conversation.created_at.desc())
            .limit(min(limit, 200))
        ).all()
        return [conversation_response(conversation) for conversation in conversations]

    @app.get("/conversations/{conversation_id}/messages", response_model=list[MessageResponse])
    def list_messages(
        conversation_id: str,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("messages:read")),
        limit: int = 100,
    ) -> list[MessageResponse]:
        conversation = readable_conversation(db, conversation_id, user)
        messages = db.scalars(
            select(SocialMessage)
            .where(SocialMessage.conversation_id == conversation.conversation_id)
            .order_by(SocialMessage.created_at.asc())
            .limit(min(limit, 500))
        ).all()
        return [message_response(message) for message in messages]

    @app.get("/messages/search", response_model=list[MessageResponse])
    def search_messages(
        query: str,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("messages:read")),
        conversation_id: str | None = None,
        limit: int = 50,
    ) -> list[MessageResponse]:
        if len(query.strip()) < 2:
            raise HTTPException(status_code=400, detail="query must be at least 2 characters")
        if conversation_id:
            readable_conversation(db, conversation_id, user)
        pattern = contains_pattern(query)
        stmt = (
            select(SocialMessage)
            .join(Conversation, Conversation.conversation_id == SocialMessage.conversation_id)
            .where((Conversation.initiator_user_id == user.user_id) | (Conversation.target_user_id == user.user_id))
            .where(
                SocialMessage.body.ilike(pattern, escape="\\")
                | SocialMessage.from_handle.ilike(pattern, escape="\\")
                | SocialMessage.to_handle.ilike(pattern, escape="\\")
            )
            .order_by(SocialMessage.created_at.desc())
            .limit(min(limit, 200))
        )
        if conversation_id:
            stmt = stmt.where(SocialMessage.conversation_id == conversation_id)
        messages = db.scalars(stmt).all()
        return [message_response(message) for message in messages]

    @app.get("/conversations/{conversation_id}/memory", response_model=ConversationMemoryResponse | None)
    def get_conversation_memory(
        conversation_id: str,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("messages:read")),
    ) -> ConversationMemoryResponse | None:
        readable_conversation(db, conversation_id, user)
        memory = db.scalar(
            select(ConversationMemory)
            .where(ConversationMemory.conversation_id == conversation_id)
            .where(ConversationMemory.owner_user_id == user.user_id)
        )
        return memory_response(memory) if memory else None

    @app.put("/conversations/{conversation_id}/memory", response_model=ConversationMemoryResponse)
    async def upsert_conversation_memory(
        conversation_id: str,
        payload: ConversationMemoryRequest,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("messages:send")),
    ) -> ConversationMemoryResponse:
        readable_conversation(db, conversation_id, user)
        memory = db.scalar(
            select(ConversationMemory)
            .where(ConversationMemory.conversation_id == conversation_id)
            .where(ConversationMemory.owner_user_id == user.user_id)
        )
        if not memory:
            memory = ConversationMemory(conversation_id=conversation_id, owner_user_id=user.user_id)
            db.add(memory)
        memory.title = payload.title
        memory.summary = payload.summary
        memory.key_facts_json = json.dumps(payload.key_facts, sort_keys=True)
        memory.pinned = payload.pinned
        memory.updated_at = utc_now()
        audit(db, user, "conversation_memory.upsert", "conversation", conversation_id, {"pinned": memory.pinned})
        db.commit()
        db.refresh(memory)
        await app.state.event_bus.publish(
            db,
            "conversation_memory.updated",
            {"conversation_id": conversation_id, "memory_id": memory.memory_id},
            user.user_id,
        )
        return memory_response(memory)

    @app.post("/conversations/{conversation_id}/memory/refresh", response_model=ConversationMemoryResponse)
    async def refresh_conversation_memory(
        conversation_id: str,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("messages:send")),
        limit: int = 50,
    ) -> ConversationMemoryResponse:
        conversation = readable_conversation(db, conversation_id, user)
        messages = db.scalars(
            select(SocialMessage)
            .where(SocialMessage.conversation_id == conversation.conversation_id)
            .order_by(SocialMessage.created_at.desc())
            .limit(min(limit, 200))
        ).all()
        chronological = list(reversed(messages))
        lines = [f"{message.from_handle}: {message.body}" for message in chronological if message.body.strip()]
        summary = "\n".join(lines)[-12000:]
        handles = sorted({message.from_handle for message in chronological} | {message.to_handle for message in chronological})
        key_facts = [
            f"messages_considered={len(chronological)}",
            f"participants={', '.join(handles)}",
        ]
        memory = db.scalar(
            select(ConversationMemory)
            .where(ConversationMemory.conversation_id == conversation_id)
            .where(ConversationMemory.owner_user_id == user.user_id)
        )
        if not memory:
            memory = ConversationMemory(conversation_id=conversation_id, owner_user_id=user.user_id)
            db.add(memory)
        memory.title = conversation.subject or f"Conversation with {conversation.target_handle_snapshot}"
        memory.summary = summary
        memory.key_facts_json = json.dumps(key_facts, sort_keys=True)
        memory.updated_at = utc_now()
        audit(db, user, "conversation_memory.refresh", "conversation", conversation_id, {"message_count": len(chronological)})
        db.commit()
        db.refresh(memory)
        await app.state.event_bus.publish(
            db,
            "conversation_memory.refreshed",
            {"conversation_id": conversation_id, "memory_id": memory.memory_id, "message_count": len(chronological)},
            user.user_id,
        )
        return memory_response(memory)

    @app.get("/memory/search", response_model=list[ConversationMemoryResponse])
    def search_memory(
        query: str,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("messages:read")),
        limit: int = 50,
    ) -> list[ConversationMemoryResponse]:
        if len(query.strip()) < 2:
            raise HTTPException(status_code=400, detail="query must be at least 2 characters")
        pattern = contains_pattern(query)
        rows = db.scalars(
            select(ConversationMemory)
            .where(ConversationMemory.owner_user_id == user.user_id)
            .where(
                ConversationMemory.summary.ilike(pattern, escape="\\")
                | ConversationMemory.title.ilike(pattern, escape="\\")
                | ConversationMemory.key_facts_json.ilike(pattern, escape="\\")
            )
            .order_by(ConversationMemory.pinned.desc(), ConversationMemory.updated_at.desc())
            .limit(min(limit, 200))
        ).all()
        return [memory_response(row) for row in rows]

    @app.post("/messages", response_model=EventResponse, status_code=status.HTTP_202_ACCEPTED)
    async def send_message(
        payload: MessageRequest,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("messages:send")),
    ) -> EventResponse:
        target_agent = db.scalar(select(AgentAccount).where(AgentAccount.handle == payload.to_handle))
        if not target_agent:
            raise HTTPException(status_code=404, detail="target handle not found")
        require_contact_permission(db, user, target_agent, "dm")
        from_handle = user.username
        if payload.from_agent_id:
            from_agent = db.get(AgentAccount, payload.from_agent_id)
            if not from_agent or from_agent.owner_user_id != user.user_id:
                raise HTTPException(status_code=404, detail="from agent not found for this account")
            from_handle = from_agent.handle
        conversation = get_or_create_conversation(db, user, target_agent, conversation_id=payload.conversation_id)
        message = SocialMessage(
            conversation_id=conversation.conversation_id,
            from_user_id=user.user_id,
            from_agent_id=payload.from_agent_id,
            from_handle=from_handle,
            to_agent_id=target_agent.agent_id,
            to_handle=target_agent.handle,
            message_type=payload.message_type,
            body=payload.body,
        )
        db.add(message)
        db.flush()
        conversation.last_message_at = message.created_at
        event = await app.state.event_bus.publish(
            db,
            "message.queued",
            {
                "conversation_id": conversation.conversation_id,
                "message_id": message.message_id,
                "from_user_id": user.user_id,
                "from_handle": from_handle,
                "to_agent_id": target_agent.agent_id,
                "to_handle": target_agent.handle,
                "body": payload.body,
            },
            target_agent.owner_user_id,
        )
        await app.state.event_bus.publish(
            db,
            "message.sent",
            {
                "event_id": event.event_id,
                "conversation_id": conversation.conversation_id,
                "message_id": message.message_id,
                "from_user_id": user.user_id,
                "from_handle": from_handle,
                "to_agent_id": target_agent.agent_id,
                "to_handle": target_agent.handle,
                "body": payload.body,
            },
            user.user_id,
        )
        return EventResponse(
            cursor_id=event.id,
            event_id=event.event_id,
            event_type=event.event_type,
            account_id=event.account_id,
            payload=json.loads(event.payload_json),
        )

    @app.post("/groups", response_model=GroupResponse, status_code=status.HTTP_201_CREATED)
    async def create_group(
        payload: GroupCreateRequest,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("groups:write")),
    ) -> GroupResponse:
        existing = db.scalar(select(Group).where(Group.handle == payload.handle))
        if existing:
            raise HTTPException(status_code=409, detail="group handle already exists")
        default_permissions = normalize_group_permissions(payload.permissions)
        owner_permissions = normalize_group_permissions(DEFAULT_GROUP_PERMISSIONS, default_full=True)
        group = Group(
            owner_user_id=user.user_id,
            handle=payload.handle,
            title=payload.title,
            description=payload.description,
            group_type=payload.group_type,
            default_permissions_json=json.dumps(default_permissions, sort_keys=True),
        )
        db.add(group)
        db.flush()
        owner_member = GroupMember(
            group_id=group.group_id,
            user_id=user.user_id,
            handle_snapshot=user.username,
            role="owner",
            permissions_json=json.dumps(owner_permissions, sort_keys=True),
        )
        db.add(owner_member)
        audit(db, user, "group.create", "group", group.group_id, {"handle": group.handle, "title": group.title})
        db.commit()
        db.refresh(group)
        await app.state.event_bus.publish(
            db,
            "group.created",
            {"group_id": group.group_id, "handle": group.handle, "title": group.title},
            user.user_id,
        )
        return group_response(group)

    @app.get("/groups", response_model=list[GroupResponse])
    def list_groups(
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("groups:read")),
        limit: int = 100,
    ) -> list[GroupResponse]:
        rows = db.scalars(
            select(Group)
            .join(GroupMember, GroupMember.group_id == Group.group_id)
            .where(GroupMember.user_id == user.user_id)
            .where(GroupMember.status == "active")
            .order_by(Group.updated_at.desc(), Group.created_at.desc())
            .limit(min(limit, 200))
        ).unique().all()
        return [group_response(group) for group in rows]

    @app.get("/groups/{group_id_or_handle}", response_model=GroupResponse)
    def get_group(
        group_id_or_handle: str,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("groups:read")),
    ) -> GroupResponse:
        group, _member = require_group_permission(db, user, group_id_or_handle, "group_read")
        return group_response(group)

    @app.post("/groups/{group_id_or_handle}/members", response_model=GroupMemberResponse, status_code=status.HTTP_201_CREATED)
    async def add_group_member(
        group_id_or_handle: str,
        payload: GroupMemberAddRequest,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("groups:write")),
    ) -> GroupMemberResponse:
        group, _member = require_group_permission(db, user, group_id_or_handle, "group_invite")
        role = payload.role.strip().lower()
        if role not in {"admin", "member"}:
            raise HTTPException(status_code=400, detail="role must be admin or member")
        target_agent = db.scalar(select(AgentAccount).where(AgentAccount.handle == payload.handle))
        if not target_agent:
            raise HTTPException(status_code=404, detail="target handle not found")
        require_contact_permission(db, user, target_agent, "group_invite")
        permissions = normalize_group_permissions(payload.permissions or parse_json_list(group.default_permissions_json))
        existing = db.scalar(
            select(GroupMember)
            .where(GroupMember.group_id == group.group_id)
            .where(GroupMember.agent_id == target_agent.agent_id)
        )
        if existing:
            existing.role = role
            existing.permissions_json = json.dumps(permissions, sort_keys=True)
            existing.status = "active"
            existing.handle_snapshot = target_agent.handle
            member = existing
        else:
            member = GroupMember(
                group_id=group.group_id,
                user_id=target_agent.owner_user_id,
                agent_id=target_agent.agent_id,
                handle_snapshot=target_agent.handle,
                role=role,
                permissions_json=json.dumps(permissions, sort_keys=True),
            )
            db.add(member)
        group.updated_at = utc_now()
        db.flush()
        audit(
            db,
            user,
            "group.member.add",
            "group",
            group.group_id,
            {"handle": target_agent.handle, "role": member.role, "permissions": permissions},
        )
        db.commit()
        db.refresh(member)
        await app.state.event_bus.publish(
            db,
            "group.member.added",
            {
                "group_id": group.group_id,
                "group_handle": group.handle,
                "member_id": member.member_id,
                "handle": target_agent.handle,
                "role": member.role,
                "permissions": permissions,
            },
            target_agent.owner_user_id,
        )
        return group_member_response(member)

    @app.get("/groups/{group_id_or_handle}/members", response_model=list[GroupMemberResponse])
    def list_group_members(
        group_id_or_handle: str,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("groups:read")),
        limit: int = 100,
    ) -> list[GroupMemberResponse]:
        group, _member = require_group_permission(db, user, group_id_or_handle, "group_read")
        members = db.scalars(
            select(GroupMember)
            .where(GroupMember.group_id == group.group_id)
            .where(GroupMember.status == "active")
            .order_by(GroupMember.created_at.asc())
            .limit(min(limit, 200))
        ).all()
        return [group_member_response(member) for member in members]

    @app.post("/groups/{group_id_or_handle}/messages", response_model=GroupMessageResponse, status_code=status.HTTP_201_CREATED)
    async def send_group_message(
        group_id_or_handle: str,
        payload: GroupMessageRequest,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("groups:write")),
    ) -> GroupMessageResponse:
        group, _member = require_group_permission(db, user, group_id_or_handle, "group_write")
        from_handle = user.username
        if payload.from_agent_id:
            from_agent = db.get(AgentAccount, payload.from_agent_id)
            if not from_agent or from_agent.owner_user_id != user.user_id:
                raise HTTPException(status_code=404, detail="from agent not found for this account")
            from_handle = from_agent.handle
        message = GroupMessage(
            group_id=group.group_id,
            from_user_id=user.user_id,
            from_agent_id=payload.from_agent_id,
            from_handle=from_handle,
            message_type=payload.message_type,
            body=payload.body,
            metadata_json=dump_json(payload.metadata),
        )
        db.add(message)
        group.updated_at = utc_now()
        db.flush()
        audit(db, user, "group.message.create", "group", group.group_id, {"message_id": message.group_message_id})
        db.commit()
        db.refresh(message)
        recipients = set(
            db.scalars(
                select(GroupMember.user_id)
                .where(GroupMember.group_id == group.group_id)
                .where(GroupMember.status == "active")
            ).all()
        )
        for recipient_user_id in recipients:
            await app.state.event_bus.publish(
                db,
                "group.message",
                {
                    "group_id": group.group_id,
                    "group_handle": group.handle,
                    "message_id": message.group_message_id,
                    "from_handle": message.from_handle,
                    "body": message.body,
                },
                recipient_user_id,
            )
        return group_message_response(message)

    @app.get("/groups/{group_id_or_handle}/messages", response_model=list[GroupMessageResponse])
    def list_group_messages(
        group_id_or_handle: str,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("groups:read")),
        limit: int = 100,
    ) -> list[GroupMessageResponse]:
        group, _member = require_group_permission(db, user, group_id_or_handle, "group_read")
        messages = db.scalars(
            select(GroupMessage)
            .where(GroupMessage.group_id == group.group_id)
            .order_by(GroupMessage.created_at.asc())
            .limit(min(limit, 500))
        ).all()
        return [group_message_response(message) for message in messages]

    @app.get("/groups/{group_id_or_handle}/memory", response_model=GroupMemoryResponse | None)
    def get_group_memory(
        group_id_or_handle: str,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("groups:read")),
    ) -> GroupMemoryResponse | None:
        group, _member = require_group_permission(db, user, group_id_or_handle, "memory_read")
        memory = db.scalar(
            select(GroupMemory)
            .where(GroupMemory.group_id == group.group_id)
            .where(GroupMemory.owner_user_id == user.user_id)
        )
        return group_memory_response(memory) if memory else None

    @app.put("/groups/{group_id_or_handle}/memory", response_model=GroupMemoryResponse)
    async def upsert_group_memory(
        group_id_or_handle: str,
        payload: GroupMemoryRequest,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("groups:write")),
    ) -> GroupMemoryResponse:
        group, _member = require_group_permission(db, user, group_id_or_handle, "memory_write")
        memory = db.scalar(
            select(GroupMemory)
            .where(GroupMemory.group_id == group.group_id)
            .where(GroupMemory.owner_user_id == user.user_id)
        )
        if not memory:
            memory = GroupMemory(group_id=group.group_id, owner_user_id=user.user_id)
            db.add(memory)
        memory.title = payload.title
        memory.summary = payload.summary
        memory.key_facts_json = json.dumps(payload.key_facts, sort_keys=True)
        memory.pinned = payload.pinned
        memory.updated_at = utc_now()
        group.updated_at = utc_now()
        audit(db, user, "group_memory.upsert", "group", group.group_id, {"pinned": memory.pinned})
        db.commit()
        db.refresh(memory)
        await app.state.event_bus.publish(
            db,
            "group_memory.updated",
            {"group_id": group.group_id, "memory_id": memory.group_memory_id},
            user.user_id,
        )
        return group_memory_response(memory)

    @app.post("/groups/{group_id_or_handle}/memory/refresh", response_model=GroupMemoryResponse)
    async def refresh_group_memory(
        group_id_or_handle: str,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("groups:write")),
        limit: int = 50,
    ) -> GroupMemoryResponse:
        group, _member = require_group_permission(db, user, group_id_or_handle, "memory_write")
        messages = db.scalars(
            select(GroupMessage)
            .where(GroupMessage.group_id == group.group_id)
            .order_by(GroupMessage.created_at.desc())
            .limit(min(limit, 200))
        ).all()
        chronological = list(reversed(messages))
        lines = [f"{message.from_handle}: {message.body}" for message in chronological if message.body.strip()]
        summary = "\n".join(lines)[-12000:]
        handles = sorted({message.from_handle for message in chronological})
        key_facts = [
            f"messages_considered={len(chronological)}",
            f"participants={', '.join(handles)}",
        ]
        memory = db.scalar(
            select(GroupMemory)
            .where(GroupMemory.group_id == group.group_id)
            .where(GroupMemory.owner_user_id == user.user_id)
        )
        if not memory:
            memory = GroupMemory(group_id=group.group_id, owner_user_id=user.user_id)
            db.add(memory)
        memory.title = group.title
        memory.summary = summary
        memory.key_facts_json = json.dumps(key_facts, sort_keys=True)
        memory.updated_at = utc_now()
        group.updated_at = utc_now()
        audit(db, user, "group_memory.refresh", "group", group.group_id, {"message_count": len(chronological)})
        db.commit()
        db.refresh(memory)
        await app.state.event_bus.publish(
            db,
            "group_memory.refreshed",
            {"group_id": group.group_id, "memory_id": memory.group_memory_id, "message_count": len(chronological)},
            user.user_id,
        )
        return group_memory_response(memory)

    @app.post("/groups/{group_id_or_handle}/tasks", response_model=GroupTaskContextResponse, status_code=status.HTTP_201_CREATED)
    async def attach_group_task(
        group_id_or_handle: str,
        payload: GroupTaskAttachRequest,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("groups:write")),
    ) -> GroupTaskContextResponse:
        group, _member = require_group_permission(db, user, group_id_or_handle, "task_create")
        task = visible_task(db, payload.task_id, user)
        context = db.scalar(
            select(GroupTaskContext)
            .where(GroupTaskContext.group_id == group.group_id)
            .where(GroupTaskContext.task_id == task.task_id)
        )
        if context:
            context.note = payload.note or context.note
        else:
            context = GroupTaskContext(
                group_id=group.group_id,
                task_id=task.task_id,
                created_by_user_id=user.user_id,
                note=payload.note,
            )
            db.add(context)
        group.updated_at = utc_now()
        db.flush()
        audit(db, user, "group.task.attach", "group", group.group_id, {"task_id": task.task_id})
        db.commit()
        db.refresh(context)
        recipients = set(
            db.scalars(
                select(GroupMember.user_id)
                .where(GroupMember.group_id == group.group_id)
                .where(GroupMember.status == "active")
            ).all()
        )
        for recipient_user_id in recipients:
            await app.state.event_bus.publish(
                db,
                "group.task.attached",
                {"group_id": group.group_id, "group_handle": group.handle, "task_id": task.task_id, "context_id": context.context_id},
                recipient_user_id,
            )
        return group_task_context_response(context, task)

    @app.get("/groups/{group_id_or_handle}/tasks", response_model=list[GroupTaskContextResponse])
    def list_group_tasks(
        group_id_or_handle: str,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("groups:read")),
        limit: int = 100,
    ) -> list[GroupTaskContextResponse]:
        group, _member = require_group_permission(db, user, group_id_or_handle, "group_read")
        contexts = db.scalars(
            select(GroupTaskContext)
            .where(GroupTaskContext.group_id == group.group_id)
            .order_by(GroupTaskContext.created_at.desc())
            .limit(min(limit, 200))
        ).all()
        responses: list[GroupTaskContextResponse] = []
        for context in contexts:
            task = db.get(ServiceTask, context.task_id)
            if task:
                responses.append(group_task_context_response(context, task))
        return responses

    @app.post("/needs", response_model=NeedPostResponse, status_code=status.HTTP_201_CREATED)
    async def create_need(
        payload: NeedPostCreateRequest,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("community:write")),
    ) -> NeedPostResponse:
        need = NeedPost(
            author_user_id=user.user_id,
            title=payload.title,
            summary=payload.summary,
            description=payload.description,
            category=payload.category.strip().lower() or "general",
            visibility=normalize_need_visibility(payload.visibility),
            budget_cents=payload.budget_cents,
            currency=payload.currency,
            input_json=dump_json(payload.input),
            deliverables_json=dump_json(payload.deliverables),
            acceptance_criteria_json=dump_json(payload.acceptance_criteria),
            tags_json=json.dumps(normalize_need_tags(payload.tags), sort_keys=True),
        )
        db.add(need)
        db.flush()
        audit(db, user, "need.create", "need", need.need_id, {"title": need.title, "category": need.category})
        db.commit()
        db.refresh(need)
        await app.state.event_bus.publish(
            db,
            "need.created",
            {"need_id": need.need_id, "title": need.title, "category": need.category, "visibility": need.visibility},
            user.user_id,
        )
        return need_response(need)

    @app.get("/needs", response_model=list[NeedPostResponse])
    def list_needs(
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("community:read")),
        query: str | None = None,
        category: str | None = None,
        status: str | None = "open",
        limit: int = 50,
    ) -> list[NeedPostResponse]:
        stmt = select(NeedPost).where(
            ((NeedPost.visibility == "public") & (NeedPost.status != "hidden")) | (NeedPost.author_user_id == user.user_id)
        )
        if status and status != "any":
            normalized_status = normalize_need_status(status)
            stmt = stmt.where(NeedPost.status == normalized_status)
        if category:
            stmt = stmt.where(NeedPost.category == category.strip().lower())
        if query:
            if len(query.strip()) < 2:
                raise HTTPException(status_code=400, detail="query must be at least 2 characters")
            pattern = contains_pattern(query)
            stmt = stmt.where(
                NeedPost.title.ilike(pattern, escape="\\")
                | NeedPost.summary.ilike(pattern, escape="\\")
                | NeedPost.description.ilike(pattern, escape="\\")
                | NeedPost.tags_json.ilike(pattern, escape="\\")
            )
        rows = db.scalars(stmt.order_by(NeedPost.updated_at.desc(), NeedPost.created_at.desc()).limit(min(limit, 200))).all()
        return [need_response(row) for row in rows]

    @app.get("/needs/{need_id}", response_model=NeedPostResponse)
    def get_need(
        need_id: str,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("community:read")),
    ) -> NeedPostResponse:
        return need_response(visible_need(db, need_id, user))

    @app.post("/needs/{need_id}/moderation", response_model=NeedPostResponse)
    async def moderate_need(
        need_id: str,
        payload: NeedModerationRequest,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("community:write")),
    ) -> NeedPostResponse:
        need = author_owned_need(db, need_id, user)
        action = payload.action.strip().lower()
        if action not in KNOWN_COMMUNITY_MODERATION_ACTIONS:
            raise HTTPException(status_code=400, detail=f"unsupported moderation action: {payload.action}")
        if action == "close":
            if need.status != "open":
                raise HTTPException(status_code=400, detail=f"need is not open: {need.status}")
            need.status = "closed"
        elif action == "hide":
            if need.status == "hidden":
                raise HTTPException(status_code=400, detail="need is already hidden")
            need.status = "hidden"
        need.updated_at = utc_now()
        audit(db, user, f"need.{action}", "need", need.need_id, {"note": payload.note})
        db.commit()
        db.refresh(need)
        event_type = {"close": "need.closed", "hide": "need.hidden"}[action]
        await app.state.event_bus.publish(
            db,
            event_type,
            {"need_id": need.need_id, "status": need.status, "note": payload.note},
            user.user_id,
        )
        return need_response(need)

    @app.post("/needs/{need_id}/reports", response_model=CommunityReportResponse, status_code=status.HTTP_201_CREATED)
    async def report_need(
        need_id: str,
        payload: CommunityReportCreateRequest,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("community:write")),
    ) -> CommunityReportResponse:
        need, target_id = validate_community_report_target(
            db, user, need_id=need_id, target_type="need", target_id=need_id
        )
        report = CommunityReport(
            reporter_user_id=user.user_id,
            target_type="need",
            target_id=target_id,
            reason=normalize_community_report_reason(payload.reason),
            details=payload.details,
            metadata_json=dump_json(payload.metadata),
        )
        db.add(report)
        db.flush()
        audit(db, user, "community.report.create", "need", target_id, {"report_id": report.report_id, "reason": report.reason})
        db.commit()
        db.refresh(report)
        await app.state.event_bus.publish(
            db,
            "community.report.created",
            {"report_id": report.report_id, "target_type": report.target_type, "target_id": report.target_id},
            need.author_user_id,
        )
        return community_report_response(report)

    @app.post("/needs/{need_id}/discussion", response_model=NeedDiscussionResponse, status_code=status.HTTP_201_CREATED)
    async def create_need_discussion(
        need_id: str,
        payload: NeedDiscussionCreateRequest,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("community:write")),
    ) -> NeedDiscussionResponse:
        need = visible_need(db, need_id, user)
        ensure_need_discussion_open_for_updates(need)
        author_agent_id = validate_agent_owner(db, user, payload.author_agent_id)
        comment = NeedDiscussion(
            need_id=need.need_id,
            author_user_id=user.user_id,
            author_agent_id=author_agent_id,
            body=payload.body,
            metadata_json=dump_json(payload.metadata),
        )
        db.add(comment)
        db.flush()
        audit(db, user, "need.discussion.create", "need", need.need_id, {"comment_id": comment.comment_id})
        db.commit()
        db.refresh(comment)
        recipients = {need.author_user_id}
        recipients.update(
            db.scalars(
                select(NeedBid.bidder_user_id)
                .where(NeedBid.need_id == need.need_id)
                .where(NeedBid.status.in_(["proposed", "accepted"]))
            ).all()
        )
        for recipient_user_id in recipients:
            await app.state.event_bus.publish(
                db,
                "need.discussion",
                {
                    "need_id": need.need_id,
                    "comment_id": comment.comment_id,
                    "author_user_id": user.user_id,
                },
                recipient_user_id,
            )
        return need_discussion_response(comment)

    @app.get("/needs/{need_id}/discussion", response_model=list[NeedDiscussionResponse])
    def list_need_discussion(
        need_id: str,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("community:read")),
        limit: int = 100,
    ) -> list[NeedDiscussionResponse]:
        need = visible_need(db, need_id, user)
        comments = db.scalars(
            select(NeedDiscussion)
            .where(NeedDiscussion.need_id == need.need_id)
            .order_by(NeedDiscussion.created_at.asc())
            .limit(min(limit, 500))
        ).all()
        return [need_discussion_response(comment) for comment in comments]

    @app.post(
        "/needs/{need_id}/discussion/{comment_id}/reports",
        response_model=CommunityReportResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def report_need_discussion(
        need_id: str,
        comment_id: str,
        payload: CommunityReportCreateRequest,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("community:write")),
    ) -> CommunityReportResponse:
        need, target_id = validate_community_report_target(
            db, user, need_id=need_id, target_type="need_comment", target_id=comment_id
        )
        report = CommunityReport(
            reporter_user_id=user.user_id,
            target_type="need_comment",
            target_id=target_id,
            reason=normalize_community_report_reason(payload.reason),
            details=payload.details,
            metadata_json=dump_json(payload.metadata),
        )
        db.add(report)
        db.flush()
        audit(
            db,
            user,
            "community.report.create",
            "need_comment",
            target_id,
            {"report_id": report.report_id, "need_id": need.need_id, "reason": report.reason},
        )
        db.commit()
        db.refresh(report)
        await app.state.event_bus.publish(
            db,
            "community.report.created",
            {"report_id": report.report_id, "target_type": report.target_type, "target_id": report.target_id},
            need.author_user_id,
        )
        return community_report_response(report)

    @app.post("/needs/{need_id}/bids", response_model=NeedBidResponse, status_code=status.HTTP_201_CREATED)
    async def create_need_bid(
        need_id: str,
        payload: NeedBidCreateRequest,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("community:write")),
    ) -> NeedBidResponse:
        need = visible_need(db, need_id, user)
        if need.status != "open":
            raise HTTPException(status_code=400, detail=f"need is not open: {need.status}")
        if need.author_user_id == user.user_id:
            raise HTTPException(status_code=400, detail="need author cannot bid on their own need")
        provider_id, service_id, agent_id = validate_need_bid_party(db, user, payload)
        bid = NeedBid(
            need_id=need.need_id,
            bidder_user_id=user.user_id,
            provider_id=provider_id,
            service_id=service_id,
            agent_id=agent_id,
            proposal=payload.proposal,
            amount_cents=payload.amount_cents,
            currency=payload.currency,
            estimated_delivery=payload.estimated_delivery,
            terms_json=dump_json(payload.terms),
        )
        db.add(bid)
        need.updated_at = utc_now()
        db.flush()
        audit(
            db,
            user,
            "need.bid.create",
            "need",
            need.need_id,
            {"bid_id": bid.bid_id, "provider_id": provider_id, "service_id": service_id},
        )
        db.commit()
        db.refresh(bid)
        await app.state.event_bus.publish(
            db,
            "need.bid.created",
            {
                "need_id": need.need_id,
                "bid_id": bid.bid_id,
                "provider_id": bid.provider_id,
                "service_id": bid.service_id,
                "agent_id": bid.agent_id,
            },
            need.author_user_id,
        )
        return need_bid_response(db, bid)

    @app.get("/needs/{need_id}/bids", response_model=list[NeedBidResponse])
    def list_need_bids(
        need_id: str,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("community:read")),
        limit: int = 100,
    ) -> list[NeedBidResponse]:
        need = visible_need(db, need_id, user)
        stmt = select(NeedBid).where(NeedBid.need_id == need.need_id)
        if need.visibility != "public" and need.author_user_id != user.user_id:
            stmt = stmt.where(NeedBid.bidder_user_id == user.user_id)
        bids = db.scalars(stmt.order_by(NeedBid.created_at.asc()).limit(min(limit, 200))).all()
        return [need_bid_response(db, bid) for bid in bids]

    @app.post("/needs/{need_id}/bids/{bid_id}/reports", response_model=CommunityReportResponse, status_code=status.HTTP_201_CREATED)
    async def report_need_bid(
        need_id: str,
        bid_id: str,
        payload: CommunityReportCreateRequest,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("community:write")),
    ) -> CommunityReportResponse:
        need, target_id = validate_community_report_target(
            db, user, need_id=need_id, target_type="need_bid", target_id=bid_id
        )
        report = CommunityReport(
            reporter_user_id=user.user_id,
            target_type="need_bid",
            target_id=target_id,
            reason=normalize_community_report_reason(payload.reason),
            details=payload.details,
            metadata_json=dump_json(payload.metadata),
        )
        db.add(report)
        db.flush()
        audit(
            db,
            user,
            "community.report.create",
            "need_bid",
            target_id,
            {"report_id": report.report_id, "need_id": need.need_id, "reason": report.reason},
        )
        db.commit()
        db.refresh(report)
        await app.state.event_bus.publish(
            db,
            "community.report.created",
            {"report_id": report.report_id, "target_type": report.target_type, "target_id": report.target_id},
            need.author_user_id,
        )
        return community_report_response(report)

    @app.post("/needs/{need_id}/bids/{bid_id}/accept", response_model=NeedAcceptBidResponse)
    async def accept_need_bid(
        need_id: str,
        bid_id: str,
        payload: NeedAcceptBidRequest,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("community:write")),
    ) -> NeedAcceptBidResponse:
        need = author_owned_need(db, need_id, user)
        if need.status != "open":
            raise HTTPException(status_code=400, detail=f"need is not open: {need.status}")
        bid = db.get(NeedBid, bid_id)
        if not bid or bid.need_id != need.need_id:
            raise HTTPException(status_code=404, detail="bid not found for this need")
        if bid.status != "proposed":
            raise HTTPException(status_code=400, detail=f"bid is not proposed: {bid.status}")
        if payload.create_task and not bid.service_id:
            raise HTTPException(status_code=400, detail="accepted bid must include service_id when create_task is true")

        group = ensure_need_group(db, user, need, payload)
        if bid.agent_id:
            agent = db.get(AgentAccount, bid.agent_id)
            if not agent or agent.owner_user_id != bid.bidder_user_id:
                raise HTTPException(status_code=400, detail="bid agent is no longer valid")
            permissions = normalize_group_permissions(parse_json_list(group.default_permissions_json))
            existing_member = db.scalar(
                select(GroupMember)
                .where(GroupMember.group_id == group.group_id)
                .where(GroupMember.agent_id == agent.agent_id)
            )
            if existing_member:
                existing_member.user_id = agent.owner_user_id
                existing_member.handle_snapshot = agent.handle
                existing_member.role = "member"
                existing_member.permissions_json = json.dumps(permissions, sort_keys=True)
                existing_member.status = "active"
            else:
                db.add(
                    GroupMember(
                        group_id=group.group_id,
                        user_id=agent.owner_user_id,
                        agent_id=agent.agent_id,
                        handle_snapshot=agent.handle,
                        role="member",
                        permissions_json=json.dumps(permissions, sort_keys=True),
                    )
                )

        task: ServiceTask | None = None
        if payload.create_task:
            service = db.get(ServiceProfile, bid.service_id)
            if not service or service.status != "active":
                raise HTTPException(status_code=404, detail="service profile not found")
            provider = db.get(Provider, service.provider_id)
            if not provider or provider.provider_id != bid.provider_id or provider.owner_user_id != bid.bidder_user_id:
                raise HTTPException(status_code=400, detail="bid provider is no longer valid")
            task_input = dict(payload.task_input or parse_json(need.input_json))
            task_input.setdefault(
                "community_need",
                {
                    "need_id": need.need_id,
                    "title": need.title,
                    "summary": need.summary,
                    "description": need.description,
                    "deliverables": parse_json(need.deliverables_json),
                    "acceptance_criteria": parse_json(need.acceptance_criteria_json),
                },
            )
            task = ServiceTask(
                requester_user_id=user.user_id,
                service_id=service.service_id,
                provider_id=service.provider_id,
                status="created",
                input_json=dump_json(task_input),
            )
            db.add(task)
            db.flush()
            db.add(
                GroupTaskContext(
                    group_id=group.group_id,
                    task_id=task.task_id,
                    created_by_user_id=user.user_id,
                    note=payload.note or f"Accepted community need bid {bid.bid_id}",
                )
            )
            need.task_id = task.task_id

        now = utc_now()
        need.status = "assigned"
        need.selected_bid_id = bid.bid_id
        need.group_id = group.group_id
        need.updated_at = now
        bid.status = "accepted"
        bid.updated_at = now
        group.updated_at = now
        rejected_bids = db.scalars(
            select(NeedBid)
            .where(NeedBid.need_id == need.need_id)
            .where(NeedBid.bid_id != bid.bid_id)
            .where(NeedBid.status == "proposed")
        ).all()
        for rejected_bid in rejected_bids:
            rejected_bid.status = "rejected"
            rejected_bid.updated_at = now
        audit(
            db,
            user,
            "need.bid.accept",
            "need",
            need.need_id,
            {"bid_id": bid.bid_id, "group_id": group.group_id, "task_id": task.task_id if task else None},
        )
        db.commit()
        db.refresh(need)
        db.refresh(bid)
        db.refresh(group)
        if task:
            db.refresh(task)
        await app.state.event_bus.publish(
            db,
            "need.bid.accepted",
            {
                "need_id": need.need_id,
                "bid_id": bid.bid_id,
                "group_id": group.group_id,
                "task_id": task.task_id if task else None,
            },
            bid.bidder_user_id,
        )
        await app.state.event_bus.publish(
            db,
            "need.assigned",
            {
                "need_id": need.need_id,
                "bid_id": bid.bid_id,
                "group_id": group.group_id,
                "task_id": task.task_id if task else None,
            },
            user.user_id,
        )
        return NeedAcceptBidResponse(
            need=need_response(need).model_dump(),
            bid=need_bid_response(db, bid).model_dump(),
            group=group_response(group).model_dump(),
            task=task_response(task).model_dump() if task else None,
        )

    @app.post("/providers", response_model=ProviderResponse, status_code=status.HTTP_201_CREATED)
    async def create_provider(
        payload: ProviderCreateRequest,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("services:write")),
    ) -> ProviderResponse:
        if payload.agent_id:
            agent = db.get(AgentAccount, payload.agent_id)
            if not agent or agent.owner_user_id != user.user_id:
                raise HTTPException(status_code=404, detail="agent not found for this account")
        provider = Provider(
            owner_user_id=user.user_id,
            agent_id=payload.agent_id,
            display_name=payload.display_name,
            provider_type=payload.provider_type,
            website=payload.website,
        )
        db.add(provider)
        db.flush()
        audit(db, user, "provider.create", "provider", provider.provider_id, {"display_name": provider.display_name})
        db.commit()
        db.refresh(provider)
        await app.state.event_bus.publish(
            db,
            "provider.created",
            {"provider_id": provider.provider_id, "display_name": provider.display_name},
            user.user_id,
        )
        return provider_response(db, provider)

    @app.post("/providers/{provider_id}/verification", response_model=ProviderResponse)
    async def update_provider_verification(
        provider_id: str,
        payload: ProviderVerificationUpdateRequest,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("services:write")),
    ) -> ProviderResponse:
        provider = db.get(Provider, provider_id)
        if not provider or provider.owner_user_id != user.user_id:
            raise HTTPException(status_code=404, detail="provider not found for this account")
        provider.verification_status = normalize_provider_verification_status(payload.verification_status)
        provider.updated_at = utc_now()
        audit(
            db,
            user,
            "provider.verification.update",
            "provider",
            provider.provider_id,
            {"verification_status": provider.verification_status, "note": payload.note},
        )
        db.commit()
        db.refresh(provider)
        await app.state.event_bus.publish(
            db,
            "provider.verification.updated",
            {
                "provider_id": provider.provider_id,
                "verification_status": provider.verification_status,
                "note": payload.note,
            },
            user.user_id,
        )
        return provider_response(db, provider)

    @app.post("/service-profiles", response_model=ServiceProfileResponse, status_code=status.HTTP_201_CREATED)
    async def create_service_profile(
        payload: ServiceProfileCreateRequest,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("services:write")),
    ) -> ServiceProfileResponse:
        provider = db.get(Provider, payload.provider_id)
        if not provider or provider.owner_user_id != user.user_id:
            raise HTTPException(status_code=404, detail="provider not found for this account")
        service = ServiceProfile(
            provider_id=provider.provider_id,
            title=payload.title,
            description=payload.description,
            category=payload.category,
            pricing_model=payload.pricing_model,
            currency=payload.currency,
            base_price_cents=payload.base_price_cents,
            input_schema_json=dump_json(payload.input_schema),
            output_schema_json=dump_json(payload.output_schema),
            sla_json=dump_json(payload.sla),
        )
        db.add(service)
        db.flush()
        for item in payload.capabilities:
            db.add(
                Capability(
                    service_id=service.service_id,
                    name=item.name,
                    description=item.description,
                    input_schema_json=dump_json(item.input_schema),
                    output_schema_json=dump_json(item.output_schema),
                )
            )
        audit(db, user, "service_profile.create", "service_profile", service.service_id, {"title": service.title})
        db.commit()
        db.refresh(service)
        await app.state.event_bus.publish(
            db,
            "service_profile.created",
            {"service_id": service.service_id, "provider_id": provider.provider_id, "title": service.title},
            user.user_id,
        )
        return service_profile_response(db, service)

    @app.get("/service-profiles", response_model=list[ServiceProfileResponse])
    def search_service_profiles(
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("services:read")),
        query: str | None = None,
        category: str | None = None,
        capability: str | None = None,
        limit: int = 20,
    ) -> list[ServiceProfileResponse]:
        stmt = select(ServiceProfile).where(ServiceProfile.status == "active")
        if category:
            stmt = stmt.where(ServiceProfile.category == category)
        if query:
            pattern = contains_pattern(query)
            stmt = stmt.where(
                ServiceProfile.title.ilike(pattern, escape="\\")
                | ServiceProfile.description.ilike(pattern, escape="\\")
            )
        if capability:
            stmt = stmt.join(Capability, Capability.service_id == ServiceProfile.service_id).where(Capability.name == capability)
        services = db.scalars(stmt.limit(min(limit, 100))).all()
        return [service_profile_response(db, service) for service in services]

    @app.get("/service-profiles/{service_id}/agent-card")
    def service_agent_card(
        service_id: str,
        db: Session = Depends(get_db),
        _user: HumanAccount = Depends(scoped_user("services:read")),
    ) -> dict:
        service = db.get(ServiceProfile, service_id)
        if not service or service.status != "active":
            raise HTTPException(status_code=404, detail="service profile not found")
        provider = db.get(Provider, service.provider_id)
        agent = db.get(AgentAccount, provider.agent_id) if provider and provider.agent_id else None
        capabilities = db.scalars(select(Capability).where(Capability.service_id == service.service_id)).all()
        return {
            "schema": "ainet.agent-card.v0",
            "name": service.title,
            "description": service.description,
            "provider": {
                "provider_id": provider.provider_id if provider else service.provider_id,
                "display_name": provider.display_name if provider else service.provider_id,
                "verification_status": provider.verification_status if provider else "unknown",
            },
            "agent": {
                "agent_id": agent.agent_id,
                "handle": agent.handle,
                "runtime_type": agent.runtime_type,
                "key_id": agent.key_id,
                "verification_status": agent.verification_status,
            }
            if agent
            else None,
            "service": {
                "service_id": service.service_id,
                "category": service.category,
                "pricing_model": service.pricing_model,
                "currency": service.currency,
                "base_price_cents": service.base_price_cents,
                "input_schema": parse_json(service.input_schema_json),
                "output_schema": parse_json(service.output_schema_json),
                "sla": parse_json(service.sla_json),
            },
            "capabilities": [capability_response(capability).model_dump() for capability in capabilities],
            "security_schemes": [{"type": "bearer", "description": "Ainet access token"}],
        }

    @app.post("/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
    async def create_task(
        payload: TaskCreateRequest,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("services:write")),
    ) -> TaskResponse:
        service = db.get(ServiceProfile, payload.service_id)
        if not service or service.status != "active":
            raise HTTPException(status_code=404, detail="service profile not found")
        if payload.capability_id:
            capability = db.get(Capability, payload.capability_id)
            if not capability or capability.service_id != service.service_id:
                raise HTTPException(status_code=404, detail="capability not found for this service")
        provider = db.get(Provider, service.provider_id)
        if provider and provider.agent_id:
            provider_agent = db.get(AgentAccount, provider.agent_id)
            if provider_agent:
                require_contact_permission(db, user, provider_agent, "service_request")
        task = ServiceTask(
            requester_user_id=user.user_id,
            service_id=service.service_id,
            capability_id=payload.capability_id,
            provider_id=service.provider_id,
            status="created",
            input_json=dump_json(payload.input),
        )
        db.add(task)
        db.flush()
        audit(db, user, "task.create", "task", task.task_id, {"service_id": service.service_id})
        db.commit()
        db.refresh(task)
        await app.state.event_bus.publish(
            db,
            "task.created",
            {"task_id": task.task_id, "service_id": service.service_id, "provider_id": service.provider_id},
            user.user_id,
        )
        return task_response(task)

    @app.get("/tasks/{task_id}", response_model=TaskResponse)
    def get_task(
        task_id: str,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("services:read")),
    ) -> TaskResponse:
        return task_response(visible_task(db, task_id, user))

    @app.post("/tasks/{task_id}/accept", response_model=TaskResponse)
    async def accept_task(
        task_id: str,
        payload: TaskAcceptRequest,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("services:write")),
    ) -> TaskResponse:
        task, provider = provider_owned_task(db, task_id, user)
        validate_agent_owner(db, user, payload.accepted_by_agent_id)
        if task.status in FINAL_TASK_STATUSES:
            raise HTTPException(status_code=400, detail=f"cannot accept task in {task.status} state")
        task.status = "accepted"
        task.updated_at = utc_now()
        audit(db, user, "task.accept", "task", task.task_id, {"provider_id": provider.provider_id, "note": payload.note})
        db.commit()
        db.refresh(task)
        await app.state.event_bus.publish(
            db,
            "task.accepted",
            {"task_id": task.task_id, "provider_id": provider.provider_id, "note": payload.note},
            task.requester_user_id,
        )
        return task_response(task)

    @app.post("/tasks/{task_id}/status", response_model=TaskResponse)
    async def update_task_status(
        task_id: str,
        payload: TaskStatusUpdateRequest,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("services:write")),
    ) -> TaskResponse:
        task = db.get(ServiceTask, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="task not found")
        status_value = normalize_task_status(payload.status)
        if task.status in FINAL_TASK_STATUSES and status_value != task.status:
            raise HTTPException(status_code=400, detail=f"cannot update task in {task.status} state")
        provider = db.get(Provider, task.provider_id)
        if provider and provider.owner_user_id == user.user_id:
            if status_value not in PROVIDER_WRITABLE_TASK_STATUSES:
                raise HTTPException(status_code=400, detail=f"provider cannot set task status: {status_value}")
            event_account_id = task.requester_user_id
        elif task.requester_user_id == user.user_id:
            if status_value not in REQUESTER_WRITABLE_TASK_STATUSES:
                raise HTTPException(status_code=400, detail=f"requester cannot set task status: {status_value}")
            event_account_id = provider.owner_user_id if provider else None
        else:
            raise HTTPException(status_code=403, detail="only requester or provider owner can update this task")
        task.status = status_value
        task.updated_at = utc_now()
        audit(db, user, "task.status_update", "task", task.task_id, {"status": task.status, "note": payload.note})
        db.commit()
        db.refresh(task)
        event_type = "task.status_updated"
        if status_value == "failed":
            event_type = "task.failed"
        elif status_value == "cancelled":
            event_type = "task.cancelled"
        await app.state.event_bus.publish(
            db,
            event_type,
            {"task_id": task.task_id, "status": task.status, "note": payload.note},
            event_account_id,
        )
        return task_response(task)

    @app.post("/artifacts", response_model=ArtifactResponse, status_code=status.HTTP_201_CREATED)
    async def create_artifact(
        payload: ArtifactCreateRequest,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("services:write")),
    ) -> ArtifactResponse:
        if payload.task_id:
            task = db.get(ServiceTask, payload.task_id)
            if not task:
                raise HTTPException(status_code=404, detail="task not found")
            provider = db.get(Provider, task.provider_id)
            is_requester = task.requester_user_id == user.user_id
            is_provider_owner = provider is not None and provider.owner_user_id == user.user_id
            if not is_requester and not is_provider_owner:
                raise HTTPException(status_code=403, detail="only requester or provider owner can attach artifacts")
        artifact = Artifact(
            task_id=payload.task_id,
            owner_user_id=user.user_id,
            filename=payload.filename,
            content_type=payload.content_type,
            size_bytes=payload.size_bytes,
            sha256=payload.sha256,
            storage_url=payload.storage_url,
        )
        db.add(artifact)
        db.flush()
        audit(db, user, "artifact.create", "artifact", artifact.artifact_id, {"task_id": artifact.task_id})
        db.commit()
        db.refresh(artifact)
        await app.state.event_bus.publish(
            db,
            "artifact.created",
            {"artifact_id": artifact.artifact_id, "task_id": artifact.task_id, "filename": artifact.filename},
            user.user_id,
        )
        return ArtifactResponse(
            artifact_id=artifact.artifact_id,
            task_id=artifact.task_id,
            filename=artifact.filename,
            content_type=artifact.content_type,
            size_bytes=artifact.size_bytes,
            sha256=artifact.sha256,
            storage_url=artifact.storage_url,
        )

    @app.post("/tasks/{task_id}/quote", response_model=QuoteResponse, status_code=status.HTTP_201_CREATED)
    async def create_quote(
        task_id: str,
        payload: QuoteCreateRequest,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("services:write")),
    ) -> QuoteResponse:
        task = db.get(ServiceTask, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="task not found")
        provider = db.get(Provider, task.provider_id)
        if not provider or provider.owner_user_id != user.user_id:
            raise HTTPException(status_code=403, detail="only provider owner can quote this task")
        quote = Quote(
            task_id=task.task_id,
            provider_id=task.provider_id,
            amount_cents=payload.amount_cents,
            currency=payload.currency,
            terms_json=dump_json(payload.terms),
        )
        db.add(quote)
        db.flush()
        task.status = "quoted"
        audit(db, user, "quote.create", "quote", quote.quote_id, {"task_id": task.task_id})
        db.commit()
        db.refresh(quote)
        await app.state.event_bus.publish(
            db,
            "quote.created",
            {"quote_id": quote.quote_id, "task_id": task.task_id, "amount_cents": quote.amount_cents},
            task.requester_user_id,
        )
        return QuoteResponse(
            quote_id=quote.quote_id,
            task_id=quote.task_id,
            provider_id=quote.provider_id,
            amount_cents=quote.amount_cents,
            currency=quote.currency,
            status=quote.status,
            terms=parse_json(quote.terms_json),
        )

    @app.post("/quotes/{quote_id}/accept", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
    async def accept_quote(
        quote_id: str,
        payload: QuoteAcceptRequest,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("services:write")),
    ) -> OrderResponse:
        quote = db.get(Quote, quote_id)
        if not quote:
            raise HTTPException(status_code=404, detail="quote not found")
        task = db.get(ServiceTask, quote.task_id)
        if not task:
            raise HTTPException(status_code=404, detail="task not found")
        if task.requester_user_id != user.user_id:
            raise HTTPException(status_code=403, detail="only requester can accept this quote")
        existing = db.scalar(select(ServiceOrder).where(ServiceOrder.quote_id == quote.quote_id))
        if existing:
            return order_response(db, existing)
        order = ServiceOrder(
            task_id=task.task_id,
            quote_id=quote.quote_id,
            buyer_user_id=user.user_id,
            provider_id=quote.provider_id,
            status="accepted",
        )
        db.add(order)
        db.flush()
        payment = PaymentRecord(
            order_id=order.order_id,
            amount_cents=quote.amount_cents,
            currency=quote.currency,
            status="authorized",
            provider_reference=payload.settlement_mode,
        )
        db.add(payment)
        quote.status = "accepted"
        task.status = "accepted"
        audit(
            db,
            user,
            "quote.accept",
            "quote",
            quote.quote_id,
            {"order_id": order.order_id, "settlement_mode": payload.settlement_mode},
        )
        db.commit()
        db.refresh(order)
        provider = db.get(Provider, order.provider_id)
        if provider:
            await app.state.event_bus.publish(
                db,
                "order.created",
                {"order_id": order.order_id, "task_id": task.task_id, "quote_id": quote.quote_id},
                provider.owner_user_id,
            )
        await app.state.event_bus.publish(
            db,
            "payment.authorized",
            {"payment_id": payment.payment_id, "order_id": order.order_id, "amount_cents": payment.amount_cents},
            user.user_id,
        )
        return order_response(db, order)

    @app.get("/orders", response_model=list[OrderResponse])
    def list_orders(
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("services:read")),
        limit: int = 100,
    ) -> list[OrderResponse]:
        provider_ids = [
            provider.provider_id
            for provider in db.scalars(select(Provider).where(Provider.owner_user_id == user.user_id)).all()
        ]
        stmt = select(ServiceOrder).where(
            (ServiceOrder.buyer_user_id == user.user_id)
            | (ServiceOrder.provider_id.in_(provider_ids) if provider_ids else ServiceOrder.provider_id == "__none__")
        )
        orders = db.scalars(stmt.order_by(ServiceOrder.created_at.desc()).limit(min(limit, 200))).all()
        return [order_response(db, order) for order in orders]

    @app.get("/payments", response_model=list[PaymentResponse])
    def list_payments(
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("services:read")),
        limit: int = 100,
    ) -> list[PaymentResponse]:
        provider_ids = [
            provider.provider_id
            for provider in db.scalars(select(Provider).where(Provider.owner_user_id == user.user_id)).all()
        ]
        orders = db.scalars(
            select(ServiceOrder).where(
                (ServiceOrder.buyer_user_id == user.user_id)
                | (ServiceOrder.provider_id.in_(provider_ids) if provider_ids else ServiceOrder.provider_id == "__none__")
            )
        ).all()
        order_ids = [order.order_id for order in orders]
        if not order_ids:
            return []
        payments = db.scalars(
            select(PaymentRecord)
            .where(PaymentRecord.order_id.in_(order_ids))
            .order_by(PaymentRecord.created_at.desc())
            .limit(min(limit, 200))
        ).all()
        return [payment_response(payment) for payment in payments]

    @app.get("/providers/{provider_id}/reputation", response_model=ProviderReputationResponse)
    def provider_reputation(
        provider_id: str,
        db: Session = Depends(get_db),
        _user: HumanAccount = Depends(scoped_user("services:read")),
    ) -> ProviderReputationResponse:
        provider = db.get(Provider, provider_id)
        if not provider:
            raise HTTPException(status_code=404, detail="provider not found")
        rating_count, average_score, completed_tasks, orders_count = provider_reputation_stats(db, provider_id)
        return ProviderReputationResponse(
            provider_id=provider_id,
            rating_count=rating_count,
            average_score=round(average_score, 2) if average_score is not None else None,
            completed_tasks=completed_tasks,
            orders_count=orders_count,
        )

    @app.post("/tasks/{task_id}/result", response_model=TaskResponse)
    async def complete_task(
        task_id: str,
        payload: TaskResultRequest,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("services:write")),
    ) -> TaskResponse:
        task, provider = provider_owned_task(db, task_id, user)
        status_value = normalize_task_status(payload.status)
        if task.status in {"verified", "rejected", "cancelled"}:
            raise HTTPException(status_code=400, detail=f"cannot submit result for task in {task.status} state")
        if status_value not in {"submitted", "completed", "failed", "cancelled"}:
            raise HTTPException(status_code=400, detail=f"unsupported result status: {payload.status}")
        artifact_ids = validate_task_artifacts(db, task, payload.artifact_ids)
        task.status = status_value
        task.result_json = dump_json(payload.result)
        task.updated_at = utc_now()
        receipt = TaskReceipt(
            task_id=task.task_id,
            provider_id=task.provider_id,
            provider_user_id=user.user_id,
            provider_agent_id=provider.agent_id,
            receipt_type="task_result",
            status=status_value,
            summary=payload.summary,
            artifact_ids_json=json.dumps(artifact_ids, sort_keys=True),
            usage_json=dump_json(payload.usage),
            result_json=dump_json(payload.result),
        )
        db.add(receipt)
        db.flush()
        audit(
            db,
            user,
            "task.result",
            "task",
            task.task_id,
            {"status": task.status, "receipt_id": receipt.receipt_id, "artifact_ids": artifact_ids},
        )
        db.commit()
        db.refresh(task)
        db.refresh(receipt)
        await app.state.event_bus.publish(
            db,
            "task.submitted" if task.status in {"submitted", "completed"} else f"task.{task.status}",
            {
                "task_id": task.task_id,
                "status": task.status,
                "receipt_id": receipt.receipt_id,
                "artifact_ids": artifact_ids,
            },
            task.requester_user_id,
        )
        return task_response(task)

    @app.get("/tasks/{task_id}/receipts", response_model=list[TaskReceiptResponse])
    def list_task_receipts(
        task_id: str,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("services:read")),
        limit: int = 100,
    ) -> list[TaskReceiptResponse]:
        task = visible_task(db, task_id, user)
        receipts = db.scalars(
            select(TaskReceipt)
            .where(TaskReceipt.task_id == task.task_id)
            .order_by(TaskReceipt.created_at.desc())
            .limit(min(limit, 200))
        ).all()
        return [task_receipt_response(receipt) for receipt in receipts]

    @app.post("/tasks/{task_id}/verify", response_model=VerificationRecordResponse, status_code=status.HTTP_201_CREATED)
    async def verify_task(
        task_id: str,
        payload: VerificationRecordRequest,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("services:write")),
    ) -> VerificationRecordResponse:
        task, provider = requester_owned_task(db, task_id, user)
        status_value = normalize_task_status(payload.status)
        if status_value not in VERIFICATION_TASK_STATUSES:
            raise HTTPException(status_code=400, detail="verification status must be verified or rejected")
        if task.status not in {"submitted", "completed", "verification_running"}:
            raise HTTPException(status_code=400, detail=f"cannot verify task in {task.status} state")
        verifier_agent_id = validate_agent_owner(db, user, payload.verifier_agent_id)
        evidence_artifact_ids = validate_task_artifacts(db, task, payload.evidence_artifact_ids)
        record = VerificationRecord(
            task_id=task.task_id,
            verifier_user_id=user.user_id,
            verifier_agent_id=verifier_agent_id,
            verification_type=payload.verification_type,
            status=status_value,
            rubric_json=dump_json(payload.rubric),
            result_json=dump_json(payload.result),
            evidence_artifact_ids_json=json.dumps(evidence_artifact_ids, sort_keys=True),
            comment=payload.comment,
        )
        db.add(record)
        task.status = status_value
        task.updated_at = utc_now()
        db.flush()
        audit(
            db,
            user,
            "task.verify" if status_value == "verified" else "task.reject",
            "task",
            task.task_id,
            {"verification_id": record.verification_id, "status": status_value, "evidence_artifact_ids": evidence_artifact_ids},
        )
        db.commit()
        db.refresh(record)
        await app.state.event_bus.publish(
            db,
            "task.verified" if status_value == "verified" else "task.rejected",
            {
                "task_id": task.task_id,
                "verification_id": record.verification_id,
                "status": status_value,
                "verification_type": record.verification_type,
            },
            provider.owner_user_id if provider else None,
        )
        return verification_record_response(record)

    @app.post("/tasks/{task_id}/reject", response_model=VerificationRecordResponse, status_code=status.HTTP_201_CREATED)
    async def reject_task(
        task_id: str,
        payload: VerificationRecordRequest,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("services:write")),
    ) -> VerificationRecordResponse:
        payload.status = "rejected"
        return await verify_task(task_id, payload, db, user)

    @app.get("/tasks/{task_id}/verifications", response_model=list[VerificationRecordResponse])
    def list_task_verifications(
        task_id: str,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("services:read")),
        limit: int = 100,
    ) -> list[VerificationRecordResponse]:
        task = visible_task(db, task_id, user)
        records = db.scalars(
            select(VerificationRecord)
            .where(VerificationRecord.task_id == task.task_id)
            .order_by(VerificationRecord.created_at.desc())
            .limit(min(limit, 200))
        ).all()
        return [verification_record_response(record) for record in records]

    @app.post("/tasks/{task_id}/rating", response_model=RatingResponse, status_code=status.HTTP_201_CREATED)
    async def rate_task(
        task_id: str,
        payload: RatingCreateRequest,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("services:write")),
    ) -> RatingResponse:
        task = db.get(ServiceTask, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="task not found")
        if task.requester_user_id != user.user_id:
            raise HTTPException(status_code=403, detail="only requester can rate this task")
        if task.status not in {"verified", "completed"}:
            raise HTTPException(status_code=400, detail="task must be verified before rating")
        rating = Rating(
            task_id=task.task_id,
            reviewer_user_id=user.user_id,
            provider_id=task.provider_id,
            score=payload.score,
            comment=payload.comment,
        )
        db.add(rating)
        db.flush()
        audit(db, user, "rating.create", "rating", rating.rating_id, {"task_id": task.task_id, "score": rating.score})
        db.commit()
        db.refresh(rating)
        await app.state.event_bus.publish(
            db,
            "rating.created",
            {"rating_id": rating.rating_id, "task_id": task.task_id, "score": rating.score},
            user.user_id,
        )
        return RatingResponse(
            rating_id=rating.rating_id,
            task_id=rating.task_id,
            provider_id=rating.provider_id,
            score=rating.score,
            comment=rating.comment,
        )

    @app.get("/events", response_model=list[EventResponse])
    def events(
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("events:read")),
        after_id: int = 0,
        limit: int = 50,
    ) -> list[EventResponse]:
        rows = db.scalars(
            select(QueuedEvent)
            .where(QueuedEvent.id > after_id)
            .where((QueuedEvent.account_id == user.user_id) | (QueuedEvent.account_id.is_(None)))
            .order_by(QueuedEvent.id.asc())
            .limit(min(limit, 200))
        ).all()
        return [queued_event_response(row) for row in rows]

    @app.get("/events/stream")
    def event_stream(
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("events:read")),
        after_id: int = 0,
        poll_seconds: float = 2.0,
    ) -> StreamingResponse:
        async def stream():
            cursor = after_id
            interval = max(0.5, min(poll_seconds, 10.0))
            while True:
                rows = db.scalars(
                    select(QueuedEvent)
                    .where(QueuedEvent.id > cursor)
                    .where((QueuedEvent.account_id == user.user_id) | (QueuedEvent.account_id.is_(None)))
                    .order_by(QueuedEvent.id.asc())
                    .limit(100)
                ).all()
                for row in rows:
                    cursor = row.id
                    payload = queued_event_response(row).model_dump()
                    data = json.dumps(payload, sort_keys=True)
                    yield f"id: {row.id}\nevent: {row.event_type}\ndata: {data}\n\n"
                if not rows:
                    yield ": keepalive\n\n"
                await asyncio.sleep(interval)

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/audit", response_model=list[AuditLogResponse])
    def audit_logs(
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(scoped_user("audit:read")),
        limit: int = 100,
    ) -> list[AuditLogResponse]:
        rows = db.scalars(
            select(AuditLog)
            .where(AuditLog.actor_user_id == user.user_id)
            .order_by(AuditLog.created_at.desc())
            .limit(min(limit, 200))
        ).all()
        return [audit_log_response(row) for row in rows]

    return app


app = create_app()


def main() -> None:
    host = os.environ.get("AINET_HOST", "127.0.0.1")
    port = int(os.environ.get("AINET_PORT", "8787"))
    uvicorn.run("ainet.server.app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
