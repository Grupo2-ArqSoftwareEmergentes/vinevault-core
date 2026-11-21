from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.dependencies import get_subscription_service
from app.subscriptions.applications.subscription_service import SubscriptionService
from app.subscriptions.domain.catalog import catalog
from ..resources.subscription_resources import (
    ActiveSubscriptionResponse, CatalogResponse, ExtraSpaceRequest, OverviewResponse,
    SubscriptionIntentResponse, UpgradeRequest,
)
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


@router.post("/plan-change-requests", response_model=SubscriptionIntentResponse)
async def request_upgrade(
    payload: UpgradeRequest, response: Response,
    user_id: int = Depends(require_active_subscription_user),
    service: SubscriptionService = Depends(get_subscription_service),
):
    intent, subscription = await service.create_request(
        user_id, kind="UPGRADE_PRO", key=payload.idempotency_key, currency=payload.currency,
        space_id=payload.space_id, cellar_id=payload.cellar_id, activate=payload.confirm_simulated_payment,
    )
    response.status_code = 201 if subscription is not None else 202
    return SubscriptionIntentResponse.from_intent(intent, subscription)


@router.post("/extra-space-requests", response_model=SubscriptionIntentResponse)
async def request_extra_space(
    payload: ExtraSpaceRequest, response: Response,
    user_id: int = Depends(require_active_subscription_user),
    service: SubscriptionService = Depends(get_subscription_service),
):
    intent, subscription = await service.create_request(
        user_id, kind="EXTRA_SPACE", key=payload.idempotency_key, currency=payload.currency,
        quantity=payload.quantity, activate=payload.confirm_simulated_payment,
    )
    response.status_code = 201 if subscription is not None else 202
    return SubscriptionIntentResponse.from_intent(intent, subscription)


@router.post("/{subscription_id}/cancel", response_model=ActiveSubscriptionResponse)
async def cancel_subscription(
    subscription_id: UUID,
    user_id: int = Depends(require_active_subscription_user),
    service: SubscriptionService = Depends(get_subscription_service),
):
    return await service.cancel(user_id, subscription_id)


@router.get("/requests", response_model=list[SubscriptionIntentResponse])
async def list_requests(
    limit: int = Query(default=20, ge=1, le=100), offset: int = Query(default=0, ge=0),
    user_id: int = Depends(require_active_subscription_user),
    service: SubscriptionService = Depends(get_subscription_service),
):
    return [SubscriptionIntentResponse.from_intent(intent) for intent in await service.list_requests(user_id, limit, offset)]
