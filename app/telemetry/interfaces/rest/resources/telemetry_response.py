from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel

from app.telemetry.domain.models import DeviceTelemetryRecord


class TelemetryRecordResponse(BaseModel):
    id: UUID
    device_id: UUID
    assignment_id: Optional[UUID] = None
    space_id: Optional[UUID] = None
    source: str
    payload: dict[str, Any]
    occurred_at: datetime
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_domain(cls, record: DeviceTelemetryRecord) -> "TelemetryRecordResponse":
        return cls(
            id=record.id,
            device_id=record.device.id,
            assignment_id=record.assignment_id,
            space_id=record.space_id,
            source=record.source,
            payload=record.payload,
            occurred_at=record.occurred_at,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

