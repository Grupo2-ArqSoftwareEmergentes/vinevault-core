from pydantic import BaseModel, Field


class InventoryItemSummary(BaseModel):
    wine_name: str
    wine_type: str | None = None
    age_years: int | None = None
    vintage: str | None = None
    quantity: int


class InventoryCategorySummary(BaseModel):
    wine_type: str | None = None
    items: int
    quantity: int


class InventorySnapshot(BaseModel):
    item_count: int = 0
    total_quantity: int = 0
    min_age_years: int | None = None
    max_age_years: int | None = None
    inventory: list[InventoryItemSummary] = Field(default_factory=list)
    categories: list[InventoryCategorySummary] = Field(default_factory=list)
    other_items: int = 0
    other_quantity: int = 0
