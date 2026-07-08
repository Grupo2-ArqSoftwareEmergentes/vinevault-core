from typing import Optional, List
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..models.edge_device_orm import EdgeDeviceORM
from app.device.domain.models import EdgeDevice


class EdgeDeviceRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def find_by_id(self, edge_device_id: UUID) -> Optional[EdgeDevice]:
        stmt = select(EdgeDeviceORM).where(EdgeDeviceORM.id == edge_device_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return orm.to_domain() if orm else None

    async def find_by_name(self, name: str) -> Optional[EdgeDevice]:
        stmt = select(EdgeDeviceORM).where(EdgeDeviceORM.name == name)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return orm.to_domain() if orm else None

    async def find_by_api_key(self, api_key: str) -> Optional[EdgeDevice]:
        stmt = select(EdgeDeviceORM).where(EdgeDeviceORM.api_key == api_key)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return orm.to_domain() if orm else None

    async def find_all(self) -> List[EdgeDevice]:
        stmt = select(EdgeDeviceORM).order_by(EdgeDeviceORM.created_at.asc())
        result = await self._session.execute(stmt)
        orms = result.scalars().all()
        return [orm.to_domain() for orm in orms]

    async def save(self, edge_device: EdgeDevice) -> EdgeDevice:
        orm = await self._session.merge(EdgeDeviceORM.from_domain(edge_device))
        await self._session.flush()
        await self._session.commit()
        result = await self._session.execute(select(EdgeDeviceORM).where(EdgeDeviceORM.id == orm.id))
        persisted = result.scalar_one()
        return persisted.to_domain()

    async def delete(self, edge_device: EdgeDevice) -> None:
        stmt = select(EdgeDeviceORM).where(EdgeDeviceORM.id == edge_device.id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return
        await self._session.delete(orm)
        await self._session.commit()
