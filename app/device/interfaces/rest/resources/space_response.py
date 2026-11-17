from datetime import datetime
from uuid import UUID
from pydantic import BaseModel

from app.device.domain.models import Space
from app.device.domain.models.value_objects.space_access import SpaceType, SubscriptionPlan, SubscriptionStatus


class SpaceResponse(BaseModel):
    id: UUID
    name: str
    organization_id: UUID
    owner_user_id: int
    space_type: SpaceType
    subscription_plan: SubscriptionPlan
    subscription_status: SubscriptionStatus
    extra_cellars_allowance: int
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_domain(cls, space: Space) -> "SpaceResponse":
        return cls(
            id=space.id,
            name=space.name,
            organization_id=space.organization_id,
            owner_user_id=space.owner_user_id.user_id,
            space_type=space.space_type,
            subscription_plan=space.subscription_plan,
            subscription_status=space.subscription_status,
            extra_cellars_allowance=space.extra_cellars_allowance,
            created_at=space.created_at,
            updated_at=space.updated_at,
        )
