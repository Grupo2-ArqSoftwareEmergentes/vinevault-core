from typing import Optional, List
from uuid import UUID

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.device.domain.models import Space
from ..models.space_orm import SpaceORM


class SpaceRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def find_by_id(self, space_id: UUID) -> Optional[Space]:
        stmt = select(SpaceORM).where(SpaceORM.id == space_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return orm.to_domain() if orm else None

    async def find_all_by_organization_id(self, organization_id: UUID) -> List[Space]:
        stmt = select(SpaceORM).where(SpaceORM.organization_id == organization_id).order_by(SpaceORM.created_at.desc())
        result = await self._session.execute(stmt)
        orms = result.scalars().all()
        return [orm.to_domain() for orm in orms]

    async def save(self, space: Space) -> Space:
        orm = await self._session.merge(SpaceORM.from_domain(space))
        await self._session.flush()
        await self._session.commit()
        result = await self._session.execute(select(SpaceORM).where(SpaceORM.id == orm.id))
        persisted = result.scalar_one()
        return persisted.to_domain()

    async def delete(self, space_id: UUID) -> None:
        await self._session.execute(delete(SpaceORM).where(SpaceORM.id == space_id))
        await self._session.commit()
