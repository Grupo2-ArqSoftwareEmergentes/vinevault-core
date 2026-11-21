from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4
from pydantic import BaseModel, Field

from .device import Device
from .value_objects import DeviceCommandType, DeviceCommandStatus


class DeviceCommand(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    device: Device
    type: DeviceCommandType
    status: DeviceCommandStatus = DeviceCommandStatus.PENDING
    payload: Optional[str] = None
    sent_at: Optional[datetime] = None
    executed_at: Optional[datetime] = None
    failure_reason: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def mark_sent(self, sent_at: datetime | None = None) -> None:
        if self.status == DeviceCommandStatus.PENDING:
            self.status = DeviceCommandStatus.SENT
            self.sent_at = sent_at or datetime.utcnow()

    def mark_executed(self, executed_at: datetime | None = None) -> None:
        self.status = DeviceCommandStatus.EXECUTED
        self.executed_at = executed_at or datetime.utcnow()
        self.failure_reason = None

    def mark_failed(self, failure_reason: str, executed_at: datetime | None = None) -> None:
        self.status = DeviceCommandStatus.FAILED
        self.executed_at = executed_at or datetime.utcnow()
        self.failure_reason = failure_reason
