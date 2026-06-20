from decimal import Decimal
from pydantic import BaseModel, Field, field_validator

from .metric_threshold import MetricThreshold


class DeviceMetricThresholdConfiguration(BaseModel):
    metric: MetricThreshold
    value: Decimal = Field(..., decimal_places=2)
    enabled: bool = True

    @field_validator('value')
    @classmethod
    def validate_value(cls, v: Decimal) -> Decimal:
        if v is None:
            raise ValueError("Value must not be null")
        if v < 0:
            raise ValueError("Value must not be negative")
        return v