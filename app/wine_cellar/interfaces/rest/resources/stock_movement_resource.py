from pydantic import BaseModel, Field, field_validator

from app.wine_cellar.domain.models.stock_movement import StockExitReason, StockMovement


class StockExitRequest(BaseModel):
    quantity: int = Field(gt=0, le=2147483647, strict=True)
    reason: StockExitReason
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class StockMovementResponse(StockMovement):
    pass
