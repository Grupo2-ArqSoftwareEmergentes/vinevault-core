# claim_device_request.py
from pydantic import BaseModel, Field, field_validator
from uuid import UUID


class ClaimDeviceRequest(BaseModel):
    claim_token: str = Field(..., min_length=1, description="One-time claim token")
    space_id: UUID = Field(..., description="Target space owned by the authenticated user")

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
    name: str = Field(..., min_length=1)


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
from app.device.domain.models.value_objects import DeviceCommandType


class CreateDeviceCommandRequest(BaseModel):
    type: DeviceCommandType
    payload: Optional[str] = None
