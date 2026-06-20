from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.device.domain.models.value_objects import DeviceStatus


class DeviceStatusResponse(BaseModel):
    device_id: UUID
    status: DeviceStatus
    last_seen_at: datetime | None = None
