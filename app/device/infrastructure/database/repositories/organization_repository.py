from typing import Optional, List
from uuid import UUID

from sqlalchemy import select, delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.device.domain.models import Organization
from app.device.domain.models.value_objects import UserId
from ..models.organization_orm import OrganizationORM


class OrganizationRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def lock_space_creation(self, user_id: int) -> None:
        # Both space-creation routes hold this lock until the unit of work ends.
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(74102, :user_id)"), {"user_id": user_id}
        )

    async def resolve_personal_organization(self, user_id: int) -> Organization:
        # Caller holds lock_space_creation and owns the transaction.
        result = await self._session.execute(
            select(OrganizationORM)
            .where(OrganizationORM.owner_user_id == str(user_id))
            .order_by(OrganizationORM.created_at.asc().nulls_last(), OrganizationORM.id)
            .limit(1)
        )
        orm = result.scalar_one_or_none()
        if orm is None:
            organization = Organization(
                name="Organización Personal", owner_user_id=UserId(user_id=user_id)
            )
            orm = OrganizationORM.from_domain(organization)
            self._session.add(orm)
            await self._session.flush()
        return orm.to_domain()

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
