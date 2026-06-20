from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel

from app.wine_cellar.domain.models import WineCellar


class WineCellarResponse(BaseModel):
    id: UUID
    space_id: UUID
    name: str
    description: Optional[str]
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
            device_id=wine_cellar.device_id,
            created_at=wine_cellar.created_at,
            updated_at=wine_cellar.updated_at,
        )
