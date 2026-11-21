from typing import List, Optional
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.device.domain.models import AlertIncident
from ..models.alert_incident_orm import AlertIncidentORM
from ..models.device_assignment_orm import DeviceAssignmentORM


class AlertIncidentRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def find_by_id(self, incident_id: UUID) -> Optional[AlertIncident]:
        stmt = (
            select(AlertIncidentORM)
            .where(AlertIncidentORM.id == incident_id)
            .options(selectinload(AlertIncidentORM.device))
        )
        result = await self._session.execute(stmt)
        orm = result.scalars().first()
        return orm.to_domain() if orm else None

    async def find_active_by_device_id_and_threshold_metric(
        self,
        device_id: UUID,
        threshold_metric: str,
        *,
        assignment_id: UUID,
        space_id: UUID | None,
    ) -> Optional[AlertIncident]:
        stmt = (
            select(AlertIncidentORM)
            .where(
                and_(
                    AlertIncidentORM.device_id == device_id,
                    AlertIncidentORM.threshold_metric == threshold_metric,
                    AlertIncidentORM.assignment_id == assignment_id,
                    AlertIncidentORM.space_id == space_id,
                    AlertIncidentORM.status != "RESOLVED",
                )
            )
            .order_by(AlertIncidentORM.occurred_at.desc())
            .options(selectinload(AlertIncidentORM.device))
        )
        result = await self._session.execute(stmt)
        orm = result.scalars().first()
        return orm.to_domain() if orm else None

    async def find_by_space_id(self, space_id: UUID, *, active_only: bool = False) -> List[AlertIncident]:
        # Never adopt incidents from an earlier assignment of the same hardware.
        stmt = select(AlertIncidentORM).join(DeviceAssignmentORM, and_(
            DeviceAssignmentORM.device_id == AlertIncidentORM.device_id,
            DeviceAssignmentORM.id == AlertIncidentORM.assignment_id,
            DeviceAssignmentORM.space_id == AlertIncidentORM.space_id,
        )).where(AlertIncidentORM.space_id == space_id)
        if active_only:
            stmt = stmt.where(AlertIncidentORM.status == "ACTIVE")
        result = await self._session.execute(stmt.options(selectinload(AlertIncidentORM.device)).order_by(
            AlertIncidentORM.occurred_at.desc(), AlertIncidentORM.id.desc()))
        return [orm.to_domain() for orm in result.scalars().all()]

    async def find_all_by_device_id(self, device_id: UUID) -> List[AlertIncident]:
        stmt = (
            select(AlertIncidentORM)
            .where(AlertIncidentORM.device_id == device_id)
            .options(selectinload(AlertIncidentORM.device))
            .order_by(AlertIncidentORM.occurred_at.desc())
        )
        result = await self._session.execute(stmt)
        return [orm.to_domain() for orm in result.scalars().all()]

    async def find_active_by_device_id(self, device_id: UUID) -> List[AlertIncident]:
        stmt = (
            select(AlertIncidentORM)
            .where(
                and_(
                    AlertIncidentORM.device_id == device_id,
                    AlertIncidentORM.status != "RESOLVED",
                )
            )
            .options(selectinload(AlertIncidentORM.device))
            .order_by(AlertIncidentORM.occurred_at.desc())
        )
        result = await self._session.execute(stmt)
        return [orm.to_domain() for orm in result.scalars().all()]

    async def find_all_active(self) -> List[AlertIncident]:
        stmt = (
            select(AlertIncidentORM)
            .where(AlertIncidentORM.status != "RESOLVED")
            .options(selectinload(AlertIncidentORM.device))
            .order_by(AlertIncidentORM.occurred_at.desc())
        )
        result = await self._session.execute(stmt)
        return [orm.to_domain() for orm in result.scalars().all()]

    async def save(self, incident: AlertIncident) -> AlertIncident:
        orm = await self._session.merge(AlertIncidentORM.from_domain(incident))
        await self._session.flush()
        await self._session.commit()
        stmt = (
            select(AlertIncidentORM)
            .where(AlertIncidentORM.id == orm.id)
            .options(selectinload(AlertIncidentORM.device))
        )
        result = await self._session.execute(stmt)
        persisted = result.scalar_one()
        return persisted.to_domain()
