from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.wine_cellar.domain.models.stock_movement import StockMovement
from ..models.stock_movement_orm import StockMovementORM
from ..models.wine_inventory_item_orm import WineInventoryItemORM


class StockMovementRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def save(self, movement: StockMovement) -> StockMovement:
        values = movement.model_dump(exclude={"created_at"})
        orm = StockMovementORM(**values)
        self._session.add(orm)
        await self._session.flush()
        return orm.to_domain()

    async def list_for_item(self, cellar_id: UUID, item_id: UUID, limit: int = 100) -> list[StockMovement]:
        result = await self._session.execute(select(StockMovementORM).join(
            WineInventoryItemORM, WineInventoryItemORM.id == StockMovementORM.inventory_item_id,
        ).where(
            StockMovementORM.inventory_item_id == item_id,
            WineInventoryItemORM.wine_cellar_id == cellar_id,
        ).order_by(StockMovementORM.created_at.desc(), StockMovementORM.id).limit(limit))
        return [orm.to_domain() for orm in result.scalars()]
