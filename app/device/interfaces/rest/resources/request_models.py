# claim_device_request.py
from pydantic import BaseModel, Field, field_validator
from uuid import UUID
from app.device.domain.models.value_objects.space_access import SpaceType


class ClaimDeviceRequest(BaseModel):
    claim_token: str = Field(..., min_length=1, description="One-time claim token")
    space_id: UUID = Field(..., description="Target space owned by the authenticated user")
    cellar_id: UUID | None = Field(default=None, description="Optional unoccupied cellar in the target space")

    @field_validator('claim_token')
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Claim token must not be null or blank")
        return v


# pair_device_request.py
from pydantic import BaseModel, Field, field_validator


class PairDeviceRequest(BaseModel):
    hardware_id: str = Field(..., min_length=1)

    @field_validator('hardware_id')
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Hardware ID must not be null or blank")
        return v


# update_device_name_request.py
from pydantic import BaseModel, Field


class UpdateDeviceNameRequest(BaseModel):
    name: str = Field(..., min_length=1)


# create_organization_request.py
from pydantic import BaseModel, Field


class CreateOrganizationRequest(BaseModel):
    name: str = Field(..., min_length=1)


# create_space_request.py
from pydantic import BaseModel, Field


class CreateSpaceRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    space_type: SpaceType = SpaceType.COLLECTOR

    @field_validator("space_type", mode="before")
    @classmethod
    def normalize_space_type(cls, value):
        return value.upper() if isinstance(value, str) else value

    @field_validator("name")
    @classmethod
    def validate_space_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Space name must not be blank")
        return value.strip()


class OnboardSpaceRequest(CreateSpaceRequest):
    space_type: SpaceType


# update_organization_name_request.py
from pydantic import BaseModel, Field


class UpdateOrganizationNameRequest(BaseModel):
    name: str = Field(..., min_length=1)


# update_space_name_request.py
from pydantic import BaseModel, Field


class UpdateSpaceNameRequest(BaseModel):
    name: str = Field(..., min_length=1)


# update_device_threshold_request.py
from pydantic import BaseModel, Field
from decimal import Decimal
from typing import List
from app.device.domain.models.value_objects import MetricThreshold


class UpdateDeviceThresholdRequest(BaseModel):
    metric: MetricThreshold
    value: Decimal = Field(..., decimal_places=2, gt=0)
    enabled: bool = True


class UpdateDeviceThresholdsRequest(BaseModel):
    thresholds: List[UpdateDeviceThresholdRequest] = Field(default_factory=list)


# create_device_command_request.py
from pydantic import BaseModel
from typing import Optional
from app.device.domain.models.value_objects import DeviceCommandType, DeviceCommandStatus


class CreateDeviceCommandRequest(BaseModel):
    type: DeviceCommandType
    payload: Optional[str] = None


# acknowledge_device_command_request.py
from datetime import datetime
from typing import Optional


class AcknowledgeDeviceCommandRequest(BaseModel):
    device_id: UUID
    command_id: UUID
    status: DeviceCommandStatus
    failure_reason: Optional[str] = None
    occurred_at: Optional[datetime] = None

    @field_validator("status")
    @classmethod
    def valid_ack_status(cls, v: DeviceCommandStatus) -> DeviceCommandStatus:
        allowed = {
            DeviceCommandStatus.SENT,
            DeviceCommandStatus.EXECUTED,
            DeviceCommandStatus.FAILED,
        }
        if v not in allowed:
            raise ValueError("status must be SENT, EXECUTED, or FAILED")
        return v

    @field_validator("failure_reason")
    @classmethod
    def failure_reason_required_for_failed_status(cls, v: Optional[str], info) -> Optional[str]:
        status = info.data.get("status")
        if status == DeviceCommandStatus.FAILED and (v is None or not v.strip()):
            raise ValueError("failure_reason is required when status is FAILED")
        return v


# update_device_presence_status_request.py
from datetime import datetime
from typing import Optional
from app.device.domain.models.value_objects import DeviceStatus


class UpdateDevicePresenceStatusRequest(BaseModel):
    device_id: Optional[UUID] = None
    hardware_id: Optional[str] = Field(default=None, min_length=1)
    status: DeviceStatus
    occurred_at: Optional[datetime] = None

    @field_validator("hardware_id")
    @classmethod
    def not_blank(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("Hardware ID must not be null or blank")
        return v

    @field_validator("status")
    @classmethod
    def valid_presence_status(cls, v: DeviceStatus) -> DeviceStatus:
        allowed = {
            DeviceStatus.ONLINE,
            DeviceStatus.OFFLINE,
            DeviceStatus.STANDBY,
            DeviceStatus.ERROR,
        }
        if v not in allowed:
            raise ValueError("status must be ONLINE, OFFLINE, STANDBY, or ERROR")
        return v

    def model_post_init(self, __context) -> None:
        if self.device_id is None and self.hardware_id is None:
            raise ValueError("device_id or hardware_id is required")
