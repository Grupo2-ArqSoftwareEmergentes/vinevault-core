from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class InventoryExportData:
    space_id: UUID
    space_name: str
    purpose: str
    cellar_id: UUID | None
    cellar_name: str | None
    generated_at: datetime
    items: list[dict]

    @property
    def quantity(self) -> int:
        return sum(item["quantity"] for item in self.items)
