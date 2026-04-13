from __future__ import annotations

import json
import logging
from typing import Any

from redis.asyncio import Redis
from sqlalchemy.orm import Session

from .config import Settings
from .models import QueuedEvent

logger = logging.getLogger(__name__)


class EventBus:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.redis: Redis | None = Redis.from_url(settings.redis_url, decode_responses=True) if settings.redis_url else None

    async def publish(
        self,
        db: Session,
        event_type: str,
        payload: dict[str, Any],
        account_id: str | None = None,
    ) -> QueuedEvent:
        event = QueuedEvent(event_type=event_type, account_id=account_id, payload_json=json.dumps(payload, sort_keys=True))
        db.add(event)
        db.commit()
        db.refresh(event)
        if self.redis:
            try:
                await self.redis.xadd(
                    "ainet-events",
                    {
                        "event_id": event.event_id,
                        "event_type": event.event_type,
                        "account_id": event.account_id or "",
                        "payload": event.payload_json,
                    },
                )
            except Exception:
                logger.exception("failed to publish event %s to Redis stream", event.event_id)
        return event

    async def close(self) -> None:
        if self.redis:
            await self.redis.aclose()
