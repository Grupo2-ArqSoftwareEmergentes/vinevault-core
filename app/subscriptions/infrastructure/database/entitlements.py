"""Effective entitlements derived from unexpired active subscriptions.

The materialized `spaces.subscription_plan`/`User.extra_spaces_allowance` columns are
kept for compatibility, but quota/security decisions use these helpers so an expired
cycle cannot keep granting Pro benefits.
"""
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.subscriptions.infrastructure.database.models import ActiveSubscriptionORM


async def effective_tiers(session: AsyncSession, spaces) -> dict[UUID, str]:
    spaces = list(spaces)
    if not spaces:
        return {}
    rows = (await session.execute(select(
        ActiveSubscriptionORM.space_id, ActiveSubscriptionORM.status, ActiveSubscriptionORM.current_period_end,
    ).where(
        ActiveSubscriptionORM.kind == "UPGRADE_PRO",
        ActiveSubscriptionORM.space_id.in_([space.id for space in spaces]),
    ).order_by(ActiveSubscriptionORM.space_id, ActiveSubscriptionORM.current_period_end.desc()))).all()
    latest = {}
    for space_id, status, period_end in rows:
        latest.setdefault(space_id, (status, period_end))
    now = datetime.now(timezone.utc)
    result = {}
    for space in spaces:
        managed = latest.get(space.id)
        if managed is None:
            result[space.id] = space.subscription_plan.value
        else:
            status, period_end = managed
            result[space.id] = "PRO" if status == "ACTIVE" and period_end > now else "FREE"
    return result


async def effective_tier(session: AsyncSession, space) -> str:
    return (await effective_tiers(session, [space]))[space.id]
