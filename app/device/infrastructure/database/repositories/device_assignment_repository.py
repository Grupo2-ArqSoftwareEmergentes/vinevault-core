from typing import Optional, List, Tuple
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from sqlalchemy.orm import selectinload

from ..models.device_assignment_orm import DeviceAssignmentORM
from app.device.domain.models import DeviceAssignment


class DeviceAssignmentRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def find_by_id(self, assignment_id: UUID) -> Optional[DeviceAssignment]:
        stmt = select(DeviceAssignmentORM).where(
            DeviceAssignmentORM.id == assignment_id
        ).options(selectinload(DeviceAssignmentORM.device))
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return orm.to_domain() if orm else None

    async def find_by_device_id(self, device_id: UUID) -> Optional[DeviceAssignment]:
        stmt = select(DeviceAssignmentORM).where(
            DeviceAssignmentORM.device_id == device_id
        ).options(selectinload(DeviceAssignmentORM.device))
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return orm.to_domain() if orm else None

    async def find_by_claim_token(self, claim_token: str) -> Optional[DeviceAssignment]:
        stmt = select(DeviceAssignmentORM).where(
            DeviceAssignmentORM.claim_token == claim_token
        ).options(selectinload(DeviceAssignmentORM.device))
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return orm.to_domain() if orm else None

    async def find_by_space_id(self, space_id: UUID, page: int = 0, size: int = 20) -> Tuple[List[DeviceAssignment], int]:
        offset = page * size
        count_stmt = select(func.count()).select_from(DeviceAssignmentORM).where(
            DeviceAssignmentORM.space_id == space_id
        )
        total = await self._session.scalar(count_stmt)

        stmt = select(DeviceAssignmentORM).where(
            DeviceAssignmentORM.space_id == space_id
        ).options(selectinload(DeviceAssignmentORM.device)).order_by(DeviceAssignmentORM.created_at.desc()).offset(offset).limit(size)
        result = await self._session.execute(stmt)
        orms = result.scalars().all()
        return [orm.to_domain() for orm in orms], total or 0

    async def exists_by_space_id(self, space_id: UUID) -> bool:
        stmt = select(func.count()).select_from(DeviceAssignmentORM).where(
            DeviceAssignmentORM.space_id == space_id
        )
        count = await self._session.scalar(stmt)
        return count > 0

    async def exists_by_organization_id(self, organization_id: UUID) -> bool:
        # Check if any assignment belongs to a space in the organization
        from ..models.space_orm import SpaceORM
        stmt = select(func.count()).select_from(DeviceAssignmentORM).join(
            SpaceORM, DeviceAssignmentORM.space_id == SpaceORM.id
        ).where(SpaceORM.organization_id == organization_id)
        count = await self._session.scalar(stmt)
        return count > 0

    async def exists_by_device_id_and_owner_user_id(self, device_id: UUID, user_id: int) -> bool:
        stmt = select(func.count()).select_from(DeviceAssignmentORM).where(
            and_(
                DeviceAssignmentORM.device_id == device_id,
                DeviceAssignmentORM.owner_user_id == str(user_id)
            )
        )
        count = await self._session.scalar(stmt)
        return count > 0

    async def find_device_ids_by_owner_user_id(self, user_id: int) -> List[UUID]:
        stmt = select(DeviceAssignmentORM.device_id).where(
            DeviceAssignmentORM.owner_user_id == str(user_id)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def save(self, assignment: DeviceAssignment) -> DeviceAssignment:
        orm = await self._session.merge(DeviceAssignmentORM.from_domain(assignment))
        await self._session.flush()
        await self._session.commit()
        stmt = select(DeviceAssignmentORM).where(DeviceAssignmentORM.id == orm.id).options(selectinload(DeviceAssignmentORM.device))
        result = await self._session.execute(stmt)
        persisted = result.scalar_one()
        return persisted.to_domain()

    async def delete(self, assignment: DeviceAssignment) -> None:
        stmt = select(DeviceAssignmentORM).where(DeviceAssignmentORM.id == assignment.id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return
        await self._session.delete(orm)
        await self._session.commit()
