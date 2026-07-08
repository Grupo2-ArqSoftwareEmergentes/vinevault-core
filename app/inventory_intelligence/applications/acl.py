from typing import Optional
from uuid import UUID

from app.wine_cellar.infrastructure.database.repositories import WineCellarRepository, WineInventoryRepository
from app.device.infrastructure.database.repositories import SpaceRepository
from app.device.interfaces.acl import DeviceContextFacade
from app.inventory_intelligence.interfaces.acl import (
    InventoryDataFacade,
    WineCellarIntelligenceData,
    WineInventorySummary,
    DeviceStatusSummary,
)


class InventoryDataFacadeImpl(InventoryDataFacade):
    def __init__(
        self,
        wine_cellar_repo: WineCellarRepository,
        wine_inventory_repo: WineInventoryRepository,
        space_repo: SpaceRepository,
        device_context_facade: DeviceContextFacade,
    ):
        self._wine_cellar_repo = wine_cellar_repo
        self._wine_inventory_repo = wine_inventory_repo
        self._space_repo = space_repo
        self._device_context_facade = device_context_facade

    async def get_cellar_data_for_intelligence(self, wine_cellar_id: UUID) -> Optional[WineCellarIntelligenceData]:
        # 1. Obtener la bodega de vino
        wine_cellar = await self._wine_cellar_repo.find_by_id(wine_cellar_id)
        if not wine_cellar:
            return None

        # 2. Obtener el space para sacar el nombre
        space = await self._space_repo.find_by_id(wine_cellar.space_id)
        space_name = space.name if space else "Espacio Desconocido"

        # 3. Obtener el inventario completo
        inventory_items = await self._wine_inventory_repo.find_all_by_wine_cellar_id(wine_cellar_id)
        inventory_summaries = [
            WineInventorySummary(
                wine_name=item.wine_name,
                wine_type=item.wine_type,
                age_years=item.age_years,
                quantity=item.quantity,
            )
            for item in inventory_items
        ]

        # 4. Obtener información del dispositivo vinculado si existe
        device_summary = None
        if wine_cellar.device_id:
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
            description=wine_cellar.description,
            space_name=space_name,
            inventory=inventory_summaries,
            device=device_summary,
        )
