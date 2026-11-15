from fastapi import APIRouter, Depends

from app.dependencies import get_current_user_id, get_space_repository, get_wine_cellar_repository
from ..resources.user_context_response import (
    ContextSpaceResponse,
    ContextWineCellarResponse,
    UserContextResponse,
)


router = APIRouter(prefix="/api/v1/user", tags=["User Context"])


@router.get("/context", response_model=UserContextResponse)
async def get_user_context(
    user_id: int = Depends(get_current_user_id),
    space_repo = Depends(get_space_repository),
    wine_cellar_repo = Depends(get_wine_cellar_repository),
) -> UserContextResponse:
    # Two tenant-scoped queries, regardless of the number of spaces/cellars.
    spaces = await space_repo.find_all_by_owner_user_id(user_id)
    wine_cellars = await wine_cellar_repo.find_all_by_owner_user_id(user_id)
    return UserContextResponse(
        spaces=[ContextSpaceResponse(id=space.id, name=space.name) for space in spaces],
        wine_cellars=[
            ContextWineCellarResponse(id=cellar.id, name=cellar.name, space_id=cellar.space_id)
            for cellar in wine_cellars
        ],
    )
