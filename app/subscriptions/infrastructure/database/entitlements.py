"""Effective entitlements derived from unexpired active subscriptions.

The materialized `spaces.subscription_plan`/`User.extra_spaces_allowance` columns are
kept for compatibility, but quota/security decisions use these helpers so an expired
cycle cannot keep granting Pro benefits.
"""
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.subscriptions.infrastructure.database.models import ActiveSubscriptionORM


def active_period_conditions():
    now = datetime.now(timezone.utc)
    return (
        ActiveSubscriptionORM.status == "ACTIVE",
        ActiveSubscriptionORM.started_at <= now,
        ActiveSubscriptionORM.current_period_end > now,
    )


def active_pro_spaces():
    """Canonical SQL entitlement predicate, shared by guards and batch quota reads."""
    return select(ActiveSubscriptionORM.space_id).where(
        ActiveSubscriptionORM.kind == "UPGRADE_PRO",
        *active_period_conditions(),
    )


def effective_tier_expression(space_id):
    return case((space_id.in_(active_pro_spaces()), "PRO"), else_="FREE")


async def effective_tiers(session: AsyncSession, spaces) -> dict[UUID, str]:
    spaces = list(spaces)
    if not spaces:
        return {}
    active = set(await session.scalars(active_pro_spaces().where(
        ActiveSubscriptionORM.space_id.in_([space.id for space in spaces]),
    )))
    return {space.id: "PRO" if space.id in active else "FREE" for space in spaces}


async def effective_tier(session: AsyncSession, space) -> str:
    return (await effective_tiers(session, [space]))[space.id]
