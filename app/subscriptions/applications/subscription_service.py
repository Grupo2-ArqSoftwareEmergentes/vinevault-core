from dataclasses import asdict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.device.applications.space_authorization_service import ALLOWED_ROLES, SpaceAuthorizationService, SpacePermission
from app.device.infrastructure.database.models.space_orm import SpaceORM
from app.device.infrastructure.database.repositories.space_member_repository import SpaceMemberRepository
from app.shared.infrastructure.database.resource_quota_repository import ResourceQuotaRepository
from app.shared.quota_policy import InventoryUsage, can_create_space, cellar_limit, inventory_limit
from app.subscriptions.domain.catalog import CATALOG_VERSION, EXTRA_SPACE_PRICES, account_space_limit, get_plan, price_in
from app.subscriptions.domain.errors import SubscriptionError
from app.subscriptions.infrastructure.database.models import SubscriptionIntentORM
from app.subscriptions.infrastructure.database.subscription_repository import SubscriptionRepository
from app.wine_cellar.infrastructure.database.models.wine_cellar_orm import WineCellarORM


class SubscriptionService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repository = SubscriptionRepository(session)
        self.quotas = ResourceQuotaRepository(session)

    async def _space(self, user_id: int, space_id: UUID, *, owner: bool = False, lock: bool = False):
        try:
            role = await SpaceAuthorizationService(SpaceMemberRepository(self.session)).require(
                space_id, user_id, SpacePermission.MANAGE if owner else SpacePermission.READ,
            )
        except PermissionError as exc:
            raise SubscriptionError("FORBIDDEN", "Insufficient permissions for this space", 403) from exc
        query = select(SpaceORM).where(SpaceORM.id == space_id)
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        space = await self.session.scalar(query)
        if space is None:
            raise SubscriptionError("SPACE_NOT_FOUND", "Space not found", 404)
        return space, role

    async def _cellar(self, space_id: UUID, cellar_id: UUID | None):
        if cellar_id is None:
            return None
        cellar = (await self.session.execute(select(WineCellarORM.id, WineCellarORM.name).where(
            WineCellarORM.id == cellar_id, WineCellarORM.space_id == space_id,
        ))).one_or_none()
        if cellar is None:
            raise SubscriptionError("CELLAR_NOT_FOUND", "Wine cellar not found in this space", 404)
        return {"id": cellar.id, "name": cellar.name, "inherits_space_plan": True}

    async def overview(self, user_id: int, space_id: UUID | None, cellar_id: UUID | None):
        if cellar_id is not None and space_id is None:
            raise SubscriptionError("SPACE_REQUIRED", "space_id is required when cellar_id is supplied", 422)
        space, role = await self._space(user_id, space_id) if space_id is not None else (None, None)
        cellar = await self._cellar(space_id, cellar_id) if space else None
        extra, owned = await self.quotas.account(user_id)
        maximum = account_space_limit(extra)
        result = {"billing_mode": "PREPARATORY", "account_quota": {
            "extra_spaces_allowance": extra, "current_spaces": len(owned), "max_spaces": maximum,
            "remaining_spaces": max(0, maximum - len(owned)),
            "can_create_collector": can_create_space(owned, extra, "COLLECTOR"),
            "can_create_business": can_create_space(owned, extra, "BUSINESS"),
        }, "space": None, "cellar": cellar}
        if space is not None:
            usage = await self.quotas.all_space_usage([space.id])
            cellars, inventory = usage.get(space.id, (0, InventoryUsage(0, 0)))
            resource, limit = inventory_limit(space.subscription_plan.value, space.space_type.value)
            def quota(used, maximum):
                return {"used": used, "limit": maximum, "remaining": max(0, maximum - used) if maximum is not None else None}
            plan = get_plan(space.space_type.value, space.subscription_plan.value)
            result["space"] = {"id": space.id, "name": space.name, "purpose": space.space_type.value,
                "subscription_plan": space.subscription_plan.value, "subscription_status": space.subscription_status.value,
                "role": role.value, "plan": asdict(plan), "extra_cellars_allowance": space.extra_cellars_allowance,
                "can_manage_subscription": role.value == "OWNER",
                "can_analyze": plan.ai_analysis_enabled and role in ALLOWED_ROLES[SpacePermission.ANALYZE],
                "quotas": {
                    "cellars": quota(cellars, cellar_limit(space.subscription_plan.value, space.extra_cellars_allowance, space.space_type.value)),
                    "bottles": quota(inventory.bottles, limit if resource == "bottles" else None),
                    "skus": quota(inventory.skus, limit if resource == "skus" else None),
                }}
        return result

    async def create_request(self, user_id: int, *, kind: str, key: UUID, currency: str, quantity: int = 1, space_id: UUID | None = None, cellar_id: UUID | None = None):
        try:
            # Own the guard's already-open request transaction. Account -> space; never item locks.
            user = await self.repository.lock_account(user_id)
            if user is None or not user.is_active:
                raise SubscriptionError("INVALID_USER", "Invalid or inactive user", 401)
            space = None
            if kind == "UPGRADE_PRO":
                space, _ = await self._space(user_id, space_id, owner=True, lock=True)
                await self._cellar(space_id, cellar_id)
            target = "PRO" if kind == "UPGRADE_PRO" else None
            previous = await self.repository.by_key(user_id, key)
            if previous is not None:
                if (previous.kind, previous.currency, previous.quantity, previous.space_id, previous.cellar_id, previous.target_plan) != (kind, currency, quantity, space_id, cellar_id, target):
                    raise SubscriptionError("IDEMPOTENCY_CONFLICT", "Idempotency key was used with different parameters", 409)
                await self.session.commit()
                return previous
            if space is not None:
                if space.subscription_plan.value != "FREE":
                    raise SubscriptionError("ALREADY_PRO", "This space is already PRO", 409)
                if await self.repository.pending_upgrade(space.id) is not None:
                    raise SubscriptionError("UPGRADE_PENDING", "This space already has a pending upgrade request", 409)
                prices = get_plan(space.space_type.value, "PRO").prices
            else:
                prices = EXTRA_SPACE_PRICES
            try:
                price = price_in(prices, currency)
            except ValueError as exc:
                raise SubscriptionError("CURRENCY_UNAVAILABLE", str(exc), 422) from exc
            intent = await self.repository.add(SubscriptionIntentORM(
                requester_user_id=user_id, idempotency_key=key, kind=kind, status="PENDING_PAYMENT",
                space_id=space_id, cellar_id=cellar_id, target_plan=target,
                currency=currency, unit_amount=price.amount, quantity=quantity,
                total_amount=price.amount * quantity, catalog_version=CATALOG_VERSION,
            ))
            # Intentionally no writes to subscription_plan, status or purchased allowances.
            await self.session.commit()
            return intent
        except Exception:
            await self.session.rollback()
            raise

    async def list_requests(self, user_id: int, limit: int, offset: int):
        return await self.repository.list_for_user(user_id, limit, offset)
