from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import (
    get_current_user_id,
    get_organization_repository,
    get_space_repository,
    get_device_assignment_repository,
)
from app.device.domain.models import Space
from app.device.domain.models.value_objects import UserId
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

    spaces = await space_repo.find_all_by_organization_id(organization_id)
    return [SpaceResponse.from_domain(space) for space in spaces]


@router.post("/organizations/{organization_id}/spaces", status_code=status.HTTP_201_CREATED)
async def create_space(
    organization_id: UUID,
    request: CreateSpaceRequest,
    user_id: int = Depends(get_current_user_id),
    organization_repo = Depends(get_organization_repository),
    space_repo = Depends(get_space_repository),
) -> SpaceResponse:
    organization = await organization_repo.find_by_id(organization_id)
    if not organization:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    if organization.owner_user_id.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization does not belong to user")

    existing_spaces = await space_repo.find_all_by_organization_id(organization_id)
    if len(existing_spaces) >= organization.get_max_spaces():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Organization reached max spaces")

    space = Space(
        name=request.name,
        organization_id=organization_id,
        owner_user_id=UserId(user_id=user_id),
    )
    saved = await space_repo.save(space)
    return SpaceResponse.from_domain(saved)


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
    if space.owner_user_id.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Space does not belong to user")

    space.update_name(request.name)
    saved = await space_repo.save(space)
    return SpaceResponse.from_domain(saved)


@router.delete("/spaces/{space_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_space(
    space_id: UUID,
    user_id: int = Depends(get_current_user_id),
    space_repo = Depends(get_space_repository),
    assignment_repo = Depends(get_device_assignment_repository),
):
    space = await space_repo.find_by_id(space_id)
    if not space:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Space not found")
    if space.owner_user_id.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Space does not belong to user")

    if await assignment_repo.exists_by_space_id(space_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Space has devices")

    await space_repo.delete(space_id)
