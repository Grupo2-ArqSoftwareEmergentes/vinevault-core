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


class ContextWineCellarResponse(BaseModel):
    id: UUID
    name: str
    space_id: UUID


class UserContextResponse(BaseModel):
    spaces: list[ContextSpaceResponse]
    wine_cellars: list[ContextWineCellarResponse]
