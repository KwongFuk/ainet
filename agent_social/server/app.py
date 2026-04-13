from __future__ import annotations

import json
import logging
from datetime import timedelta
from datetime import datetime, timezone

import jwt
import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, status
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
    DeviceSession,
    EmailVerificationCode,
    HumanAccount,
    Provider,
    QueuedEvent,
    Quote,
    Rating,
    ServiceProfile,
    ServiceTask,
    utc_now,
)
from .queue import EventBus
from .schemas import (
    AgentCreateRequest,
    AgentResponse,
    ArtifactCreateRequest,
    ArtifactResponse,
    CapabilityInput,
    EventResponse,
    LoginRequest,
    MeResponse,
    MessageRequest,
    ProviderCreateRequest,
    ProviderResponse,
    QuoteCreateRequest,
    QuoteResponse,
    RatingCreateRequest,
    RatingResponse,
    ServiceProfileCreateRequest,
    ServiceProfileResponse,
    SignupRequest,
    SignupResponse,
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


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def dump_json(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def parse_json(value: str) -> dict:
    return json.loads(value or "{}")


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

        session_placeholder = "pending"
        scopes = ["profile:read", "profile:write", "messages:read", "messages:send", "contacts:read", "contacts:write"]
        session = DeviceSession(
            user_id=user.user_id,
            device_name=payload.device_name,
            runtime_type=payload.runtime_type,
            access_token_hash=session_placeholder,
            scopes=" ".join(scopes),
            expires_at=utc_now() + timedelta(minutes=settings.access_token_minutes),
        )
        db.add(session)
        db.flush()
        token, expires_at = create_access_token(settings, user.user_id, session.session_id, scopes)
        session.access_token_hash = hash_secret(token)
        session.expires_at = expires_at
        db.commit()
        await app.state.event_bus.publish(db, "auth.login", {"user_id": user.user_id, "session_id": session.session_id}, user.user_id)
        return TokenResponse(access_token=token, expires_at=expires_at.isoformat(), user_id=user.user_id, scopes=scopes)

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
        user = db.get(HumanAccount, claims.get("sub"))
        if not user or user.disabled:
            raise HTTPException(status_code=401, detail="account disabled or missing")
        return user

    @app.get("/account/me", response_model=MeResponse)
    def me(user: HumanAccount = Depends(current_user)) -> MeResponse:
        return MeResponse(
            user_id=user.user_id,
            email=user.email,
            username=user.username,
            email_verified=bool(user.email_verified_at),
        )

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
        event = await app.state.event_bus.publish(
            db,
            "message.queued",
            {
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
            pattern = f"%{query.lower()}%"
            stmt = stmt.where(ServiceProfile.title.ilike(pattern) | ServiceProfile.description.ilike(pattern))
        if capability:
            stmt = stmt.join(Capability, Capability.service_id == ServiceProfile.service_id).where(Capability.name == capability)
        services = db.scalars(stmt.limit(min(limit, 100))).all()
        return [service_profile_response(db, service) for service in services]

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
        if payload.task_id and not db.get(ServiceTask, payload.task_id):
            raise HTTPException(status_code=404, detail="task not found")
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
        return [
            EventResponse(
                cursor_id=row.id,
                event_id=row.event_id,
                event_type=row.event_type,
                account_id=row.account_id,
                payload=json.loads(row.payload_json),
            )
            for row in rows
        ]

    return app


app = create_app()


def main() -> None:
    uvicorn.run("agent_social.server.app:app", host="127.0.0.1", port=8787, reload=False)


if __name__ == "__main__":
    main()
