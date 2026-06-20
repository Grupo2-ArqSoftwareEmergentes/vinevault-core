from pydantic import BaseModel, Field, field_validator


class GetDeviceByHardwareIdQuery(BaseModel):
    hardware_id: str = Field(..., min_length=1)

    @field_validator('hardware_id')
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Hardware ID must not be null or blank")
        return v