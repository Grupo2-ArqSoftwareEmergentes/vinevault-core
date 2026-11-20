from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.iam.models import User
from .models import SubscriptionIntentORM


class SubscriptionRepository:
    """No commits: the application service owns the request transaction."""
    def __init__(self, session: AsyncSession):
        self.session = session

    async def lock_account(self, user_id: int) -> User | None:
        return await self.session.scalar(select(User).where(User.id == user_id).with_for_update().execution_options(populate_existing=True))

    async def by_key(self, user_id: int, key: UUID):
        return await self.session.scalar(select(SubscriptionIntentORM).where(
            SubscriptionIntentORM.requester_user_id == user_id, SubscriptionIntentORM.idempotency_key == key,
        ))

    async def pending_upgrade(self, space_id: UUID):
        return await self.session.scalar(select(SubscriptionIntentORM.id).where(
            SubscriptionIntentORM.space_id == space_id, SubscriptionIntentORM.kind == "UPGRADE_PRO",
            SubscriptionIntentORM.status == "PENDING_PAYMENT",
        ))

    async def list_for_user(self, user_id: int, limit: int, offset: int):
        rows = await self.session.scalars(select(SubscriptionIntentORM).where(
            SubscriptionIntentORM.requester_user_id == user_id,
        ).order_by(SubscriptionIntentORM.created_at.desc(), SubscriptionIntentORM.id).offset(offset).limit(limit))
        return list(rows)

    async def add(self, intent: SubscriptionIntentORM):
        self.session.add(intent)
        await self.session.flush()
        return intent
