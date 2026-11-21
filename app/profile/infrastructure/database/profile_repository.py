from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.iam.models import User


class ProfileRepository:
    """Data access for user profile records; commits belong to ProfileService."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, user_id: int) -> User | None:
        return await self.session.scalar(select(User).where(User.id == user_id))

    async def lock_by_id(self, user_id: int) -> User | None:
        return await self.session.scalar(
            select(User)
            .where(User.id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def username_taken(self, username: str, *, exclude_user_id: int) -> bool:
        existing_id = await self.session.scalar(
            select(User.id)
            .where(func.lower(User.username) == username.lower(), User.id != exclude_user_id)
            .limit(1)
        )
        return existing_id is not None

    async def email_taken(self, email: str, *, exclude_user_id: int) -> bool:
        existing_id = await self.session.scalar(
            select(User.id)
            .where(func.lower(User.email) == email.lower(), User.id != exclude_user_id)
            .limit(1)
        )
        return existing_id is not None
