from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.device.domain.models.value_objects import DeviceStatus
from app.device.domain.models import DeviceAssignment


class DeviceStatusResponse(BaseModel):
    device_id: UUID
    status: DeviceStatus
    last_seen_at: datetime | None = None
    is_online: bool = False

    @classmethod
    def from_assignment(cls, assignment: DeviceAssignment, last_telemetry_at: datetime | None = None):
        status, online, seen = assignment.connection(last_telemetry_at)
        return cls(device_id=assignment.device.id, status=status, is_online=online, last_seen_at=seen)
