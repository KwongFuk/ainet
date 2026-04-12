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
from .models import AgentAccount, DeviceSession, EmailVerificationCode, HumanAccount, QueuedEvent, utc_now
from .queue import EventBus
from .schemas import (
    AgentCreateRequest,
    AgentResponse,
    EventResponse,
    LoginRequest,
    MeResponse,
    MessageRequest,
    SignupRequest,
    SignupResponse,
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
        event = await app.state.event_bus.publish(
            db,
            "message.queued",
            {"from_user_id": user.user_id, "to_handle": payload.to_handle, "body": payload.body},
            user.user_id,
        )
        return EventResponse(
            event_id=event.event_id,
            event_type=event.event_type,
            account_id=event.account_id,
            payload=json.loads(event.payload_json),
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
