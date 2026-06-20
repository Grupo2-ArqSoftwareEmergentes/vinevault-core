from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4
from pydantic import BaseModel, Field

from .value_objects import UserId


class Space(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str = Field(..., min_length=1)
    organization_id: UUID
    owner_user_id: UserId
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def update_name(self, name: str) -> None:
        if not name or not name.strip():
            raise ValueError("Space name must not be null or blank")
        self.name = name.strip()