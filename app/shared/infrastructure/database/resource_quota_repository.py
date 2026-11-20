from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.iam.models import User
from app.device.infrastructure.database.models.space_orm import SpaceORM
from app.device.infrastructure.database.models.space_member_orm import SpaceMemberORM
from app.device.domain.models.value_objects.space_access import SpaceRole
from app.wine_cellar.infrastructure.database.models.wine_cellar_orm import WineCellarORM
from app.wine_cellar.infrastructure.database.models.wine_inventory_item_orm import WineInventoryItemORM
from app.shared.quota_policy import InventoryUsage, QuotaExceededError, QuotaResourceNotFoundError, can_create_space, cellar_limit
from app.subscriptions.domain.catalog import account_space_limit
from app.subscriptions.infrastructure.database.entitlements import effective_tier, effective_tiers
from app.subscriptions.infrastructure.database.models import ActiveSubscriptionORM
from datetime import datetime, timezone


class ResourceQuotaRepository:
    """Quota reads and locks share the caller's transaction; this adapter never commits."""
    def __init__(self, session: AsyncSession):
        self.session = session

    async def account(self, user_id: int, *, lock: bool = False) -> tuple[int, list[tuple[str, str]]]:
        statement = select(User.id, User.extra_spaces_allowance).where(User.id == user_id)
        if lock:
            statement = statement.with_for_update()
        user = (await self.session.execute(statement)).one_or_none()
        if user is None:
            raise QuotaResourceNotFoundError("User not found")
        purchased = await self.session.scalar(select(func.coalesce(func.sum(ActiveSubscriptionORM.quantity), 0)).where(
            ActiveSubscriptionORM.requester_user_id == user_id,
            ActiveSubscriptionORM.kind == "EXTRA_SPACE",
            ActiveSubscriptionORM.status == "ACTIVE",
            ActiveSubscriptionORM.current_period_end > datetime.now(timezone.utc),
        ))
        extra = int(user.extra_spaces_allowance) + int(purchased or 0)
        rows = await self.session.execute(select(SpaceORM.space_type, SpaceORM.subscription_plan).join(
            SpaceMemberORM, SpaceMemberORM.space_id == SpaceORM.id,
        ).where(SpaceMemberORM.user_id == user_id, SpaceMemberORM.role == SpaceRole.OWNER))
        return extra, [(purpose.value, plan.value) for purpose, plan in rows]

    async def effective_tier(self, space: SpaceORM) -> str:
        return await effective_tier(self.session, space)

    async def effective_tiers(self, spaces) -> dict:
        return await effective_tiers(self.session, spaces)

    async def require_space_slot(self, user_id: int, purpose: str) -> None:
        extra, owned = await self.account(user_id, lock=True)
        if not can_create_space(owned, extra, purpose):
            raise QuotaExceededError("SPACE_LIMIT_REACHED", "La cuenta no tiene cupo disponible para otro espacio de este tipo.", len(owned), account_space_limit(extra))

    async def lock_space(self, space_id: UUID) -> SpaceORM:
        space = await self.session.scalar(select(SpaceORM).where(SpaceORM.id == space_id).with_for_update().execution_options(populate_existing=True))
        if space is None:
            raise QuotaResourceNotFoundError("Space not found")
        return space

    async def lock_for_cellar(self, cellar_id: UUID) -> SpaceORM:
        space = await self.session.scalar(select(SpaceORM).join(
            WineCellarORM, WineCellarORM.space_id == SpaceORM.id,
        ).where(WineCellarORM.id == cellar_id).with_for_update(of=SpaceORM).execution_options(populate_existing=True))
        if space is None:
            raise QuotaResourceNotFoundError("Wine cellar not found")
        return space

    async def usage(self, space_id: UUID) -> InventoryUsage:
        result = await self.session.execute(select(
            func.coalesce(func.sum(WineInventoryItemORM.quantity), 0), func.count(WineInventoryItemORM.id),
        ).join(WineCellarORM, WineInventoryItemORM.wine_cellar_id == WineCellarORM.id).where(WineCellarORM.space_id == space_id))
        bottles, skus = result.one()
        return InventoryUsage(bottles=int(bottles), skus=skus)

    async def require_cellar_slot(self, space: SpaceORM) -> None:
        current = await self.session.scalar(select(func.count()).select_from(WineCellarORM).where(WineCellarORM.space_id == space.id))
        maximum = cellar_limit(await self.effective_tier(space), space.extra_cellars_allowance, space.space_type.value)
        if current >= maximum:
            raise QuotaExceededError("CELLAR_LIMIT_REACHED", "El espacio alcanzó el límite de cavas de su plan.", current, maximum)

    async def all_space_usage(self, space_ids: list[UUID]) -> dict[UUID, tuple[int, InventoryUsage]]:
        if not space_ids:
            return {}
        result = await self.session.execute(select(
            WineCellarORM.space_id, func.count(func.distinct(WineCellarORM.id)),
            func.coalesce(func.sum(WineInventoryItemORM.quantity), 0), func.count(WineInventoryItemORM.id),
        ).outerjoin(WineInventoryItemORM, WineInventoryItemORM.wine_cellar_id == WineCellarORM.id)
          .where(WineCellarORM.space_id.in_(space_ids)).group_by(WineCellarORM.space_id))
        return {space_id: (cellars, InventoryUsage(int(bottles), skus)) for space_id, cellars, bottles, skus in result}
