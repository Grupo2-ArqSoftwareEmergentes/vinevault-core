from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
import uuid

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


def _to_naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


class AlertIncidentORM(Base):
    __tablename__ = "alert_incidents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False, index=True)
    assignment_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    space_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    metric: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    threshold_metric: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    threshold_value: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    actual_value: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="ACTIVE", index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    device = relationship("DeviceORM")

    def to_domain(self) -> "AlertIncident":
        from app.device.domain.models import AlertIncident
        from app.device.domain.models.value_objects import AlertMetricType, AlertStatus, MetricThreshold

        return AlertIncident(
            id=self.id,
            device=self.device.to_domain(),
            assignment_id=self.assignment_id,
            space_id=self.space_id,
            metric=AlertMetricType(self.metric),
            threshold_metric=MetricThreshold(self.threshold_metric),
            threshold_value=Decimal(str(self.threshold_value)),
            actual_value=Decimal(str(self.actual_value)),
            message=self.message,
            status=AlertStatus(self.status),
            occurred_at=_to_naive_utc(self.occurred_at) or self.occurred_at,
            resolved_at=_to_naive_utc(self.resolved_at),
            created_at=_to_naive_utc(self.created_at),
            updated_at=_to_naive_utc(self.updated_at),
        )

    @classmethod
    def from_domain(cls, incident: "AlertIncident") -> "AlertIncidentORM":
        return cls(
            id=incident.id,
            device_id=incident.device.id,
            assignment_id=incident.assignment_id,
            space_id=incident.space_id,
            metric=incident.metric.value,
            threshold_metric=incident.threshold_metric.value,
            threshold_value=incident.threshold_value,
            actual_value=incident.actual_value,
            message=incident.message,
            status=incident.status.value,
            occurred_at=_to_naive_utc(incident.occurred_at) or incident.occurred_at,
            resolved_at=_to_naive_utc(incident.resolved_at),
            created_at=_to_naive_utc(incident.created_at),
            updated_at=_to_naive_utc(incident.updated_at),
        )
