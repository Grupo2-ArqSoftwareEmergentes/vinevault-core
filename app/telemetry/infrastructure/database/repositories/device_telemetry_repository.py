from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, func
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.telemetry.domain.models import DeviceTelemetryRecord
from ..models.device_telemetry_orm import DeviceTelemetryORM


class TelemetryRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def find_by_id(self, telemetry_id: UUID) -> Optional[DeviceTelemetryRecord]:
        stmt = (
            select(DeviceTelemetryORM)
            .where(DeviceTelemetryORM.id == telemetry_id)
            .options(selectinload(DeviceTelemetryORM.device))
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return orm.to_domain() if orm else None

    async def find_all_by_device_id(self, device_id: UUID) -> List[DeviceTelemetryRecord]:
        stmt = (
            select(DeviceTelemetryORM)
            .where(DeviceTelemetryORM.device_id == device_id)
            .options(selectinload(DeviceTelemetryORM.device))
            .order_by(DeviceTelemetryORM.occurred_at.desc())
        )
        result = await self._session.execute(stmt)
        return [orm.to_domain() for orm in result.scalars().all()]

    async def latest_activity(self, assignment_ids: list[UUID]) -> dict[UUID, datetime]:
        if not assignment_ids:
            return {}
        # Batch lookup for legacy records ingested before last_seen was maintained.
        stmt = select(DeviceTelemetryORM.assignment_id, func.max(DeviceTelemetryORM.occurred_at)).where(
            DeviceTelemetryORM.assignment_id.in_(assignment_ids),
            DeviceTelemetryORM.occurred_at <= datetime.now(timezone.utc).replace(tzinfo=None),
        ).group_by(DeviceTelemetryORM.assignment_id)
        return dict((await self._session.execute(stmt)).all())

    async def commit(self) -> None:
        await self._session.commit()

    async def save(self, record: DeviceTelemetryRecord, *, auto_commit: bool = True) -> DeviceTelemetryRecord:
        orm = await self._session.merge(DeviceTelemetryORM.from_domain(record))
        await self._session.flush()
        if auto_commit:
            await self._session.commit()
        stmt = (
            select(DeviceTelemetryORM)
            .where(DeviceTelemetryORM.id == orm.id)
            .options(selectinload(DeviceTelemetryORM.device))
        )
        result = await self._session.execute(stmt)
        persisted = result.scalar_one()
        return persisted.to_domain()

