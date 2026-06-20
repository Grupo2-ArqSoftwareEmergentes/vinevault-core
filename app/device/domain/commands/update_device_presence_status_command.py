from uuid import UUID
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

from ..models.value_objects import DeviceStatus, HardwareId


class UpdateDevicePresenceStatusCommand(BaseModel):
    device_id: Optional[UUID] = None
    hardware_id: Optional[HardwareId] = None
    status: DeviceStatus
    occurred_at: datetime = Field(default_factory=datetime.utcnow)

    def model_post_init(self, __context) -> None:
        if self.device_id is None and self.hardware_id is None:
            raise ValueError("device_id or hardware_id is required")
        
        if self.status not in [DeviceStatus.ONLINE, DeviceStatus.OFFLINE, 
                               DeviceStatus.STANDBY, DeviceStatus.ERROR]:
            raise ValueError("status must be ONLINE, OFFLINE, STANDBY, or ERROR")