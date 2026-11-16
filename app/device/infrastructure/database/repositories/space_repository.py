from typing import Optional, List
from uuid import UUID

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.device.domain.models import Space
from app.device.domain.models.value_objects.space_access import SpaceRole
from ..models.space_orm import SpaceORM
from ..models.space_member_orm import SpaceMemberORM


class SpaceRepository:
    def __init__(self, session: AsyncSession, *, auto_commit: bool = True):
        self._session = session
        self._auto_commit = auto_commit

    async def find_by_id(self, space_id: UUID, *, for_update: bool = False) -> Optional[Space]:
        stmt = select(SpaceORM).where(SpaceORM.id == space_id)
        if for_update:
            stmt = stmt.with_for_update()
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return orm.to_domain() if orm else None

    async def find_all_by_organization_id(self, organization_id: UUID) -> List[Space]:
        stmt = select(SpaceORM).where(SpaceORM.organization_id == organization_id).order_by(SpaceORM.created_at.desc())
        result = await self._session.execute(stmt)
        orms = result.scalars().all()
        return [orm.to_domain() for orm in orms]

    async def find_all_by_owner_user_id(self, user_id: int) -> List[Space]:
        # Legacy method name retained for callers; visibility is membership-based.
        stmt = select(SpaceORM).join(SpaceMemberORM, SpaceMemberORM.space_id == SpaceORM.id).where(SpaceMemberORM.user_id == user_id).order_by(SpaceORM.created_at.desc())
        result = await self._session.execute(stmt)
        orms = result.scalars().all()
        return [orm.to_domain() for orm in orms]

    async def find_all_with_membership(self, user_id: int) -> list[tuple[Space, SpaceRole]]:
        result = await self._session.execute(select(SpaceORM, SpaceMemberORM.role).join(
            SpaceMemberORM, SpaceMemberORM.space_id == SpaceORM.id,
        ).where(SpaceMemberORM.user_id == user_id).order_by(SpaceORM.created_at.desc(), SpaceORM.id))
        return [(space.to_domain(), role) for space, role in result]

    async def save(self, space: Space) -> Space:
        orm = await self._session.merge(SpaceORM.from_domain(space))
        await self._session.flush()
        if self._auto_commit:
            await self._session.commit()
        result = await self._session.execute(select(SpaceORM).where(SpaceORM.id == orm.id))
        persisted = result.scalar_one()
        return persisted.to_domain()

    async def delete(self, space_id: UUID) -> None:
        await self._session.execute(delete(SpaceORM).where(SpaceORM.id == space_id))
        if self._auto_commit:
            await self._session.commit()
