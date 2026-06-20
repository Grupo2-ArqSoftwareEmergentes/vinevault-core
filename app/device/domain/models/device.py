from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from uuid import UUID, uuid4

from .value_objects import HardwareId, ApiKey, DeviceType


class Device(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    serial_number: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    factory_name: str = Field(..., min_length=1)
    hardware_id: HardwareId
    api_key: ApiKey
    device_type: DeviceType
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def update_name(self, name: str) -> None:
        if not name or not name.strip():
            raise ValueError("Device name must not be null or blank")
        self.name = name.strip()

    def reset_name_to_factory_default(self) -> None:
        self.name = self.factory_name

    def rotate_api_key(self, new_api_key: ApiKey) -> None:
        self.api_key = new_api_key