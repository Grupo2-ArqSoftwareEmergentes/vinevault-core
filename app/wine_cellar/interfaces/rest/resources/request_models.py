from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class CreateWineCellarRequest(BaseModel):
    name: str = Field(..., min_length=1)
    description: Optional[str] = None

    @field_validator("name")
    @classmethod
    def not_blank_name(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Wine cellar name must not be null or blank")
        return value.strip()

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        return value or None


class UpdateWineCellarRequest(CreateWineCellarRequest):
    pass


class LinkWineCellarDeviceRequest(BaseModel):
    device_id: UUID
