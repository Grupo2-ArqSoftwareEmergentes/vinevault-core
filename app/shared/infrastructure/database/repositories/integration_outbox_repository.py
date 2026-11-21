from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.integration_outbox_orm import IntegrationOutboxORM


class IntegrationOutboxRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def enqueue_event(
        self,
        *,
        topic: str,
        message_key: str | None,
        event_type: str,
        payload: dict[str, Any],
        aggregate_type: str | None = None,
        aggregate_id: str | None = None,
    ) -> UUID:
        orm = IntegrationOutboxORM(
            topic=topic,
            message_key=message_key,
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload=payload,
            attempts=0,
            last_error=None,
            published_at=None,
        )
        merged = await self._session.merge(orm)
        await self._session.flush()
        await self._session.commit()
        return merged.id

    async def fetch_pending(self, limit: int = 20) -> list[IntegrationOutboxORM]:
        stmt = (
            select(IntegrationOutboxORM)
            .where(IntegrationOutboxORM.published_at.is_(None))
            .order_by(IntegrationOutboxORM.created_at.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def mark_published(self, event_id: UUID, published_at: datetime | None = None) -> None:
        stmt = select(IntegrationOutboxORM).where(IntegrationOutboxORM.id == event_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return
        orm.published_at = published_at or datetime.utcnow()
        orm.last_error = None
        await self._session.commit()

    async def mark_failed(self, event_id: UUID, error: str) -> None:
        stmt = select(IntegrationOutboxORM).where(IntegrationOutboxORM.id == event_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return
        orm.attempts += 1
        orm.last_error = error
        await self._session.commit()
