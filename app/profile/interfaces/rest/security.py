from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies import get_current_user_id_optional
from app.iam.models import User


async def require_active_profile_user(
    user_id: int | None = Depends(get_current_user_id_optional),
    db: AsyncSession = Depends(get_db),
) -> int:
    if user_id is None or await db.scalar(select(User.id).where(User.id == user_id, User.is_active.is_(True))) is None:
        raise HTTPException(401, "Invalid or inactive user", headers={"WWW-Authenticate": "Bearer"})
    return user_id
