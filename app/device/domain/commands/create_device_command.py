from typing import Optional
from pydantic import BaseModel
from uuid import UUID

from ..models.value_objects import DeviceCommandType


class CreateDeviceCommand(BaseModel):
    device_id: UUID
    type: DeviceCommandType
    payload: Optional[str] = None
    user_id: int
