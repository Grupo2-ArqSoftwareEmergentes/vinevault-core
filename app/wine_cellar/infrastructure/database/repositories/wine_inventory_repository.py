from typing import List, Optional
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.wine_cellar.domain.models import WineInventoryItem
from ..models.wine_inventory_item_orm import WineInventoryItemORM


class WineInventoryRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def find_by_id(self, wine_inventory_item_id: UUID) -> Optional[WineInventoryItem]:
        stmt = select(WineInventoryItemORM).where(WineInventoryItemORM.id == wine_inventory_item_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return orm.to_domain() if orm else None

    async def find_all_by_wine_cellar_id(self, wine_cellar_id: UUID) -> List[WineInventoryItem]:
        stmt = (
            select(WineInventoryItemORM)
            .where(WineInventoryItemORM.wine_cellar_id == wine_cellar_id)
            .order_by(WineInventoryItemORM.created_at.desc())
        )
        result = await self._session.execute(stmt)
        orms = result.scalars().all()
        return [orm.to_domain() for orm in orms]

    async def save(self, wine_item: WineInventoryItem) -> WineInventoryItem:
        orm = await self._session.merge(WineInventoryItemORM.from_domain(wine_item))
        await self._session.flush()
        await self._session.commit()
        result = await self._session.execute(select(WineInventoryItemORM).where(WineInventoryItemORM.id == orm.id))
        persisted = result.scalar_one()
        return persisted.to_domain()

    async def delete(self, wine_inventory_item_id: UUID) -> None:
        stmt = select(WineInventoryItemORM).where(WineInventoryItemORM.id == wine_inventory_item_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return
        await self._session.delete(orm)
        await self._session.commit()

    async def delete_by_wine_cellar_id(self, wine_cellar_id: UUID) -> None:
        await self._session.execute(
            delete(WineInventoryItemORM).where(WineInventoryItemORM.wine_cellar_id == wine_cellar_id)
        )
        await self._session.commit()
