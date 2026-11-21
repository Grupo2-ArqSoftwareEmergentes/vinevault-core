"""Shared guard for user-facing space, cellar, device and AI routes, not edge ingestion."""
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies import get_current_user_id_optional
from app.iam.models import User
from app.device.applications.space_authorization_service import ALLOWED_ROLES, SpaceAuthorizationService, SpacePermission
from app.device.infrastructure.database.repositories.space_member_repository import SpaceMemberRepository
from app.device.infrastructure.database.models.space_orm import SpaceORM
from app.device.infrastructure.database.models.space_member_orm import SpaceMemberORM
from app.device.infrastructure.database.models.device_assignment_orm import DeviceAssignmentORM
from app.wine_cellar.infrastructure.database.models.wine_cellar_orm import WineCellarORM
from app.subscriptions.domain.catalog import plans_with_feature, require_feature
from app.subscriptions.domain.errors import SubscriptionError
from app.subscriptions.infrastructure.database.entitlements import effective_tier, effective_tier_expression


async def authorize_inventory_autocomplete(
    user_id: int | None = Depends(get_current_user_id_optional),
    db: AsyncSession = Depends(get_db),
    space_id: UUID | None = None,
) -> None:
    """Name-only suggestions require an active account with an existing ANALYZE membership."""
    if user_id is None or await db.scalar(select(User.id).where(User.id == user_id, User.is_active.is_(True))) is None:
        raise HTTPException(status_code=401, detail="Invalid or inactive user", headers={"WWW-Authenticate": "Bearer"})
    allowed_memberships = (
        select(SpaceMemberORM.space_id)
        .join(SpaceORM, SpaceORM.id == SpaceMemberORM.space_id)
        .where(SpaceMemberORM.user_id == user_id, SpaceMemberORM.role.in_(ALLOWED_ROLES[SpacePermission.ANALYZE]))
    )
    if space_id is not None:
        allowed_memberships = allowed_memberships.where(SpaceORM.id == space_id)
    membership = await db.scalar(allowed_memberships.where(or_(False, *(
        and_(SpaceORM.space_type == purpose, effective_tier_expression(SpaceORM.id) == tier)
        for purpose, tier in plans_with_feature("autocomplete")
    ))).limit(1))
    if membership is None:
        if await db.scalar(allowed_memberships.limit(1)) is not None:
            raise SubscriptionError("PLAN_FEATURE_UNAVAILABLE", "El autocompletado con IA requiere plan PRO.", 403)
        raise HTTPException(status_code=403, detail="An ANALYZE membership in a valid space is required")


async def authorize_space_request(
    request: Request,
    user_id: int | None = Depends(get_current_user_id_optional),
    db: AsyncSession = Depends(get_db),
) -> None:
    # Factory pairing has no tenant yet; claiming it does require space permissions.
    if request.url.path == "/api/v1/devices/pair":
        return
    if user_id is None or await db.scalar(select(User.id).where(User.id == user_id, User.is_active.is_(True))) is None:
        raise HTTPException(status_code=401, detail="Invalid or inactive user")

    parameters = request.path_params
    if request.query_params.get("space_id") and request.query_params.get("spaceId"):
        try:
            if UUID(request.query_params["space_id"]) != UUID(request.query_params["spaceId"]):
                raise HTTPException(status_code=422, detail="Conflicting space_id and spaceId")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid context identifier") from exc
    raw_space = parameters.get("space_id") or request.query_params.get("space_id") or request.query_params.get("spaceId")
    cellar_id = parameters.get("wine_cellar_id")
    device_id = parameters.get("device_id")
    if request.method == "POST" and (request.url.path.startswith("/api/v1/ai/") or request.url.path in {
        "/api/v1/devices/claim", "/api/v1/wine-cellars", "/api/v1/wine-items",
    }):
        try:
            body = await request.json()
        except ValueError:
            return  # Pydantic will reject malformed request bodies.
        if not isinstance(body, dict):
            return
        raw_space = body.get("space_id") or raw_space
        cellar_id = body.get("wine_cellar_id") or cellar_id
    try:
        if cellar_id:
            space_id = await db.scalar(select(WineCellarORM.space_id).where(WineCellarORM.id == UUID(str(cellar_id))))
            if space_id is None:
                raise HTTPException(status_code=404, detail="Wine cellar not found")
        elif device_id:
            space_id = await db.scalar(select(DeviceAssignmentORM.space_id).where(DeviceAssignmentORM.device_id == UUID(str(device_id))))
            if space_id is None:
                raise HTTPException(status_code=404, detail="Assigned device not found")
        elif raw_space:
            space_id = UUID(str(raw_space))
            if await db.scalar(select(SpaceORM.id).where(SpaceORM.id == space_id)) is None:
                raise HTTPException(status_code=404, detail="Space not found")
        else:
            return
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(status_code=422, detail="Invalid context identifier") from exc

    permission = SpacePermission.READ
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        path = request.url.path
        if path.startswith("/api/v1/ai/"):
            permission = SpacePermission.ANALYZE
        elif "/inventory" in path or path == "/api/v1/wine-items":
            permission = SpacePermission.INVENTORY
        elif "/wine-cellars" in path or "/devices" in path:
            permission = SpacePermission.CONFIGURE
        else:
            permission = SpacePermission.MANAGE
    try:
        role = await SpaceAuthorizationService(SpaceMemberRepository(db)).require(space_id, user_id, permission)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if permission == SpacePermission.ANALYZE:
        space = await db.get(SpaceORM, space_id)
        if space is None:
            raise HTTPException(404, "Space not found")
        require_feature(space.space_type.value, await effective_tier(db, space), "stock_analysis")
    request.state.space_role = role
    request.state.space_id = space_id
