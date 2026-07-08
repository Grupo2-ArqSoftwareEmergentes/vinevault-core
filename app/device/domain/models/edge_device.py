from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from .value_objects import ApiKey


class EdgeDevice(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str = Field(..., min_length=1)
    api_key: ApiKey
    active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def rotate_api_key(self, new_api_key: ApiKey) -> None:
        self.api_key = new_api_key
