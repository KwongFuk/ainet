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
    from_agent_id: str | None = Field(default=None, max_length=40)
    conversation_id: str | None = Field(default=None, max_length=40)
    message_type: str = Field(default="text", max_length=40)


class EventResponse(BaseModel):
    cursor_id: int | None = None
    event_id: str
    event_type: str
    account_id: str | None
    payload: dict


class ContactCreateRequest(BaseModel):
    handle: str = Field(min_length=3, max_length=120)
    label: str | None = Field(default=None, max_length=160)


class ContactResponse(BaseModel):
    contact_id: str
    agent_id: str
    handle: str
    label: str | None
    status: str
    created_at: str


class ConversationCreateRequest(BaseModel):
    target_handle: str = Field(min_length=3, max_length=120)
    subject: str | None = Field(default=None, max_length=200)


class ConversationResponse(BaseModel):
    conversation_id: str
    target_agent_id: str
    target_handle: str
    conversation_type: str
    subject: str | None
    last_message_at: str | None
    created_at: str


class MessageResponse(BaseModel):
    message_id: str
    conversation_id: str
    from_handle: str
    to_handle: str
    message_type: str
    body: str
    metadata: dict
    created_at: str


class CapabilityInput(BaseModel):
    name: str = Field(min_length=2, max_length=120, pattern=r"^[a-z0-9_.:-]+$")
    description: str = Field(default="", max_length=2000)
    input_schema: dict = Field(default_factory=dict)
    output_schema: dict = Field(default_factory=dict)


class ProviderCreateRequest(BaseModel):
    display_name: str = Field(min_length=2, max_length=160)
    provider_type: str = Field(default="agent", max_length=40)
    agent_id: str | None = Field(default=None, max_length=40)
    website: str | None = Field(default=None, max_length=500)


class ProviderResponse(BaseModel):
    provider_id: str
    display_name: str
    provider_type: str
    verification_status: str
    agent_id: str | None


class ServiceProfileCreateRequest(BaseModel):
    provider_id: str = Field(max_length=40)
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(default="", max_length=8000)
    category: str = Field(default="general", max_length=80)
    pricing_model: str = Field(default="quote", max_length=60)
    currency: str = Field(default="credits", max_length=12)
    base_price_cents: int | None = Field(default=None, ge=0)
    input_schema: dict = Field(default_factory=dict)
    output_schema: dict = Field(default_factory=dict)
    sla: dict = Field(default_factory=dict)
    capabilities: list[CapabilityInput] = Field(default_factory=list)


class ServiceProfileResponse(BaseModel):
    service_id: str
    provider_id: str
    title: str
    description: str
    category: str
    pricing_model: str
    currency: str
    base_price_cents: int | None
    status: str
    capabilities: list[CapabilityInput] = Field(default_factory=list)


class TaskCreateRequest(BaseModel):
    service_id: str = Field(max_length=40)
    capability_id: str | None = Field(default=None, max_length=40)
    input: dict = Field(default_factory=dict)


class TaskResponse(BaseModel):
    task_id: str
    service_id: str
    provider_id: str
    capability_id: str | None
    status: str
    input: dict
    result: dict


class ArtifactCreateRequest(BaseModel):
    task_id: str | None = Field(default=None, max_length=40)
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(default="application/octet-stream", max_length=120)
    size_bytes: int = Field(default=0, ge=0)
    sha256: str | None = Field(default=None, min_length=64, max_length=64)
    storage_url: str | None = Field(default=None, max_length=1000)


class ArtifactResponse(BaseModel):
    artifact_id: str
    task_id: str | None
    filename: str
    content_type: str
    size_bytes: int
    sha256: str | None
    storage_url: str | None


class QuoteCreateRequest(BaseModel):
    amount_cents: int = Field(ge=0)
    currency: str = Field(default="credits", max_length=12)
    terms: dict = Field(default_factory=dict)


class QuoteResponse(BaseModel):
    quote_id: str
    task_id: str
    provider_id: str
    amount_cents: int
    currency: str
    status: str
    terms: dict


class QuoteAcceptRequest(BaseModel):
    settlement_mode: str = Field(default="internal_credits", max_length=80)


class PaymentResponse(BaseModel):
    payment_id: str
    order_id: str
    amount_cents: int
    currency: str
    status: str
    provider_reference: str | None
    created_at: str


class OrderResponse(BaseModel):
    order_id: str
    task_id: str
    quote_id: str | None
    buyer_user_id: str
    provider_id: str
    status: str
    created_at: str
    payment: PaymentResponse | None = None


class TaskResultRequest(BaseModel):
    status: str = Field(default="completed", max_length=40)
    result: dict = Field(default_factory=dict)


class RatingCreateRequest(BaseModel):
    score: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=4000)


class RatingResponse(BaseModel):
    rating_id: str
    task_id: str
    provider_id: str
    score: int
    comment: str


class ProviderReputationResponse(BaseModel):
    provider_id: str
    rating_count: int
    average_score: float | None
    completed_tasks: int
    orders_count: int
