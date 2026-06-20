from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel

from app.device.domain.models import DeviceCommand
from app.device.domain.models.value_objects import DeviceCommandStatus, DeviceCommandType


class DeviceCommandResponse(BaseModel):
    id: UUID
    device_id: UUID
    type: DeviceCommandType
    status: DeviceCommandStatus
    payload: Optional[str] = None
    sent_at: Optional[datetime] = None
    executed_at: Optional[datetime] = None
    failure_reason: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_domain(cls, command: DeviceCommand) -> "DeviceCommandResponse":
        return cls(
            id=command.id,
            device_id=command.device.id,
            type=command.type,
            status=command.status,
            payload=command.payload,
            sent_at=command.sent_at,
            executed_at=command.executed_at,
            failure_reason=command.failure_reason,
            created_at=command.created_at,
            updated_at=command.updated_at,
        )
