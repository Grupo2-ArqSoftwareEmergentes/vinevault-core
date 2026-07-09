from datetime import datetime, timezone
from typing import Any, Optional
import uuid

from sqlalchemy import DateTime, ForeignKey, JSON, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


def _to_naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


class DeviceTelemetryORM(Base):
    __tablename__ = "device_telemetry"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False, index=True)
    assignment_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    space_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="edge")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    device = relationship("DeviceORM", back_populates="telemetry_records")

    def to_domain(self) -> "DeviceTelemetryRecord":
        from app.telemetry.domain.models import DeviceTelemetryRecord

        return DeviceTelemetryRecord(
            id=self.id,
            device=self.device.to_domain(),
            assignment_id=self.assignment_id,
            space_id=self.space_id,
            source=self.source,
            payload=dict(self.payload or {}),
            occurred_at=_to_naive_utc(self.occurred_at) or self.occurred_at,
            created_at=_to_naive_utc(self.created_at),
            updated_at=_to_naive_utc(self.updated_at),
        )

    @classmethod
    def from_domain(cls, record: "DeviceTelemetryRecord") -> "DeviceTelemetryORM":
        return cls(
            id=record.id,
            device_id=record.device.id,
            assignment_id=record.assignment_id,
            space_id=record.space_id,
            source=record.source,
            payload=dict(record.payload or {}),
            occurred_at=_to_naive_utc(record.occurred_at) or record.occurred_at,
            created_at=_to_naive_utc(record.created_at),
            updated_at=_to_naive_utc(record.updated_at),
        )
