from datetime import datetime
import json
from decimal import Decimal
from typing import Optional, Dict, List
from uuid import UUID

from pydantic import BaseModel, Field

from app.device.domain.models import Device, DeviceAssignment
from app.device.domain.models.value_objects import DeviceStatus, MetricThreshold, DeviceMetricThresholdConfiguration
from .device_threshold_response import DeviceThresholdResponse


class EdgeDeviceResponse(BaseModel):
    id: UUID
    serial_number: str
    name: str
    factory_name: str
    hardware_id: str
    api_key: str
    device_type: str
    assigned: bool
    status: Optional[DeviceStatus] = None
    space_id: Optional[UUID] = None
    owner_user_id: Optional[int] = None
    claim_token: Optional[str] = None
    configuration: Dict[str, str] = Field(default_factory=dict)
    thresholds: List[DeviceThresholdResponse] = Field(default_factory=list)
    activated_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_device_and_assignment(
        cls,
        device: Device,
        assignment: DeviceAssignment | None = None,
    ) -> "EdgeDeviceResponse":
        thresholds = []
        configuration = {}
        status = None
        space_id = None
        owner_user_id = None
        claim_token = None
        activated_at = None
        last_seen_at = None

        if assignment is not None:
            configuration = assignment.configuration
            status = assignment.status
            space_id = assignment.space_id
            owner_user_id = assignment.owner_user_id.user_id if assignment.owner_user_id else None
            claim_token = assignment.claim_token.value if assignment.claim_token else None
            activated_at = assignment.activated_at
            last_seen_at = assignment.last_seen_at

            for metric in MetricThreshold:
                config_json = assignment.find_configuration_value(f"threshold.{metric.value}")
                try:
                    if config_json:
                        data = json.loads(config_json)
                        config = DeviceMetricThresholdConfiguration(
                            metric=metric,
                            value=Decimal(str(data["value"])),
                            enabled=data.get("enabled", True),
                        )
                    else:
                        config = DeviceMetricThresholdConfiguration.default_for(metric)
                    thresholds.append(DeviceThresholdResponse.from_config(config, device.id))
                except Exception:
                    pass

        if assignment is None:
            return cls(
                id=device.id,
                serial_number=device.serial_number,
                name=device.name,
                factory_name=device.factory_name,
                hardware_id=device.hardware_id.value,
                api_key=device.api_key.value,
                device_type=device.device_type.value,
                assigned=False,
                configuration=configuration,
                thresholds=thresholds,
                created_at=device.created_at,
                updated_at=device.updated_at,
            )

        return cls(
            id=device.id,
            serial_number=device.serial_number,
            name=device.name,
            factory_name=device.factory_name,
            hardware_id=device.hardware_id.value,
            api_key=device.api_key.value,
            device_type=device.device_type.value,
            assigned=True,
            status=status,
            space_id=space_id,
            owner_user_id=owner_user_id,
            claim_token=claim_token,
            configuration=configuration,
            thresholds=thresholds,
            activated_at=activated_at,
            last_seen_at=last_seen_at,
            created_at=device.created_at,
            updated_at=device.updated_at,
        )
