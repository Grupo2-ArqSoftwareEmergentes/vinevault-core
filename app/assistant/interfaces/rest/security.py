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
from app.assistant.domain.models import AssistantMode, CellarSummary, SpaceSummary
from app.subscriptions.domain.catalog import require_feature
from app.subscriptions.infrastructure.database.entitlements import effective_tier
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
    space = await db.get(SpaceORM, payload.space_id)
    if space is None:
        raise HTTPException(404, "Space not found")
    feature = "sommelier_analysis" if payload.mode == AssistantMode.SOMMELIER_ANALYSIS else "assistant_chat"
    require_feature(space.space_type.value, await effective_tier(db, space), feature)
    cellar = None
    if payload.cellar_id is not None:
        row = (await db.execute(select(WineCellarORM.id, WineCellarORM.name).where(
            WineCellarORM.id == payload.cellar_id, WineCellarORM.space_id == payload.space_id,
        ))).one_or_none()
        if row is None:
            raise HTTPException(404, "Wine cellar not found in this space")
        cellar = CellarSummary(id=row.id, name=row.name)
    return SpaceSummary(id=space.id, name=space.name, purpose=space.space_type.value), cellar
