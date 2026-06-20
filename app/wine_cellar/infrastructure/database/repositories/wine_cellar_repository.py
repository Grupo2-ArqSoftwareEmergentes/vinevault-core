from typing import List, Optional
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.wine_cellar.domain.models import WineCellar
from ..models.wine_cellar_orm import WineCellarORM


class WineCellarRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def find_by_id(self, wine_cellar_id: UUID) -> Optional[WineCellar]:
        stmt = select(WineCellarORM).where(WineCellarORM.id == wine_cellar_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return orm.to_domain() if orm else None

    async def find_by_device_id(self, device_id: UUID) -> Optional[WineCellar]:
        stmt = select(WineCellarORM).where(WineCellarORM.device_id == device_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return orm.to_domain() if orm else None

    async def find_all_by_space_id(self, space_id: UUID) -> List[WineCellar]:
        stmt = select(WineCellarORM).where(WineCellarORM.space_id == space_id).order_by(WineCellarORM.created_at.desc())
        result = await self._session.execute(stmt)
        orms = result.scalars().all()
        return [orm.to_domain() for orm in orms]

    async def save(self, wine_cellar: WineCellar) -> WineCellar:
        orm = await self._session.merge(WineCellarORM.from_domain(wine_cellar))
        await self._session.flush()
        await self._session.commit()
        result = await self._session.execute(select(WineCellarORM).where(WineCellarORM.id == orm.id))
        persisted = result.scalar_one()
        return persisted.to_domain()

    async def delete(self, wine_cellar_id: UUID) -> None:
        await self._session.execute(delete(WineCellarORM).where(WineCellarORM.id == wine_cellar_id))
        await self._session.commit()

