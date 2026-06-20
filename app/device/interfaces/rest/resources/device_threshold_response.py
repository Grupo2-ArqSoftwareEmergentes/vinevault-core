from pydantic import BaseModel
from uuid import UUID
from decimal import Decimal
from datetime import datetime
from typing import Optional
import uuid
import hashlib

from app.device.domain.models.value_objects import MetricThreshold, DeviceMetricThresholdConfiguration


class DeviceThresholdResponse(BaseModel):
    id: UUID
    device_id: UUID
    metric: MetricThreshold
    metric_label: str
    metric_unit: str
    value: Decimal
    enabled: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_config(cls, config: DeviceMetricThresholdConfiguration, device_id: UUID) -> "DeviceThresholdResponse":
        # Generate synthetic ID from device_id + metric
        namespace = uuid.NAMESPACE_DNS
        synthetic_id = uuid.uuid5(namespace, f"{str(device_id)}:{config.metric.value}")
        
        return cls(
            id=synthetic_id,
            device_id=device_id,
            metric=config.metric,
            metric_label=config.metric.label(),
            metric_unit=config.metric.unit(),
            value=config.value,
            enabled=config.enabled,
            created_at=None,
            updated_at=None
        )
