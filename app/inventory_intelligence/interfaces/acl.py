from typing import Protocol, Optional
from uuid import UUID
from pydantic import BaseModel
from app.wine_cellar.domain.models.inventory_snapshot import InventorySnapshot
from app.wine_cellar.domain.models.inventory_snapshot import InventoryItemSummary as WineInventorySummary


class DeviceStatusSummary(BaseModel):
    device_id: UUID
    serial_number: str
    status: str
    configuration: dict
    last_seen_at: Optional[str] = None


class WineCellarIntelligenceData(InventorySnapshot):
    id: UUID
    name: str
    description: Optional[str] = None
    space_name: str
    device: Optional[DeviceStatusSummary] = None


class InventoryDataFacade(Protocol):
    async def get_cellar_data_for_intelligence(
        self, wine_cellar_id: UUID, *, include_device: bool = False,
    ) -> Optional[WineCellarIntelligenceData]:
        """
        Obtiene los datos mínimos necesarios de una bodega e inventario para enviarle a la IA,
        evitando romper la encapsulación de los bounded contexts existentes.
        """
        ...
