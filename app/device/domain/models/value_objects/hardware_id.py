from pydantic import BaseModel, Field, field_validator
import re


class HardwareId(BaseModel):
    value: str = Field(..., min_length=1)

    @field_validator('value')
    @classmethod
    def validate_format(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Hardware ID must not be null or blank")
        
        # Supported format: VINE-0KBG
        if not re.match(r'^(VINE-[0-9A-Z]{4}|HW-\d{4})$', v):
            raise ValueError("Hardware ID must match VINE-0KBG or HW-0001")
        return v
