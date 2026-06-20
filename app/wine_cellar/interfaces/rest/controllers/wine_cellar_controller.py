from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import (
    get_current_user_id,
    get_device_assignment_repository,
    get_space_repository,
    get_wine_cellar_repository,
)
from app.wine_cellar.domain.models import WineCellar
from ..resources import (
    CreateWineCellarRequest,
    LinkWineCellarDeviceRequest,
    UpdateWineCellarRequest,
    WineCellarResponse,
)


router = APIRouter(prefix="/api/v1", tags=["Wine Cellars"])


async def _get_space_for_user(space_id: UUID, user_id: int, space_repo):
    space = await space_repo.find_by_id(space_id)
    if not space:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Space not found")
    if space.owner_user_id.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Space does not belong to user")
    return space


async def _get_wine_cellar_for_user(wine_cellar_id: UUID, user_id: int, wine_cellar_repo, space_repo):
    wine_cellar = await wine_cellar_repo.find_by_id(wine_cellar_id)
    if not wine_cellar:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Wine cellar not found")
    await _get_space_for_user(wine_cellar.space_id, user_id, space_repo)
    return wine_cellar


@router.get("/spaces/{space_id}/wine-cellars")
async def list_wine_cellars(
    space_id: UUID,
    user_id: int = Depends(get_current_user_id),
    space_repo = Depends(get_space_repository),
    wine_cellar_repo = Depends(get_wine_cellar_repository),
) -> List[WineCellarResponse]:
    await _get_space_for_user(space_id, user_id, space_repo)
    wine_cellars = await wine_cellar_repo.find_all_by_space_id(space_id)
    return [WineCellarResponse.from_domain(wine_cellar) for wine_cellar in wine_cellars]


@router.post("/spaces/{space_id}/wine-cellars", status_code=status.HTTP_201_CREATED)
async def create_wine_cellar(
    space_id: UUID,
    request: CreateWineCellarRequest,
    user_id: int = Depends(get_current_user_id),
    space_repo = Depends(get_space_repository),
    wine_cellar_repo = Depends(get_wine_cellar_repository),
) -> WineCellarResponse:
    await _get_space_for_user(space_id, user_id, space_repo)

    wine_cellar = WineCellar(
        space_id=space_id,
        name=request.name,
        description=request.description,
    )
    saved = await wine_cellar_repo.save(wine_cellar)
    return WineCellarResponse.from_domain(saved)


@router.put("/wine-cellars/{wine_cellar_id}")
async def update_wine_cellar(
    wine_cellar_id: UUID,
    request: UpdateWineCellarRequest,
    user_id: int = Depends(get_current_user_id),
    wine_cellar_repo = Depends(get_wine_cellar_repository),
    space_repo = Depends(get_space_repository),
) -> WineCellarResponse:
    wine_cellar = await _get_wine_cellar_for_user(wine_cellar_id, user_id, wine_cellar_repo, space_repo)
    wine_cellar.update(name=request.name, description=request.description)
    saved = await wine_cellar_repo.save(wine_cellar)
    return WineCellarResponse.from_domain(saved)


@router.delete("/wine-cellars/{wine_cellar_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_wine_cellar(
    wine_cellar_id: UUID,
    user_id: int = Depends(get_current_user_id),
    wine_cellar_repo = Depends(get_wine_cellar_repository),
    space_repo = Depends(get_space_repository),
):
    await _get_wine_cellar_for_user(wine_cellar_id, user_id, wine_cellar_repo, space_repo)
    await wine_cellar_repo.delete(wine_cellar_id)


@router.post("/wine-cellars/{wine_cellar_id}/devices")
async def link_device_to_wine_cellar(
    wine_cellar_id: UUID,
    request: LinkWineCellarDeviceRequest,
    user_id: int = Depends(get_current_user_id),
    wine_cellar_repo = Depends(get_wine_cellar_repository),
    space_repo = Depends(get_space_repository),
    assignment_repo = Depends(get_device_assignment_repository),
) -> WineCellarResponse:
    wine_cellar = await _get_wine_cellar_for_user(wine_cellar_id, user_id, wine_cellar_repo, space_repo)

    device_assignment = await assignment_repo.find_by_device_id(request.device_id)
    if not device_assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    if device_assignment.owner_user_id is None or device_assignment.owner_user_id.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Device does not belong to user")
    if device_assignment.space_id != wine_cellar.space_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Device does not belong to the same space as the wine cellar")
    if wine_cellar.device_id is not None and wine_cellar.device_id != request.device_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Wine cellar already has a linked device")

    existing = await wine_cellar_repo.find_by_device_id(request.device_id)
    if existing and existing.id != wine_cellar.id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Device is already linked to another wine cellar")

    wine_cellar.link_device(request.device_id)
    saved = await wine_cellar_repo.save(wine_cellar)
    return WineCellarResponse.from_domain(saved)


@router.delete("/wine-cellars/{wine_cellar_id}/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_device_from_wine_cellar(
    wine_cellar_id: UUID,
    device_id: UUID,
    user_id: int = Depends(get_current_user_id),
    wine_cellar_repo = Depends(get_wine_cellar_repository),
    space_repo = Depends(get_space_repository),
):
    wine_cellar = await _get_wine_cellar_for_user(wine_cellar_id, user_id, wine_cellar_repo, space_repo)
    if wine_cellar.device_id != device_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device is not linked to this wine cellar")

    wine_cellar.unlink_device()
    await wine_cellar_repo.save(wine_cellar)
