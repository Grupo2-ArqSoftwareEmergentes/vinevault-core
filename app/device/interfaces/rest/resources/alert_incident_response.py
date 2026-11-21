from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, field_serializer

from app.device.domain.models import AlertIncident
from app.device.domain.models.value_objects import AlertMetricType, AlertStatus, MetricThreshold


class AlertIncidentResponse(BaseModel):
    id: UUID
    device_id: UUID
    device_name: str | None = None
    serial_number: str | None = None
    cellar_id: UUID | None = None
    cellar_name: str | None = None
    assignment_id: Optional[UUID] = None
    space_id: Optional[UUID] = None
    metric: AlertMetricType
    threshold_metric: MetricThreshold
    threshold_value: Decimal
    actual_value: Decimal
    message: str
    status: AlertStatus
    occurred_at: datetime
    resolved_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_domain(cls, incident: AlertIncident, *, cellar: tuple[UUID, str] | None = None, language: str = "en") -> "AlertIncidentResponse":
        metric = "Temperature" if incident.metric == AlertMetricType.TEMPERATURE else "Humidity"
        above = incident.threshold_metric.value.endswith("_max")
        if language == "es":
            metric = "Temperatura" if incident.metric == AlertMetricType.TEMPERATURE else "Humedad"
            reason = ("por encima del máximo" if above else "por debajo del mínimo") if incident.status == AlertStatus.ACTIVE else "dentro del rango configurado"
        else:
            reason = ("above configured maximum" if above else "below configured minimum") if incident.status == AlertStatus.ACTIVE else "back within configured range"
        return cls(
            id=incident.id,
            device_id=incident.device.id,
            device_name=incident.device.name,
            serial_number=incident.device.serial_number,
            cellar_id=cellar[0] if cellar else None,
            cellar_name=cellar[1] if cellar else None,
            assignment_id=incident.assignment_id,
            space_id=incident.space_id,
            metric=incident.metric,
            threshold_metric=incident.threshold_metric,
            threshold_value=incident.threshold_value,
            actual_value=incident.actual_value,
            message=f"{metric} {reason}",
            status=incident.status,
            occurred_at=incident.occurred_at,
            resolved_at=incident.resolved_at,
            created_at=incident.created_at,
            updated_at=incident.updated_at,
        )

    @field_serializer("threshold_value", "actual_value", when_used="json")
    def serialize_decimal(self, value: Decimal) -> str:
        return format(value.normalize(), "f")

    @field_serializer("occurred_at", "resolved_at", "created_at", "updated_at", when_used="json")
    def serialize_timestamp(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value).isoformat()
