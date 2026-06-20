from typing import Optional, List
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_

from ..models.device_orm import DeviceORM
from app.device.domain.models import Device


class DeviceRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def find_by_id(self, device_id: UUID) -> Optional[Device]:
        stmt = select(DeviceORM).where(DeviceORM.id == device_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return orm.to_domain() if orm else None

    async def find_by_hardware_id(self, hardware_id: str) -> Optional[Device]:
        stmt = select(DeviceORM).where(DeviceORM.hardware_id == hardware_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return orm.to_domain() if orm else None

    async def find_by_api_key(self, api_key: str) -> Optional[Device]:
        stmt = select(DeviceORM).where(DeviceORM.api_key == api_key)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return orm.to_domain() if orm else None

    async def find_by_serial_number(self, serial_number: str) -> Optional[Device]:
        stmt = select(DeviceORM).where(DeviceORM.serial_number == serial_number)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return orm.to_domain() if orm else None

    async def find_all_by_serial_numbers(self, serial_numbers: List[str]) -> List[Device]:
        stmt = select(DeviceORM).where(DeviceORM.serial_number.in_(serial_numbers))
        result = await self._session.execute(stmt)
        orms = result.scalars().all()
        return [orm.to_domain() for orm in orms]

    async def exists_by_hardware_id(self, hardware_id: str) -> bool:
        stmt = select(DeviceORM).where(DeviceORM.hardware_id == hardware_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def save(self, device: Device) -> Device:
        orm = await self._session.merge(DeviceORM.from_domain(device))
        await self._session.flush()
        await self._session.commit()
        result = await self._session.execute(select(DeviceORM).where(DeviceORM.id == orm.id))
        persisted = result.scalar_one()
        return persisted.to_domain()

    async def save_all(self, devices: List[Device]) -> List[Device]:
        orms = [await self._session.merge(DeviceORM.from_domain(d)) for d in devices]
        await self._session.flush()
        await self._session.commit()
        result = await self._session.execute(select(DeviceORM).where(DeviceORM.id.in_([orm.id for orm in orms])))
        persisted = result.scalars().all()
        return [orm.to_domain() for orm in persisted]
