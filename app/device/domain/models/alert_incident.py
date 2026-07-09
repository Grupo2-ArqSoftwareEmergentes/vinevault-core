from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from .device import Device
from .value_objects import AlertMetricType, AlertStatus, MetricThreshold


class AlertIncident(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    device: Device
    assignment_id: Optional[UUID] = None
    space_id: Optional[UUID] = None
    metric: AlertMetricType
    threshold_metric: MetricThreshold
    threshold_value: Decimal
    actual_value: Decimal
    message: str
    status: AlertStatus = AlertStatus.ACTIVE
    occurred_at: datetime
    resolved_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
