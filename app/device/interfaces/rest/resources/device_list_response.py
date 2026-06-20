from pydantic import BaseModel, Field
from typing import List

from .device_response import DeviceResponse


class DeviceListResponse(BaseModel):
    items: List[DeviceResponse] = Field(default_factory=list)
    page: int
    size: int
    total: int
