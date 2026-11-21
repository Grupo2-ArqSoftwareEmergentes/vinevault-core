from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Optional, List, Dict
from pydantic import Field

from app.device.domain.models import DeviceAssignment
from app.device.domain.models.value_objects import DeviceStatus
from .device_threshold_response import DeviceThresholdResponse


class DeviceResponse(BaseModel):
    id: UUID
    serial_number: str
    name: str
    status: DeviceStatus
    is_online: bool = False
    space_id: Optional[UUID] = None
    cellar_id: UUID | None = None
    cellar_name: str | None = None
    owner_user_id: Optional[int] = None
    configuration: Dict[str, str] = Field(default_factory=dict)
    thresholds: List[DeviceThresholdResponse] = Field(default_factory=list)
    hardware_id: str
    device_type: str
    activated_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_assignment(cls, assignment: DeviceAssignment, last_telemetry_at: datetime | None = None, *, cellar: tuple[UUID, str] | None = None) -> "DeviceResponse":
        device = assignment.device
        status, online, seen = assignment.connection(last_telemetry_at)
        # Build thresholds
        thresholds = []
        from app.device.domain.models.value_objects import MetricThreshold, DeviceMetricThresholdConfiguration
        import json
        from decimal import Decimal
        
        for metric in MetricThreshold:
            config_json = assignment.find_configuration_value(f"threshold.{metric.value}")
            try:
                if config_json:
                    data = json.loads(config_json)
                    config = DeviceMetricThresholdConfiguration(
                        metric=metric,
                        value=Decimal(str(data["value"])),
                        enabled=data.get("enabled", True)
                    )
                else:
                    config = DeviceMetricThresholdConfiguration.default_for(metric)
                thresholds.append(DeviceThresholdResponse.from_config(config, device.id))
            except:
                pass

        return cls(
            id=device.id,
            serial_number=device.serial_number,
            name=device.name,
            status=status,
            is_online=online,
            space_id=assignment.space_id,
            cellar_id=cellar[0] if cellar else None,
            cellar_name=cellar[1] if cellar else None,
            owner_user_id=assignment.owner_user_id.user_id if assignment.owner_user_id else None,
            configuration=assignment.configuration,
            thresholds=thresholds,
            hardware_id=device.hardware_id.value,
            device_type=device.device_type.value,
            activated_at=assignment.activated_at,
            last_seen_at=seen,
            created_at=assignment.created_at,
            updated_at=assignment.updated_at
        )
