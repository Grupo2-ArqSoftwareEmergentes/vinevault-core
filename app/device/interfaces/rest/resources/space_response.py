from datetime import datetime
from uuid import UUID
from pydantic import BaseModel

from app.device.domain.models import Space


class SpaceResponse(BaseModel):
    id: UUID
    name: str
    organization_id: UUID
    owner_user_id: int
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_domain(cls, space: Space) -> "SpaceResponse":
        return cls(
            id=space.id,
            name=space.name,
            organization_id=space.organization_id,
            owner_user_id=space.owner_user_id.user_id,
            created_at=space.created_at,
            updated_at=space.updated_at,
        )
