from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class CreateWineCellarRequest(BaseModel):
    name: str = Field(..., min_length=1)
    description: Optional[str] = None
    temperature_min: Decimal = Field(...)
    temperature_max: Decimal = Field(...)
    humidity_min: Decimal = Field(...)
    humidity_max: Decimal = Field(...)

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

    @model_validator(mode="after")
    def validate_ranges(self) -> "CreateWineCellarRequest":
        if self.temperature_min > self.temperature_max:
            raise ValueError("Temperature minimum must be less than or equal to temperature maximum")
        if self.humidity_min > self.humidity_max:
            raise ValueError("Humidity minimum must be less than or equal to humidity maximum")
        return self


class UpdateWineCellarRequest(CreateWineCellarRequest):
    pass


class LinkWineCellarDeviceRequest(BaseModel):
    device_id: UUID

