from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel

from app.wine_cellar.domain.models import WineCellar


class WineCellarResponse(BaseModel):
    id: UUID
    space_id: UUID
    name: str
    description: Optional[str]
    temperature_min: Decimal
    temperature_max: Decimal
    humidity_min: Decimal
    humidity_max: Decimal
    device_id: Optional[UUID]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    @classmethod
    def from_domain(cls, wine_cellar: WineCellar) -> "WineCellarResponse":
        return cls(
            id=wine_cellar.id,
            space_id=wine_cellar.space_id,
            name=wine_cellar.name,
            description=wine_cellar.description,
            temperature_min=wine_cellar.temperature_min,
            temperature_max=wine_cellar.temperature_max,
            humidity_min=wine_cellar.humidity_min,
            humidity_max=wine_cellar.humidity_max,
            device_id=wine_cellar.device_id,
            created_at=wine_cellar.created_at,
            updated_at=wine_cellar.updated_at,
        )

