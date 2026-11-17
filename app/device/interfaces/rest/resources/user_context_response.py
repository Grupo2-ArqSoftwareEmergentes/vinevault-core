from uuid import UUID

from pydantic import BaseModel
from app.device.domain.models.value_objects.space_access import SpaceRole, SpaceType, SubscriptionPlan, SubscriptionStatus


class ContextSpaceResponse(BaseModel):
    id: UUID
    name: str
    role: SpaceRole
    space_type: SpaceType
    subscription_plan: SubscriptionPlan
    subscription_status: SubscriptionStatus
    extra_cellars_allowance: int
    quotas: "SpaceQuotaResponse"


class ResourceUsageResponse(BaseModel):
    used: int
    limit: int | None
    remaining: int | None


class SpaceQuotaResponse(BaseModel):
    cellars: ResourceUsageResponse
    bottles: ResourceUsageResponse
    skus: ResourceUsageResponse


class AccountQuotaResponse(BaseModel):
    extra_spaces_allowance: int
    current_spaces: int
    max_spaces: int
    remaining_spaces: int
    can_create_collector: bool
    can_create_business: bool


class ContextWineCellarResponse(BaseModel):
    id: UUID
    name: str
    space_id: UUID


class UserContextResponse(BaseModel):
    spaces: list[ContextSpaceResponse]
    wine_cellars: list[ContextWineCellarResponse]
    account_quota: AccountQuotaResponse
