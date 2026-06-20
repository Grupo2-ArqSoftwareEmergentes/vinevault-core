from typing import Optional, List
from uuid import UUID

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.device.domain.models import Organization
from ..models.organization_orm import OrganizationORM


class OrganizationRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def find_by_id(self, organization_id: UUID) -> Optional[Organization]:
        stmt = select(OrganizationORM).where(OrganizationORM.id == organization_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return orm.to_domain() if orm else None

    async def find_all_by_owner_user_id(self, user_id: int) -> List[Organization]:
        stmt = select(OrganizationORM).where(OrganizationORM.owner_user_id == str(user_id)).order_by(OrganizationORM.created_at.desc())
        result = await self._session.execute(stmt)
        orms = result.scalars().all()
        return [orm.to_domain() for orm in orms]

    async def save(self, organization: Organization) -> Organization:
        orm = await self._session.merge(OrganizationORM.from_domain(organization))
        await self._session.flush()
        await self._session.commit()
        result = await self._session.execute(select(OrganizationORM).where(OrganizationORM.id == orm.id))
        persisted = result.scalar_one()
        return persisted.to_domain()

    async def delete(self, organization_id: UUID) -> None:
        await self._session.execute(delete(OrganizationORM).where(OrganizationORM.id == organization_id))
        await self._session.commit()
