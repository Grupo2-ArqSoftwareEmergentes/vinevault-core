import secrets
import re
from pydantic import BaseModel, Field, field_validator


class ClaimToken(BaseModel):
    value: str = Field(..., min_length=1)

    @classmethod
    def generate(cls) -> 'ClaimToken':
        """Generate a short claim token in format AB45-F3B1"""
        bytes_data = secrets.token_bytes(4)
        hex_str = bytes_data.hex().upper()
        token = f"{hex_str[:4]}-{hex_str[4:8]}"
        return cls(value=token)

    @field_validator('value')
    @classmethod
    def validate_format(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Claim token must not be null or blank")
        
        # Short code format: AB45-F3B1 or legacy base64-url
        is_short_code = bool(re.match(r'^[A-Z0-9]{4}-[A-Z0-9]{4}$', v))
        is_legacy = bool(re.match(r'^[A-Za-z0-9_-]{20,}$', v))
        
        if not is_short_code and not is_legacy:
            raise ValueError("Claim token must match AB45-F3B1 format")
        return v