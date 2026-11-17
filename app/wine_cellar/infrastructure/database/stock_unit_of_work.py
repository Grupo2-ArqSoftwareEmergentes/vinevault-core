from sqlalchemy.ext.asyncio import AsyncSession

from .repositories.wine_inventory_repository import WineInventoryRepository
from .repositories.stock_movement_repository import StockMovementRepository


class StockUnitOfWork:
    def __init__(self, session: AsyncSession):
        self._session = session
        self.inventory = WineInventoryRepository(session, auto_commit=False)
        self.movements = StockMovementRepository(session)

    async def __aenter__(self):
        if not self._session.in_transaction():
            await self._session.begin()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        if exc_type is None:
            await self._session.commit()
        else:
            await self._session.rollback()
