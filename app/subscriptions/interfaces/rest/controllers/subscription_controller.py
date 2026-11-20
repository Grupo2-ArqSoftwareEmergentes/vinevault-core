from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.dependencies import get_subscription_service
from app.subscriptions.applications.subscription_service import SubscriptionService
from app.subscriptions.domain.catalog import catalog
from ..resources.subscription_resources import CatalogResponse, ExtraSpaceRequest, OverviewResponse, SubscriptionIntentResponse, UpgradeRequest
from ..security import require_active_subscription_user


router = APIRouter(prefix="/api/v1/subscriptions", tags=["Subscriptions"])


@router.get("/catalog", response_model=CatalogResponse)
async def get_catalog(user_id: int = Depends(require_active_subscription_user)):
    return catalog()


@router.get("/overview", response_model=OverviewResponse)
async def get_overview(
    space_id: UUID | None = None, cellar_id: UUID | None = None,
    user_id: int = Depends(require_active_subscription_user),
    service: SubscriptionService = Depends(get_subscription_service),
):
    return await service.overview(user_id, space_id, cellar_id)


@router.post("/plan-change-requests", response_model=SubscriptionIntentResponse, status_code=202)
async def request_upgrade(
    payload: UpgradeRequest, user_id: int = Depends(require_active_subscription_user),
    service: SubscriptionService = Depends(get_subscription_service),
):
    intent = await service.create_request(user_id, kind="UPGRADE_PRO", key=payload.idempotency_key,
        currency=payload.currency, space_id=payload.space_id, cellar_id=payload.cellar_id)
    return SubscriptionIntentResponse.from_intent(intent)


@router.post("/extra-space-requests", response_model=SubscriptionIntentResponse, status_code=202)
async def request_extra_space(
    payload: ExtraSpaceRequest, user_id: int = Depends(require_active_subscription_user),
    service: SubscriptionService = Depends(get_subscription_service),
):
    intent = await service.create_request(user_id, kind="EXTRA_SPACE", key=payload.idempotency_key,
        currency=payload.currency, quantity=payload.quantity)
    return SubscriptionIntentResponse.from_intent(intent)


@router.get("/requests", response_model=list[SubscriptionIntentResponse])
async def list_requests(
    limit: int = Query(default=20, ge=1, le=100), offset: int = Query(default=0, ge=0),
    user_id: int = Depends(require_active_subscription_user),
    service: SubscriptionService = Depends(get_subscription_service),
):
    return [SubscriptionIntentResponse.from_intent(intent) for intent in await service.list_requests(user_id, limit, offset)]
