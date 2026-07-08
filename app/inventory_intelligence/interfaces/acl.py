from typing import Protocol, List, Optional
from uuid import UUID
from pydantic import BaseModel


class WineInventorySummary(BaseModel):
    wine_name: str
    wine_type: str
    age_years: int
    quantity: int


class DeviceStatusSummary(BaseModel):
    device_id: UUID
    serial_number: str
    status: str
    configuration: dict
    last_seen_at: Optional[str] = None


class WineCellarIntelligenceData(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    space_name: str
    inventory: List[WineInventorySummary]
    device: Optional[DeviceStatusSummary] = None


class InventoryDataFacade(Protocol):
    async def get_cellar_data_for_intelligence(self, wine_cellar_id: UUID) -> Optional[WineCellarIntelligenceData]:
        """
        Obtiene los datos mínimos necesarios de una bodega e inventario para enviarle a la IA,
        evitando romper la encapsulación de los bounded contexts existentes.
        """
        ...
