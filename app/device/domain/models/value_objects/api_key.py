import secrets
from pydantic import BaseModel, Field, field_validator


class ApiKey(BaseModel):
    value: str = Field(..., min_length=1)

    @classmethod
    def generate(cls) -> 'ApiKey':
        """Generate a new API key (32 bytes URL-safe base64)"""
        return cls(value=secrets.token_urlsafe(32))

    @field_validator('value')
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("API key must not be null or blank")
        return v