from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENT_SOCIAL_", env_file=".env", extra="ignore")

    environment: str = "development"
    database_url: str = "sqlite:///./agent_social.db"
    jwt_secret: str = Field(default="dev-change-me", min_length=12)
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60
    email_code_minutes: int = 10
    redis_url: str | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "no-reply@agent-social.local"
    smtp_starttls: bool = True
    log_email_codes: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()

