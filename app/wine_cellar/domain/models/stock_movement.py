from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class StockExitReason(str, Enum):
    SALE = "sale"
    TASTING = "tasting"
    BREAKAGE = "breakage"
    UNCORKING = "uncorking"


class StockMovement(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    inventory_item_id: UUID
    user_id: int
    reason: StockExitReason
    quantity: int = Field(gt=0)
    stock_before: int = Field(ge=0)
    stock_after: int = Field(ge=0)
    notes: str | None = Field(default=None, max_length=4000)
    created_at: datetime | None = None
