from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class RecordDeviceTelemetryCommand(BaseModel):
    device_id: Optional[UUID] = None
    hardware_id: Optional[str] = Field(default=None, min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    occurred_at: Optional[datetime] = None
    source: str = Field(default="edge", min_length=1)

    @field_validator("hardware_id")
    @classmethod
    def not_blank(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not value.strip():
            raise ValueError("Hardware ID must not be null or blank")
        return value

    @field_validator("source")
    @classmethod
    def source_not_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Source must not be null or blank")
        return value.strip()

    @model_validator(mode="after")
    def validate_command(self) -> "RecordDeviceTelemetryCommand":
        if self.device_id is None and self.hardware_id is None:
            raise ValueError("device_id or hardware_id is required")
        if not self.payload:
            raise ValueError("payload must not be empty")
        return self

