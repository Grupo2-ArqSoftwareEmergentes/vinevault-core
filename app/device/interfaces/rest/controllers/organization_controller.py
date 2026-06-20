from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import (
    get_current_user_id,
    get_organization_repository,
    get_space_repository,
)
from app.device.domain.models import Organization
from app.device.domain.models.value_objects import UserId
from ..resources import (
    CreateOrganizationRequest,
    UpdateOrganizationNameRequest,
    OrganizationResponse,
)


router = APIRouter(prefix="/api/v1/organizations", tags=["Organizations"])


@router.get("")
async def list_organizations(
    user_id: int = Depends(get_current_user_id),
    organization_repo = Depends(get_organization_repository),
) -> List[OrganizationResponse]:
    organizations = await organization_repo.find_all_by_owner_user_id(user_id)
    return [OrganizationResponse.from_domain(org) for org in organizations]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_organization(
    request: CreateOrganizationRequest,
    user_id: int = Depends(get_current_user_id),
    organization_repo = Depends(get_organization_repository),
) -> OrganizationResponse:
    organization = Organization(
        name=request.name,
        owner_user_id=UserId(user_id=user_id),
    )
    saved = await organization_repo.save(organization)
    return OrganizationResponse.from_domain(saved)


@router.patch("/{organization_id}/name")
async def update_organization_name(
    organization_id: UUID,
    request: UpdateOrganizationNameRequest,
    user_id: int = Depends(get_current_user_id),
    organization_repo = Depends(get_organization_repository),
) -> OrganizationResponse:
    organization = await organization_repo.find_by_id(organization_id)
    if not organization:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    if organization.owner_user_id.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization does not belong to user")

    organization.update_name(request.name)
    saved = await organization_repo.save(organization)
    return OrganizationResponse.from_domain(saved)


@router.delete("/{organization_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_organization(
    organization_id: UUID,
    user_id: int = Depends(get_current_user_id),
    organization_repo = Depends(get_organization_repository),
    space_repo = Depends(get_space_repository),
):
    organization = await organization_repo.find_by_id(organization_id)
    if not organization:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    if organization.owner_user_id.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization does not belong to user")

    spaces = await space_repo.find_all_by_organization_id(organization_id)
    if spaces:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Organization has spaces")

    await organization_repo.delete(organization_id)
