from typing import Optional
from uuid import UUID

from app.wine_cellar.infrastructure.database.repositories import WineCellarRepository, WineInventoryRepository
from app.device.interfaces.acl import DeviceContextFacade
from app.inventory_intelligence.interfaces.acl import (
    InventoryDataFacade,
    WineCellarIntelligenceData,
    DeviceStatusSummary,
)


class InventoryDataFacadeImpl(InventoryDataFacade):
    def __init__(
        self,
        wine_cellar_repo: WineCellarRepository,
        wine_inventory_repo: WineInventoryRepository,
        device_context_facade: DeviceContextFacade,
    ):
        self._wine_cellar_repo = wine_cellar_repo
        self._wine_inventory_repo = wine_inventory_repo
        self._device_context_facade = device_context_facade

    async def get_cellar_data_for_intelligence(
        self, wine_cellar_id: UUID, *, include_device: bool = False,
    ) -> Optional[WineCellarIntelligenceData]:
        wine_cellar = await self._wine_cellar_repo.find_by_id(wine_cellar_id)
        if not wine_cellar:
            return None

        snapshot = await self._wine_inventory_repo.get_analysis_snapshot(wine_cellar_id)

        # Inventory-only requests never fetch device metadata.
        device_summary = None
        if snapshot.item_count and include_device and wine_cellar.device_id:
            assignment = await self._device_context_facade.get_assignment(wine_cellar.device_id)
            if assignment:
                # Filtrar la configuración de thresholds para enviar solo lo necesario
                filtered_config = {}
                if assignment.configuration:
                    for key, val in assignment.configuration.items():
                        if "threshold" in key:
                            filtered_config[key] = val

                device_summary = DeviceStatusSummary(
                    device_id=assignment.device.id,
                    serial_number=assignment.device.serial_number,
                    status=assignment.status.value,
                    configuration=filtered_config,
                    last_seen_at=assignment.last_seen_at.isoformat() if assignment.last_seen_at else None,
                )

        return WineCellarIntelligenceData(
            id=wine_cellar.id,
            name=wine_cellar.name,
            space_name="",
            **snapshot.model_dump(),
            device=device_summary,
        )
