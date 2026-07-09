from datetime import datetime
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from app.device.domain.models import Device


class DeviceTelemetryRecord(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    device: Device
    assignment_id: Optional[UUID] = None
    space_id: Optional[UUID] = None
    source: str = Field(default="edge", min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

