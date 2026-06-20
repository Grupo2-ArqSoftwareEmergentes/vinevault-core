from typing import Optional, List
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.device.domain.models import DeviceCommand
from ..models.device_command_orm import DeviceCommandORM


class DeviceCommandRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def find_by_id(self, command_id: UUID) -> Optional[DeviceCommand]:
        stmt = select(DeviceCommandORM).where(DeviceCommandORM.id == command_id).options(selectinload(DeviceCommandORM.device))
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return orm.to_domain() if orm else None

    async def find_all_by_device_id(self, device_id: UUID) -> List[DeviceCommand]:
        stmt = select(DeviceCommandORM).where(DeviceCommandORM.device_id == device_id).options(selectinload(DeviceCommandORM.device)).order_by(DeviceCommandORM.created_at.desc())
        result = await self._session.execute(stmt)
        orms = result.scalars().all()
        return [orm.to_domain() for orm in orms]

    async def save(self, command: DeviceCommand) -> DeviceCommand:
        orm = await self._session.merge(DeviceCommandORM.from_domain(command))
        await self._session.flush()
        await self._session.commit()
        stmt = select(DeviceCommandORM).where(DeviceCommandORM.id == orm.id).options(selectinload(DeviceCommandORM.device))
        result = await self._session.execute(stmt)
        persisted = result.scalar_one()
        return persisted.to_domain()
