from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4
from pydantic import BaseModel, Field

from .value_objects import UserId


class Organization(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str = Field(..., min_length=1)
    owner_user_id: UserId
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def update_name(self, name: str) -> None:
        if not name or not name.strip():
            raise ValueError("Organization name must not be null or blank")
        self.name = name.strip()

    def get_max_spaces(self) -> int:
        return 5

    def get_max_devices(self) -> int:
        return 10