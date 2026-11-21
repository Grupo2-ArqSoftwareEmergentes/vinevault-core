from decimal import Decimal
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AssistantMode(str, Enum):
    CHAT = "CHAT"
    SOMMELIER_ANALYSIS = "SOMMELIER_ANALYSIS"


class HistoryMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class SpaceSummary(BaseModel):
    id: UUID
    name: str
    purpose: Literal["COLLECTOR", "BUSINESS"]


class CellarSummary(BaseModel):
    id: UUID
    name: str


class InventoryTotals(BaseModel):
    items: int
    bottles: int
    cellars: int
    purchase_value_known: Decimal
    items_missing_purchase_price: int
    sale_value_known: Decimal | None = None
    items_missing_sale_price: int | None = None


class ContextSummary(BaseModel):
    space: SpaceSummary
    cellar: CellarSummary | None = None
    space_totals: InventoryTotals
    scope_totals: InventoryTotals
    items_considered: int
    truncated: bool


class InventoryContext(BaseModel):
    summary: ContextSummary
    # Bounded SQL projections, not ORM entities or a full inventory dump.
    items: list[dict]


class AssistantUnavailableError(Exception):
    def __init__(self, code: str, message: str, status_code: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
