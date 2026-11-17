from typing import List, Optional
from uuid import UUID

from sqlalchemy import delete, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.wine_cellar.domain.models import WineInventoryItem
from app.wine_cellar.domain.models.inventory_snapshot import (
    InventorySnapshot, InventoryItemSummary, InventoryCategorySummary,
)
from ..models.wine_inventory_item_orm import WineInventoryItemORM


class WineInventoryRepository:
    def __init__(self, session: AsyncSession, *, auto_commit: bool = True):
        self._session = session
        self._auto_commit = auto_commit

    async def get_analysis_snapshot(self, wine_cellar_id: UUID) -> InventorySnapshot:
        """Bounded projection: never load a large cellar into an LLM prompt or ORM list."""
        item = WineInventoryItemORM
        scope = item.wine_cellar_id == wine_cellar_id
        result = await self._session.execute(select(
            func.count(item.id), func.coalesce(func.sum(item.quantity), 0),
            func.min(item.age_years), func.max(item.age_years),
        ).where(scope))
        count, quantity, min_age, max_age = result.one()
        snapshot = InventorySnapshot(
            item_count=count, total_quantity=quantity, min_age_years=min_age, max_age_years=max_age,
        )
        if count == 0:
            return snapshot
        if count <= 40:
            result = await self._session.execute(select(
                item.wine_name.label("wine_name"), item.wine_type, item.age_years, item.quantity, item.vintage,
            ).where(scope).order_by(item.id).limit(40))
            snapshot.inventory = [InventoryItemSummary(**dict(row._mapping)) for row in result]
        else:
            result = await self._session.execute(select(
                item.wine_type, func.count(item.id).label("items"),
                func.sum(item.quantity).label("quantity"),
            ).where(scope).group_by(item.wine_type).order_by(
                func.sum(item.quantity).desc(), item.wine_type,
            ).limit(12))
            snapshot.categories = [InventoryCategorySummary(**dict(row._mapping)) for row in result]
            snapshot.other_items = count - sum(category.items for category in snapshot.categories)
            snapshot.other_quantity = quantity - sum(category.quantity for category in snapshot.categories)
        return snapshot

    async def find_by_id(
        self, wine_inventory_item_id: UUID, *, for_update: bool = False, wine_cellar_id: UUID | None = None,
    ) -> Optional[WineInventoryItem]:
        stmt = select(WineInventoryItemORM).where(WineInventoryItemORM.id == wine_inventory_item_id)
        if wine_cellar_id is not None:
            stmt = stmt.where(WineInventoryItemORM.wine_cellar_id == wine_cellar_id)
        if for_update:
            stmt = stmt.with_for_update()
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
        if self._auto_commit:
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
