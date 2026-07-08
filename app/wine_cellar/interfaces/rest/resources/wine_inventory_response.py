from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel

from app.wine_cellar.domain.models import WineInventoryItem


class WineInventoryItemResponse(BaseModel):
    id: UUID
    wine_cellar_id: UUID
    wine_name: str
    wine_type: str
    age_years: int
    quantity: int
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    @classmethod
    def from_domain(cls, wine_item: WineInventoryItem) -> "WineInventoryItemResponse":
        return cls(
            id=wine_item.id,
            wine_cellar_id=wine_item.wine_cellar_id,
            wine_name=wine_item.wine_name,
            wine_type=wine_item.wine_type,
            age_years=wine_item.age_years,
            quantity=wine_item.quantity,
            created_at=wine_item.created_at,
            updated_at=wine_item.updated_at,
        )
