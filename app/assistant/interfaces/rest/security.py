from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies import get_current_user_id_optional
from app.device.applications.space_authorization_service import SpaceAuthorizationService, SpacePermission
from app.device.infrastructure.database.repositories.space_member_repository import SpaceMemberRepository
from app.device.infrastructure.database.models.space_orm import SpaceORM
from app.wine_cellar.infrastructure.database.models.wine_cellar_orm import WineCellarORM
from app.iam.models import User
from app.assistant.domain.models import CellarSummary, SpaceSummary
from app.subscriptions.domain.catalog import require_analysis_feature
from .resources import AssistantChatRequest


async def authorize_assistant_request(
    payload: AssistantChatRequest,
    user_id: int | None = Depends(get_current_user_id_optional),
    db: AsyncSession = Depends(get_db),
) -> tuple[SpaceSummary, CellarSummary | None]:
    if user_id is None or await db.scalar(select(User.id).where(User.id == user_id, User.is_active.is_(True))) is None:
        raise HTTPException(401, "Invalid or inactive user", headers={"WWW-Authenticate": "Bearer"})
    try:
        await SpaceAuthorizationService(SpaceMemberRepository(db)).require(payload.space_id, user_id, SpacePermission.ANALYZE)
    except PermissionError as exc:
        raise HTTPException(403, "Insufficient permissions for this space") from exc
    space = (await db.execute(select(SpaceORM.id, SpaceORM.name, SpaceORM.space_type, SpaceORM.subscription_plan).where(SpaceORM.id == payload.space_id))).one_or_none()
    if space is None:
        raise HTTPException(404, "Space not found")
    require_analysis_feature(space.space_type.value, space.subscription_plan.value)
    cellar = None
    if payload.cellar_id is not None:
        row = (await db.execute(select(WineCellarORM.id, WineCellarORM.name).where(
            WineCellarORM.id == payload.cellar_id, WineCellarORM.space_id == payload.space_id,
        ))).one_or_none()
        if row is None:
            raise HTTPException(404, "Wine cellar not found in this space")
        cellar = CellarSummary(id=row.id, name=row.name)
    return SpaceSummary(id=space.id, name=space.name, purpose=space.space_type.value), cellar
