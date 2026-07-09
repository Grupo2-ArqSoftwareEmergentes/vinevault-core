from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from ..models.value_objects import DeviceCommandStatus


class AcknowledgeDeviceCommand(BaseModel):
    device_id: UUID
    command_id: UUID
    status: DeviceCommandStatus
    failure_reason: Optional[str] = None
    occurred_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("status")
    @classmethod
    def valid_ack_status(cls, v: DeviceCommandStatus) -> DeviceCommandStatus:
        allowed = {
            DeviceCommandStatus.SENT,
            DeviceCommandStatus.EXECUTED,
            DeviceCommandStatus.FAILED,
        }
        if v not in allowed:
            raise ValueError("status must be SENT, EXECUTED, or FAILED")
        return v

    def model_post_init(self, __context) -> None:
        if self.status == DeviceCommandStatus.FAILED and not self.failure_reason:
            raise ValueError("failure_reason is required when status is FAILED")
