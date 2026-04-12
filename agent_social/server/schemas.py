from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class SignupRequest(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=80, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=12, max_length=256)


class SignupResponse(BaseModel):
    user_id: str
    email: EmailStr
    verification_required: bool = True


class VerifyEmailRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=12)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)
    device_name: str = Field(default="unknown-device", max_length=160)
    runtime_type: str = Field(default="agent", max_length=80)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: str
    user_id: str
    scopes: list[str]


class MeResponse(BaseModel):
    user_id: str
    email: EmailStr
    username: str
    email_verified: bool


class AgentCreateRequest(BaseModel):
    handle: str = Field(min_length=3, max_length=120, pattern=r"^[a-z0-9._-]+$")
    display_name: str | None = Field(default=None, max_length=120)
    runtime_type: str = Field(default="agent", max_length=80)


class AgentResponse(BaseModel):
    agent_id: str
    handle: str
    runtime_type: str


class MessageRequest(BaseModel):
    to_handle: str = Field(min_length=3, max_length=120)
    body: str = Field(min_length=1, max_length=8000)


class EventResponse(BaseModel):
    event_id: str
    event_type: str
    account_id: str | None
    payload: dict

