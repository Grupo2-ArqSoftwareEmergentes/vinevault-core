from datetime import datetime
from typing import Optional, Dict
from uuid import UUID

from pydantic import BaseModel, Field

from app.device.domain.models import Device, DeviceAssignment
from app.device.domain.models.value_objects import DeviceStatus


class EdgeDeviceResponse(BaseModel):
    id: UUID
    serial_number: str
    name: str
    factory_name: str
    hardware_id: str
    device_type: str
    assigned: bool
    status: Optional[DeviceStatus] = None
    space_id: Optional[UUID] = None
    owner_user_id: Optional[int] = None
    configuration: Dict[str, str] = Field(default_factory=dict)
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
        if assignment is None:
            return cls(
                id=device.id,
                serial_number=device.serial_number,
                name=device.name,
                factory_name=device.factory_name,
                hardware_id=device.hardware_id.value,
                device_type=device.device_type.value,
                assigned=False,
                configuration={},
                created_at=device.created_at,
                updated_at=device.updated_at,
            )

        return cls(
            id=device.id,
            serial_number=device.serial_number,
            name=device.name,
            factory_name=device.factory_name,
            hardware_id=device.hardware_id.value,
            device_type=device.device_type.value,
            assigned=True,
            status=assignment.status,
            space_id=assignment.space_id,
            owner_user_id=assignment.owner_user_id.user_id if assignment.owner_user_id else None,
            configuration=assignment.configuration,
            activated_at=assignment.activated_at,
            last_seen_at=assignment.last_seen_at,
            created_at=device.created_at,
            updated_at=device.updated_at,
        )
