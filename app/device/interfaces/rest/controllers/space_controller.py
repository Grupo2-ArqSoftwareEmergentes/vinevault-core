from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import (
    get_current_user_id,
    get_organization_repository,
    get_space_repository,
    get_space_creation_service,
    get_space_deletion_service,
)
from app.device.applications.personal_space_service import (
    OrganizationAccessDeniedError,
    OrganizationNotFoundError,
    SpaceLimitReachedError,
)
from app.device.domain.models.value_objects.space_access import SpaceType
from ..resources.request_models import OnboardSpaceRequest
from ..resources.created_space_response import CreatedSpaceResponse
from app.device.applications.space_deletion_service import (
    SpaceAccessDeniedError,
    SpaceHasDevicesError,
    SpaceNotFoundError,
)
from app.wine_cellar.interfaces.rest.resources.wine_cellar_response import WineCellarResponse
from ..resources import (
    CreateSpaceRequest,
    UpdateSpaceNameRequest,
    SpaceResponse,
)


router = APIRouter(prefix="/api/v1", tags=["Spaces"])


@router.get("/organizations/{organization_id}/spaces")
async def list_spaces_by_organization(
    organization_id: UUID,
    user_id: int = Depends(get_current_user_id),
    organization_repo = Depends(get_organization_repository),
    space_repo = Depends(get_space_repository),
) -> List[SpaceResponse]:
    organization = await organization_repo.find_by_id(organization_id)
    if not organization:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    if organization.owner_user_id.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization does not belong to user")

    spaces = [space for space in await space_repo.find_all_by_owner_user_id(user_id) if space.organization_id == organization_id]
    return [SpaceResponse.from_domain(space) for space in spaces]


@router.get("/spaces")
async def list_spaces(
    user_id: int = Depends(get_current_user_id),
    space_repo = Depends(get_space_repository),
) -> List[SpaceResponse]:
    spaces = await space_repo.find_all_by_owner_user_id(user_id)
    return [SpaceResponse.from_domain(space) for space in spaces]


@router.post("/organizations/{organization_id}/spaces", status_code=status.HTTP_201_CREATED)
async def create_space(
    organization_id: UUID,
    request: CreateSpaceRequest,
    user_id: int = Depends(get_current_user_id),
    service = Depends(get_space_creation_service),
) -> CreatedSpaceResponse:
    return await _create_space_with_cellar(service, user_id, request.name, organization_id, request.space_type)


@router.post("/spaces", status_code=status.HTTP_201_CREATED)
async def create_personal_space(
    request: CreateSpaceRequest,
    user_id: int = Depends(get_current_user_id),
    service = Depends(get_space_creation_service),
) -> CreatedSpaceResponse:
    return await _create_space_with_cellar(service, user_id, request.name, space_type=request.space_type)


@router.post("/user/onboarding", status_code=status.HTTP_201_CREATED)
async def onboard_space(
    request: OnboardSpaceRequest,
    user_id: int = Depends(get_current_user_id),
    service = Depends(get_space_creation_service),
) -> CreatedSpaceResponse:
    return await _create_space_with_cellar(service, user_id, request.name, space_type=request.space_type)


async def _create_space_with_cellar(
    service, user_id: int, name: str, organization_id: UUID | None = None,
    space_type: SpaceType = SpaceType.COLLECTOR,
):
    try:
        created = await service.create(user_id, name, organization_id, space_type)
    except SpaceLimitReachedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except OrganizationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except OrganizationAccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return CreatedSpaceResponse(
        **SpaceResponse.from_domain(created.space).model_dump(),
        default_wine_cellar=WineCellarResponse.from_domain(created.default_wine_cellar),
    )


@router.patch("/spaces/{space_id}/name")
async def update_space_name(
    space_id: UUID,
    request: UpdateSpaceNameRequest,
    user_id: int = Depends(get_current_user_id),
    space_repo = Depends(get_space_repository),
) -> SpaceResponse:
    space = await space_repo.find_by_id(space_id)
    if not space:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Space not found")

    space.update_name(request.name)
    saved = await space_repo.save(space)
    return SpaceResponse.from_domain(saved)


@router.get("/spaces/{space_id}")
async def get_space(
    space_id: UUID,
    user_id: int = Depends(get_current_user_id),
    space_repo = Depends(get_space_repository),
) -> SpaceResponse:
    space = await space_repo.find_by_id(space_id)
    if not space:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Space not found")
    return SpaceResponse.from_domain(space)


@router.delete("/spaces/{space_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_space(
    space_id: UUID,
    user_id: int = Depends(get_current_user_id),
    service = Depends(get_space_deletion_service),
):
    try:
        await service.delete(user_id, space_id)
    except SpaceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SpaceAccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except SpaceHasDevicesError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
