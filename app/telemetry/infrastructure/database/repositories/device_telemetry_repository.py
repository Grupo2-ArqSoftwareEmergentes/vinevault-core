from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
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

    async def save(self, record: DeviceTelemetryRecord) -> DeviceTelemetryRecord:
        orm = await self._session.merge(DeviceTelemetryORM.from_domain(record))
        await self._session.flush()
        await self._session.commit()
        stmt = (
            select(DeviceTelemetryORM)
            .where(DeviceTelemetryORM.id == orm.id)
            .options(selectinload(DeviceTelemetryORM.device))
        )
        result = await self._session.execute(stmt)
        persisted = result.scalar_one()
        return persisted.to_domain()

