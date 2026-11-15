from typing import List, Optional
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.wine_cellar.domain.models import WineCellar
from app.device.infrastructure.database.models.space_orm import SpaceORM
from .wine_inventory_repository import WineInventoryRepository
from ..models.wine_cellar_orm import WineCellarORM
from ..models.wine_inventory_item_orm import WineInventoryItemORM


class WineCellarRepository:
    def __init__(self, session: AsyncSession, *, auto_commit: bool = True):
        self._session = session
        self._auto_commit = auto_commit

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

    async def find_all_by_owner_user_id(self, user_id: int, space_id: UUID | None = None) -> List[WineCellar]:
        stmt = (
            select(WineCellarORM)
            .join(SpaceORM, WineCellarORM.space_id == SpaceORM.id)
            .where(SpaceORM.owner_user_id == str(user_id))
            .order_by(WineCellarORM.created_at.desc(), WineCellarORM.id)
        )
        if space_id is not None:
            stmt = stmt.where(WineCellarORM.space_id == space_id)
        result = await self._session.execute(stmt)
        return [orm.to_domain() for orm in result.scalars().all()]

    async def save(self, wine_cellar: WineCellar) -> WineCellar:
        orm = await self._session.merge(WineCellarORM.from_domain(wine_cellar))
        await self._session.flush()
        if self._auto_commit:
            await self._session.commit()
        result = await self._session.execute(select(WineCellarORM).where(WineCellarORM.id == orm.id))
        persisted = result.scalar_one()
        return persisted.to_domain()

    async def delete(self, wine_cellar_id: UUID) -> None:
        await WineInventoryRepository(self._session).delete_by_wine_cellar_id(wine_cellar_id)
        await self._session.execute(delete(WineCellarORM).where(WineCellarORM.id == wine_cellar_id))
        await self._session.commit()

    async def delete_all_by_space_id(self, space_id: UUID) -> None:
        # Delete explicitly for existing databases whose FKs may lack ON DELETE CASCADE.
        cellar_ids = select(WineCellarORM.id).where(WineCellarORM.space_id == space_id)
        await self._session.execute(
            delete(WineInventoryItemORM).where(WineInventoryItemORM.wine_cellar_id.in_(cellar_ids))
        )
        await self._session.execute(delete(WineCellarORM).where(WineCellarORM.space_id == space_id))
        if self._auto_commit:
            await self._session.commit()
