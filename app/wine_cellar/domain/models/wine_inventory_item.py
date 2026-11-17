from datetime import datetime
from uuid import UUID, uuid4

from pydantic import Field, computed_field

from .wine_item_details import WineItemDetails


class WineInventoryItem(WineItemDetails):
    id: UUID = Field(default_factory=uuid4)
    wine_cellar_id: UUID
    name: str = Field(min_length=1, max_length=255)
    quantity: int = Field(default=0, ge=0, le=2147483647)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @computed_field
    @property
    def wine_name(self) -> str:
        """Legacy API name, backed by the same value, not a second inventory column."""
        return self.name

    def with_changes(self, changes: dict[str, object]) -> "WineInventoryItem":
        values = self.model_dump(exclude={"wine_name"})
        values.update(changes)
        return type(self).model_validate(values)
