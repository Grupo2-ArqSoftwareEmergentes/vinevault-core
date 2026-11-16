"""Shared guard for user-facing space, cellar, device and AI routes, not edge ingestion."""
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies import get_current_user_id_optional
from app.iam.models import User
from app.device.applications.space_authorization_service import SpaceAuthorizationService, SpacePermission
from app.device.infrastructure.database.repositories.space_member_repository import SpaceMemberRepository
from app.device.infrastructure.database.models.space_orm import SpaceORM
from app.device.infrastructure.database.models.device_assignment_orm import DeviceAssignmentORM
from app.wine_cellar.infrastructure.database.models.wine_cellar_orm import WineCellarORM


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
    if request.method == "POST" and (request.url.path.startswith("/api/v1/ai/") or request.url.path == "/api/v1/devices/claim"):
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
        elif "/inventory" in path:
            permission = SpacePermission.INVENTORY
        elif "/wine-cellars" in path or "/devices" in path:
            permission = SpacePermission.CONFIGURE
        else:
            permission = SpacePermission.MANAGE
    try:
        role = await SpaceAuthorizationService(SpaceMemberRepository(db)).require(space_id, user_id, permission)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    request.state.space_role = role
    request.state.space_id = space_id
