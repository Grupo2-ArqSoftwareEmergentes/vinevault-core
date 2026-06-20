from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator


class WineCellar(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    space_id: UUID
    name: str = Field(..., min_length=1)
    description: Optional[str] = None
    temperature_min: Decimal
    temperature_max: Decimal
    humidity_min: Decimal
    humidity_max: Decimal
    device_id: Optional[UUID] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @model_validator(mode="after")
    def validate_ranges(self) -> "WineCellar":
        if self.temperature_min > self.temperature_max:
            raise ValueError("Temperature minimum must be less than or equal to temperature maximum")
        if self.humidity_min > self.humidity_max:
            raise ValueError("Humidity minimum must be less than or equal to humidity maximum")
        return self

    def update(
        self,
        name: str,
        description: Optional[str],
        temperature_min: Decimal,
        temperature_max: Decimal,
        humidity_min: Decimal,
        humidity_max: Decimal,
    ) -> None:
        if not name or not name.strip():
            raise ValueError("Wine cellar name must not be null or blank")
        self.name = name.strip()
        self.description = description.strip() if isinstance(description, str) else description
        self.temperature_min = temperature_min
        self.temperature_max = temperature_max
        self.humidity_min = humidity_min
        self.humidity_max = humidity_max
        self.validate_ranges()

    def link_device(self, device_id: UUID) -> None:
        if device_id is None:
            raise ValueError("Device ID must not be null")
        self.device_id = device_id

    def unlink_device(self) -> None:
        self.device_id = None

