from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class WineInventoryItem(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    wine_cellar_id: UUID
    wine_name: str = Field(..., min_length=1)
    wine_type: str = Field(..., min_length=1)
    age_years: int = Field(..., ge=0)
    quantity: int = Field(..., ge=0)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def update(self, wine_name: str, wine_type: str, age_years: int, quantity: int) -> None:
        if not wine_name or not wine_name.strip():
            raise ValueError("Wine name must not be null or blank")
        if not wine_type or not wine_type.strip():
            raise ValueError("Wine type must not be null or blank")
        if age_years < 0:
            raise ValueError("Wine age must be greater than or equal to zero")
        if quantity < 0:
            raise ValueError("Quantity must be greater than or equal to zero")

        self.wine_name = wine_name.strip()
        self.wine_type = wine_type.strip()
        self.age_years = age_years
        self.quantity = quantity
