from pydantic import BaseModel, Field, field_validator
from uuid import UUID


class UpdateDeviceNameCommand(BaseModel):
    device_id: UUID
    name: str = Field(..., min_length=1)
    user_id: int

    @field_validator("name")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Device name must not be null or blank")
        return v.strip()
