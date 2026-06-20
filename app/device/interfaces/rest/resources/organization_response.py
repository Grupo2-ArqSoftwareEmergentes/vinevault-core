from datetime import datetime
from uuid import UUID
from pydantic import BaseModel

from app.device.domain.models import Organization


class OrganizationResponse(BaseModel):
    id: UUID
    name: str
    owner_user_id: int
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_domain(cls, organization: Organization) -> "OrganizationResponse":
        return cls(
            id=organization.id,
            name=organization.name,
            owner_user_id=organization.owner_user_id.user_id,
            created_at=organization.created_at,
            updated_at=organization.updated_at,
        )
