from __future__ import annotations

import asyncio
import json
import logging
import secrets
from datetime import timedelta
from datetime import datetime, timezone

import jwt
import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .database import get_db, init_db
from .emailer import send_verification_code
from .models import (
    AgentAccount,
    Artifact,
    AuditLog,
    Capability,
    Contact,
    Conversation,
    ConversationMemory,
    DeviceSession,
    EmailVerificationCode,
    HumanAccount,
    Invite,
    PaymentRecord,
    Provider,
    QueuedEvent,
    Quote,
    Rating,
    ServiceProfile,
    ServiceOrder,
    ServiceTask,
    SocialMessage,
    utc_now,
)
from .queue import EventBus
from .schemas import (
    AgentCreateRequest,
    AgentResponse,
    AuditLogResponse,
    ArtifactCreateRequest,
    ArtifactResponse,
    CapabilityInput,
    ContactCreateRequest,
    ContactResponse,
    ConversationCreateRequest,
    ConversationMemoryRequest,
    ConversationMemoryResponse,
    ConversationResponse,
    EventResponse,
    InviteAcceptRequest,
    InviteCreateRequest,
    InviteResponse,
    LoginRequest,
    MeResponse,
    MessageResponse,
    MessageRequest,
    OrderResponse,
    PaymentResponse,
    ProviderCreateRequest,
    ProviderReputationResponse,
    ProviderResponse,
    QuoteAcceptRequest,
    QuoteCreateRequest,
    QuoteResponse,
    RatingCreateRequest,
    RatingResponse,
    ServiceProfileCreateRequest,
    ServiceProfileResponse,
    SignupRequest,
    SignupResponse,
    SessionResponse,
    TaskCreateRequest,
    TaskResponse,
    TaskResultRequest,
    TokenResponse,
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

DEFAULT_SESSION_SCOPES = [
    "profile:read",
    "profile:write",
    "messages:read",
    "messages:send",
    "contacts:read",
    "contacts:write",
]
KNOWN_SESSION_SCOPES = set(DEFAULT_SESSION_SCOPES)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def dump_json(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def parse_json(value: str) -> dict:
    return json.loads(value or "{}")


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


def contact_response(contact: Contact) -> ContactResponse:
    return ContactResponse(
        contact_id=contact.contact_id,
        agent_id=contact.agent_id,
        handle=contact.handle_snapshot,
        label=contact.label,
        status=contact.status,
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


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Agent Social Enterprise Backend", version="0.1.0")
    app.state.event_bus = EventBus(settings)

    @app.on_event("startup")
    def on_startup() -> None:
        init_db()

    @app.on_event("shutdown")
    async def on_shutdown() -> None:
        await app.state.event_bus.close()

    @app.get("/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

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
        return user

    @app.post("/auth/invites", response_model=InviteResponse, status_code=status.HTTP_201_CREATED)
    async def create_invite(
        payload: InviteCreateRequest,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(current_user),
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
    def me(user: HumanAccount = Depends(current_user)) -> MeResponse:
        return MeResponse(
            user_id=user.user_id,
            email=user.email,
            username=user.username,
            email_verified=bool(user.email_verified_at),
        )

    @app.get("/account/sessions", response_model=list[SessionResponse])
    def list_sessions(
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(current_user),
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
        user: HumanAccount = Depends(current_user),
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
        user: HumanAccount = Depends(current_user),
    ) -> AgentResponse:
        existing = db.scalar(select(AgentAccount).where(AgentAccount.handle == payload.handle))
        if existing:
            raise HTTPException(status_code=409, detail="handle already exists")
        agent = AgentAccount(
            owner_user_id=user.user_id,
            handle=payload.handle,
            display_name=payload.display_name,
            runtime_type=payload.runtime_type,
        )
        db.add(agent)
        db.commit()
        db.refresh(agent)
        await app.state.event_bus.publish(db, "agent.created", {"agent_id": agent.agent_id, "handle": agent.handle}, user.user_id)
        return AgentResponse(agent_id=agent.agent_id, handle=agent.handle, runtime_type=agent.runtime_type)

    @app.post("/contacts", response_model=ContactResponse, status_code=status.HTTP_201_CREATED)
    async def create_contact(
        payload: ContactCreateRequest,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(current_user),
    ) -> ContactResponse:
        agent = db.scalar(select(AgentAccount).where(AgentAccount.handle == payload.handle))
        if not agent:
            raise HTTPException(status_code=404, detail="target handle not found")
        contact = db.scalar(
            select(Contact).where(Contact.owner_user_id == user.user_id).where(Contact.agent_id == agent.agent_id)
        )
        if contact:
            contact.label = payload.label or contact.label
            contact.status = "active"
        else:
            contact = Contact(
                owner_user_id=user.user_id,
                agent_id=agent.agent_id,
                handle_snapshot=agent.handle,
                label=payload.label,
            )
            db.add(contact)
        db.flush()
        audit(db, user, "contact.create", "contact", contact.contact_id, {"handle": agent.handle})
        db.commit()
        db.refresh(contact)
        await app.state.event_bus.publish(
            db,
            "contact.created",
            {"contact_id": contact.contact_id, "handle": contact.handle_snapshot},
            user.user_id,
        )
        return contact_response(contact)

    @app.get("/contacts", response_model=list[ContactResponse])
    def list_contacts(
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(current_user),
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

    @app.post("/conversations", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
    def create_conversation(
        payload: ConversationCreateRequest,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(current_user),
    ) -> ConversationResponse:
        target_agent = db.scalar(select(AgentAccount).where(AgentAccount.handle == payload.target_handle))
        if not target_agent:
            raise HTTPException(status_code=404, detail="target handle not found")
        conversation = get_or_create_conversation(db, user, target_agent, subject=payload.subject)
        db.commit()
        db.refresh(conversation)
        return conversation_response(conversation)

    @app.get("/conversations", response_model=list[ConversationResponse])
    def list_conversations(
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(current_user),
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
        user: HumanAccount = Depends(current_user),
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
        user: HumanAccount = Depends(current_user),
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
        user: HumanAccount = Depends(current_user),
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
        user: HumanAccount = Depends(current_user),
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
        user: HumanAccount = Depends(current_user),
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
        user: HumanAccount = Depends(current_user),
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
        user: HumanAccount = Depends(current_user),
    ) -> EventResponse:
        target_agent = db.scalar(select(AgentAccount).where(AgentAccount.handle == payload.to_handle))
        if not target_agent:
            raise HTTPException(status_code=404, detail="target handle not found")
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

    @app.post("/providers", response_model=ProviderResponse, status_code=status.HTTP_201_CREATED)
    async def create_provider(
        payload: ProviderCreateRequest,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(current_user),
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
        return ProviderResponse(
            provider_id=provider.provider_id,
            display_name=provider.display_name,
            provider_type=provider.provider_type,
            verification_status=provider.verification_status,
            agent_id=provider.agent_id,
        )

    @app.post("/service-profiles", response_model=ServiceProfileResponse, status_code=status.HTTP_201_CREATED)
    async def create_service_profile(
        payload: ServiceProfileCreateRequest,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(current_user),
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
        user: HumanAccount = Depends(current_user),
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
        _user: HumanAccount = Depends(current_user),
    ) -> dict:
        service = db.get(ServiceProfile, service_id)
        if not service or service.status != "active":
            raise HTTPException(status_code=404, detail="service profile not found")
        provider = db.get(Provider, service.provider_id)
        agent = db.get(AgentAccount, provider.agent_id) if provider and provider.agent_id else None
        capabilities = db.scalars(select(Capability).where(Capability.service_id == service.service_id)).all()
        return {
            "schema": "agent-social.agent-card.v0",
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
            "security_schemes": [{"type": "bearer", "description": "Agent Social access token"}],
        }

    @app.post("/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
    async def create_task(
        payload: TaskCreateRequest,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(current_user),
    ) -> TaskResponse:
        service = db.get(ServiceProfile, payload.service_id)
        if not service or service.status != "active":
            raise HTTPException(status_code=404, detail="service profile not found")
        if payload.capability_id:
            capability = db.get(Capability, payload.capability_id)
            if not capability or capability.service_id != service.service_id:
                raise HTTPException(status_code=404, detail="capability not found for this service")
        task = ServiceTask(
            requester_user_id=user.user_id,
            service_id=service.service_id,
            capability_id=payload.capability_id,
            provider_id=service.provider_id,
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
        user: HumanAccount = Depends(current_user),
    ) -> TaskResponse:
        task = db.get(ServiceTask, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="task not found")
        provider = db.get(Provider, task.provider_id)
        if task.requester_user_id != user.user_id and (not provider or provider.owner_user_id != user.user_id):
            raise HTTPException(status_code=403, detail="only requester or provider owner can read this task")
        return task_response(task)

    @app.post("/artifacts", response_model=ArtifactResponse, status_code=status.HTTP_201_CREATED)
    async def create_artifact(
        payload: ArtifactCreateRequest,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(current_user),
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
        user: HumanAccount = Depends(current_user),
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
        user: HumanAccount = Depends(current_user),
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
        user: HumanAccount = Depends(current_user),
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
        user: HumanAccount = Depends(current_user),
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
        _user: HumanAccount = Depends(current_user),
    ) -> ProviderReputationResponse:
        provider = db.get(Provider, provider_id)
        if not provider:
            raise HTTPException(status_code=404, detail="provider not found")
        ratings = db.scalars(select(Rating).where(Rating.provider_id == provider_id)).all()
        completed_tasks = db.scalars(
            select(ServiceTask).where(ServiceTask.provider_id == provider_id).where(ServiceTask.status == "completed")
        ).all()
        orders_count = len(db.scalars(select(ServiceOrder).where(ServiceOrder.provider_id == provider_id)).all())
        average_score = sum(rating.score for rating in ratings) / len(ratings) if ratings else None
        return ProviderReputationResponse(
            provider_id=provider_id,
            rating_count=len(ratings),
            average_score=round(average_score, 2) if average_score is not None else None,
            completed_tasks=len(completed_tasks),
            orders_count=orders_count,
        )

    @app.post("/tasks/{task_id}/result", response_model=TaskResponse)
    async def complete_task(
        task_id: str,
        payload: TaskResultRequest,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(current_user),
    ) -> TaskResponse:
        task = db.get(ServiceTask, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="task not found")
        provider = db.get(Provider, task.provider_id)
        if not provider or provider.owner_user_id != user.user_id:
            raise HTTPException(status_code=403, detail="only provider owner can submit result")
        task.status = payload.status
        task.result_json = dump_json(payload.result)
        audit(db, user, "task.result", "task", task.task_id, {"status": task.status})
        db.commit()
        db.refresh(task)
        await app.state.event_bus.publish(
            db,
            "task.completed",
            {"task_id": task.task_id, "status": task.status},
            task.requester_user_id,
        )
        return task_response(task)

    @app.post("/tasks/{task_id}/rating", response_model=RatingResponse, status_code=status.HTTP_201_CREATED)
    async def rate_task(
        task_id: str,
        payload: RatingCreateRequest,
        db: Session = Depends(get_db),
        user: HumanAccount = Depends(current_user),
    ) -> RatingResponse:
        task = db.get(ServiceTask, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="task not found")
        if task.requester_user_id != user.user_id:
            raise HTTPException(status_code=403, detail="only requester can rate this task")
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
        user: HumanAccount = Depends(current_user),
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
        user: HumanAccount = Depends(current_user),
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
        user: HumanAccount = Depends(current_user),
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
    uvicorn.run("agent_social.server.app:app", host="127.0.0.1", port=8787, reload=False)


if __name__ == "__main__":
    main()
