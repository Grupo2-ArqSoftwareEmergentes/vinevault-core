from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class WineCellar(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    space_id: UUID
    name: str = Field(..., min_length=1)
    description: Optional[str] = None
    device_id: Optional[UUID] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def update(self, name: str, description: Optional[str]) -> None:
        if not name or not name.strip():
            raise ValueError("Wine cellar name must not be null or blank")
        self.name = name.strip()
        self.description = description.strip() if isinstance(description, str) else description

    def link_device(self, device_id: UUID) -> None:
        if device_id is None:
            raise ValueError("Device ID must not be null")
        self.device_id = device_id

    def unlink_device(self) -> None:
        self.device_id = None
