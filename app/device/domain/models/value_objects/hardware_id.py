from pydantic import BaseModel, Field, field_validator
import re


class HardwareId(BaseModel):
    value: str = Field(..., min_length=1)

    @field_validator('value')
    @classmethod
    def validate_format(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Hardware ID must not be null or blank")
        
        # Supported formats: CLAIR-0KBG or HW-0001
        if not re.match(r'^(CLAIR-[0-9A-Z]{4}|HW-\d{4})$', v):
            raise ValueError("Hardware ID must match CLAIR-0KBG or HW-0001")
        return v