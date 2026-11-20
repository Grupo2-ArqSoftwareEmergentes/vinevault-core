from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.device.applications.space_authorization_service import ALLOWED_ROLES, SpaceAuthorizationService, SpacePermission
from app.device.domain.models.value_objects.space_access import SubscriptionPlan, SubscriptionStatus
from app.device.infrastructure.database.models.space_orm import SpaceORM
from app.device.infrastructure.database.repositories.space_member_repository import SpaceMemberRepository
from app.shared.infrastructure.database.resource_quota_repository import ResourceQuotaRepository
from app.shared.quota_policy import InventoryUsage, can_create_space, cellar_limit, inventory_limit
from app.subscriptions.domain.catalog import (
    CATALOG_VERSION, CYCLE_DAYS, EXTRA_SPACE_PRICES, account_space_limit, get_plan, price_in,
)
from app.subscriptions.domain.errors import SubscriptionError
from app.subscriptions.infrastructure.database.entitlements import effective_tier
from app.subscriptions.infrastructure.database.models import ActiveSubscriptionORM, SubscriptionIntentORM
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

    async def _expire_due(self, user_id: int, space_id: UUID | None = None) -> None:
        """Lazy cycle close: expired rows lose every benefit, without deleting history."""
        now = datetime.now(timezone.utc)
        scopes = [ActiveSubscriptionORM.requester_user_id == user_id]
        if space_id is not None:
            from sqlalchemy import or_
            scopes = [or_(ActiveSubscriptionORM.requester_user_id == user_id, ActiveSubscriptionORM.space_id == space_id)]
        rows = list(await self.session.scalars(select(ActiveSubscriptionORM).where(
            ActiveSubscriptionORM.status == "ACTIVE", ActiveSubscriptionORM.current_period_end <= now, *scopes,
        ).with_for_update()))
        affected = set()
        for row in rows:
            row.status = "EXPIRED"
            if row.kind == "UPGRADE_PRO" and row.space_id is not None:
                affected.add(row.space_id)
        for affected_space in affected:
            if await self.repository.active_pro(affected_space) is None:
                space = await self.session.get(SpaceORM, affected_space)
                if space is not None:
                    space.subscription_plan = SubscriptionPlan.FREE
        if rows:
            await self.session.flush()

    @staticmethod
    def _billing(subscriptions: list[ActiveSubscriptionORM], space_subscription: ActiveSubscriptionORM | None):
        now = datetime.now(timezone.utc)
        visible = {row.id: row for row in subscriptions if row.status == "ACTIVE" and row.current_period_end > now}
        if space_subscription is not None and space_subscription.status == "ACTIVE" and space_subscription.current_period_end > now:
            visible.setdefault(space_subscription.id, space_subscription)
        rows = sorted(visible.values(), key=lambda row: (row.created_at, str(row.id)), reverse=True)
        current = sum((row.total_amount for row in rows), Decimal("0.00"))
        next_cycle = sum((row.total_amount for row in rows if not row.cancel_at_period_end), Decimal("0.00"))
        return {
            "currency": "PEN", "cycle_days": CYCLE_DAYS,
            "monthly_recurring_total": current, "next_cycle_monthly_total": next_cycle,
            "active_subscriptions": rows,
        }

    async def overview(self, user_id: int, space_id: UUID | None, cellar_id: UUID | None):
        if cellar_id is not None and space_id is None:
            raise SubscriptionError("SPACE_REQUIRED", "space_id is required when cellar_id is supplied", 422)
        space, role = await self._space(user_id, space_id) if space_id is not None else (None, None)
        cellar = await self._cellar(space_id, cellar_id) if space else None
        await self._expire_due(user_id, space_id)
        subscriptions = await self.repository.active_for_user(user_id)
        extra, owned = await self.quotas.account(user_id)
        maximum = account_space_limit(extra)
        result = {"billing_mode": "PREPARATORY", "account_quota": {
            "extra_spaces_allowance": extra, "current_spaces": len(owned),
            "max_spaces": maximum, "remaining_spaces": max(0, maximum - len(owned)),
            "can_create_collector": can_create_space(owned, extra, "COLLECTOR"),
            "can_create_business": can_create_space(owned, extra, "BUSINESS"),
        }, "space": None, "cellar": cellar, "billing": None}
        space_subscription = None
        space_subscriptions = subscriptions
        if space is not None:
            tier = await effective_tier(self.session, space)
            usage = await self.quotas.all_space_usage([space.id])
            cellars, inventory = usage.get(space.id, (0, InventoryUsage(0, 0)))
            resource, limit = inventory_limit(tier, space.space_type.value)
            def quota(used, maximum):
                return {"used": used, "limit": maximum, "remaining": max(0, maximum - used) if maximum is not None else None}
            plan = get_plan(space.space_type.value, tier)
            space_subscription = await self.repository.active_for_space(space.id)
            result["space"] = {
                "id": space.id, "name": space.name, "purpose": space.space_type.value,
                "subscription_plan": tier, "subscription_status": space.subscription_status.value,
                "role": role.value, "plan": asdict(plan), "extra_cellars_allowance": space.extra_cellars_allowance,
                "can_manage_subscription": role.value == "OWNER",
                "can_analyze": plan.ai_analysis_enabled and role in ALLOWED_ROLES[SpacePermission.ANALYZE],
                "active_subscription": space_subscription,
                "quotas": {
                    "cellars": quota(cellars, cellar_limit(tier, space.extra_cellars_allowance, space.space_type.value)),
                    "bottles": quota(inventory.bottles, limit if resource == "bottles" else None),
                    "skus": quota(inventory.skus, limit if resource == "skus" else None),
                },
            }
        result["billing"] = self._billing(space_subscriptions, space_subscription)
        await self.session.commit()
        return result

    def _create_intent(self, *, user_id, key, kind, currency, quantity, space_id, cellar_id, status):
        return SubscriptionIntentORM(
            requester_user_id=user_id, idempotency_key=key, kind=kind, status=status,
            space_id=space_id, cellar_id=cellar_id, target_plan="PRO" if kind == "UPGRADE_PRO" else None,
            currency=currency, unit_amount=Decimal("0"), quantity=quantity, total_amount=Decimal("0"),
            catalog_version=CATALOG_VERSION,
        )

    def _price(self, *, kind: str, space: SpaceORM | None, currency: str):
        prices = get_plan(space.space_type.value, "PRO").prices if kind == "UPGRADE_PRO" and space else EXTRA_SPACE_PRICES
        try:
            return price_in(prices, currency)
        except ValueError as exc:
            raise SubscriptionError("CURRENCY_UNAVAILABLE", str(exc), 422) from exc

    async def create_request(
        self, user_id: int, *, kind: str, key: UUID, currency: str, quantity: int = 1,
        space_id: UUID | None = None, cellar_id: UUID | None = None, activate: bool = False,
    ):
        """Create a pending intent, or activate immediately for a confirmed simulated payment."""
        try:
            # Own the request transaction. Account -> space lock order; never item locks.
            user = await self.repository.lock_account(user_id)
            if user is None or not user.is_active:
                raise SubscriptionError("INVALID_USER", "Invalid or inactive user", 401)
            if activate and currency != "PEN":
                raise SubscriptionError(
                    "SIMULATED_ACTIVATION_REQUIRES_PEN",
                    "Immediate simulated activation is available in PEN only; USD requests remain pending.",
                    422,
                )
            space = None
            if kind == "UPGRADE_PRO":
                if space_id is None:
                    raise SubscriptionError("SPACE_REQUIRED", "space_id is required for an upgrade", 422)
                space, _ = await self._space(user_id, space_id, owner=True, lock=True)
                await self._cellar(space_id, cellar_id)
                await self._expire_due(user_id, space_id)

            previous = await self.repository.by_key(user_id, key)
            if previous is not None:
                same = (previous.kind, previous.currency, previous.quantity, previous.space_id, previous.cellar_id) == (
                    kind, currency, quantity, space_id, cellar_id)
                if not same:
                    raise SubscriptionError("IDEMPOTENCY_CONFLICT", "Idempotency key was used with different parameters", 409)
                if previous.status == "FULFILLED":
                    subscription = await self.repository.subscription_for_intent(previous.id)
                    await self.session.commit()
                    return previous, subscription
                if previous.status == "CANCELLED":
                    raise SubscriptionError("INTENT_CANCELLED", "This request was cancelled; use a new idempotency key", 409)
                intent = previous
            else:
                intent = await self.repository.add(self._create_intent(
                    user_id=user_id, key=key, kind=kind, currency=currency, quantity=quantity,
                    space_id=space_id, cellar_id=cellar_id, status="FULFILLED" if activate else "PENDING_PAYMENT",
                ))

            if activate and space is not None and await effective_tier(self.session, space) != "FREE":
                raise SubscriptionError("ALREADY_PRO", "This space already has an active PRO plan", 409)

            if not activate:
                if space is not None:
                    if space.subscription_plan.value != "FREE" and await self.repository.active_pro(space.id) is None:
                        raise SubscriptionError("ALREADY_PRO", "This space is already PRO", 409)
                    if await self.repository.pending_upgrade(space.id, exclude_id=intent.id) is not None:
                        raise SubscriptionError("UPGRADE_PENDING", "This space already has a pending upgrade request", 409)
                price = self._price(kind=kind, space=space, currency=currency)
                intent.unit_amount, intent.total_amount = price.amount, price.amount * quantity
                await self.session.commit()
                return intent, None

            # Confirmed simulated payment: quote from immutable catalogue, grant immediately.
            price = self._price(kind=kind, space=space, currency=currency)
            if previous is None:
                intent.unit_amount, intent.total_amount = price.amount, price.amount * quantity
            now = datetime.now(timezone.utc)
            for stale in await self.repository.pending_upgrades(space_id) if space is not None else []:
                stale.status = "CANCELLED"
            subscription = await self.repository.add_subscription(ActiveSubscriptionORM(
                requester_user_id=user_id, intent_id=intent.id, kind=kind, status="ACTIVE",
                cancel_at_period_end=False, space_id=space_id, quantity=quantity, currency=currency,
                unit_amount=price.amount, total_amount=price.amount * quantity,
                started_at=now, current_period_end=now + timedelta(days=CYCLE_DAYS), catalog_version=CATALOG_VERSION,
            ))
            intent.status = "FULFILLED"
            if space is not None:
                space.subscription_plan = SubscriptionPlan.PRO
                space.subscription_status = SubscriptionStatus.ACTIVE
            await self.session.commit()
            return intent, subscription
        except Exception:
            await self.session.rollback()
            raise

    async def cancel(self, user_id: int, subscription_id: UUID):
        try:
            user = await self.repository.lock_account(user_id)
            if user is None or not user.is_active:
                raise SubscriptionError("INVALID_USER", "Invalid or inactive user", 401)
            subscription = await self.repository.by_id(subscription_id, lock=True)
            if subscription is None:
                raise SubscriptionError("SUBSCRIPTION_NOT_FOUND", "Subscription not found", 404)
            if subscription.kind == "UPGRADE_PRO":
                await self._space(user_id, subscription.space_id, owner=True, lock=True)
            elif subscription.requester_user_id != user_id:
                raise SubscriptionError("SUBSCRIPTION_NOT_FOUND", "Subscription not found", 404)
            if subscription.status != "ACTIVE" or subscription.current_period_end <= datetime.now(timezone.utc):
                raise SubscriptionError("SUBSCRIPTION_EXPIRED", "This subscription has no remaining period", 409)
            if not subscription.cancel_at_period_end:
                subscription.cancel_at_period_end = True
                subscription.cancelled_at = datetime.now(timezone.utc)
            await self.session.commit()
            return subscription
        except Exception:
            await self.session.rollback()
            raise

    async def list_requests(self, user_id: int, limit: int, offset: int):
        return await self.repository.list_for_user(user_id, limit, offset)
