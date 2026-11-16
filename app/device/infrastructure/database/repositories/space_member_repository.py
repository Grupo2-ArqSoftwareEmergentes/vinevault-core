from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.device.domain.models.value_objects.space_access import SpaceRole
from ..models.space_member_orm import SpaceMemberORM


class SpaceMemberRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def role_for(self, space_id: UUID, user_id: int) -> SpaceRole | None:
        return await self._session.scalar(select(SpaceMemberORM.role).where(
            SpaceMemberORM.space_id == space_id, SpaceMemberORM.user_id == user_id,
        ))

    async def add_owner(self, space_id: UUID, user_id: int) -> None:
        self._session.add(SpaceMemberORM(space_id=space_id, user_id=user_id, role=SpaceRole.OWNER))
        await self._session.flush()
