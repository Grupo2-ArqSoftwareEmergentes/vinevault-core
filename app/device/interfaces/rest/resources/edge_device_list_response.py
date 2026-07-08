from pydantic import BaseModel, Field
from typing import List

from .edge_device_response import EdgeDeviceResponse


class EdgeDeviceListResponse(BaseModel):
    items: List[EdgeDeviceResponse] = Field(default_factory=list)
    page: int
    size: int
    total: int
