from uuid import UUID
from typing import Optional
from pydantic import BaseModel, Field


class GetDevicesBySpaceQuery(BaseModel):
    space_id: UUID
    page: Optional[int] = Field(default=0, ge=0)
    size: Optional[int] = Field(default=20, ge=1)