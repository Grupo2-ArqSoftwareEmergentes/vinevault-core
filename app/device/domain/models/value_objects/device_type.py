from pydantic import BaseModel, Field, field_validator


class DeviceType(BaseModel):
    value: str = Field(..., min_length=1)

    @field_validator("value")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Device type must not be null or blank")
        return v.strip()
