from fastapi import APIRouter, Depends

from app.dependencies import get_current_user_id, get_space_repository, get_wine_cellar_repository, get_resource_quota_repository
from app.shared.quota_policy import InventoryUsage, cellar_limit, can_create_space, inventory_limit
from app.subscriptions.domain.catalog import account_space_limit
from ..resources.user_context_response import (
    ContextSpaceResponse,
    ContextWineCellarResponse,
    UserContextResponse,
    ResourceUsageResponse, SpaceQuotaResponse, AccountQuotaResponse,
)


router = APIRouter(prefix="/api/v1/user", tags=["User Context"])


@router.get("/context", response_model=UserContextResponse)
async def get_user_context(
    user_id: int = Depends(get_current_user_id),
    space_repo = Depends(get_space_repository),
    wine_cellar_repo = Depends(get_wine_cellar_repository),
    quota_repo = Depends(get_resource_quota_repository),
) -> UserContextResponse:
    # Fixed query count, regardless of the number of spaces/cellars.
    spaces = await space_repo.find_all_with_membership(user_id)
    wine_cellars = await wine_cellar_repo.find_all_by_owner_user_id(user_id)
    usage = await quota_repo.all_space_usage([space.id for space, role in spaces])
    extra, owned = await quota_repo.account(user_id)

    def resource(used: int, limit: int | None) -> ResourceUsageResponse:
        return ResourceUsageResponse(used=used, limit=limit, remaining=max(0, limit - used) if limit is not None else None)

    def space_quotas(space) -> SpaceQuotaResponse:
        cellars, inventory = usage.get(space.id, (0, InventoryUsage(0, 0)))
        limited_resource, maximum = inventory_limit(space.subscription_plan.value, space.space_type.value)
        return SpaceQuotaResponse(
            cellars=resource(cellars, cellar_limit(space.subscription_plan.value, space.extra_cellars_allowance, space.space_type.value)),
            bottles=resource(inventory.bottles, maximum if limited_resource == "bottles" else None),
            skus=resource(inventory.skus, maximum if limited_resource == "skus" else None),
        )
    return UserContextResponse(
        spaces=[ContextSpaceResponse(
            id=space.id, name=space.name, role=role, space_type=space.space_type,
            subscription_plan=space.subscription_plan, subscription_status=space.subscription_status,
            extra_cellars_allowance=space.extra_cellars_allowance, quotas=space_quotas(space),
        ) for space, role in spaces],
        wine_cellars=[
            ContextWineCellarResponse(id=cellar.id, name=cellar.name, space_id=cellar.space_id)
            for cellar in wine_cellars
        ],
        account_quota=AccountQuotaResponse(
            extra_spaces_allowance=extra, current_spaces=len(owned), max_spaces=account_space_limit(extra),
            remaining_spaces=max(0, account_space_limit(extra) - len(owned)),
            can_create_collector=can_create_space(owned, extra, "COLLECTOR"),
            can_create_business=can_create_space(owned, extra, "BUSINESS"),
        ),
    )
