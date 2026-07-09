from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel

from app.device.domain.models import AlertIncident
from app.device.domain.models.value_objects import AlertMetricType, AlertStatus, MetricThreshold


class AlertIncidentResponse(BaseModel):
    id: UUID
    device_id: UUID
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
    def from_domain(cls, incident: AlertIncident) -> "AlertIncidentResponse":
        return cls(
            id=incident.id,
            device_id=incident.device.id,
            assignment_id=incident.assignment_id,
            space_id=incident.space_id,
            metric=incident.metric,
            threshold_metric=incident.threshold_metric,
            threshold_value=incident.threshold_value,
            actual_value=incident.actual_value,
            message=incident.message,
            status=incident.status,
            occurred_at=incident.occurred_at,
            resolved_at=incident.resolved_at,
            created_at=incident.created_at,
            updated_at=incident.updated_at,
        )
