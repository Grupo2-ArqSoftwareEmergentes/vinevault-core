from pydantic import Field, model_validator

from app.wine_cellar.domain.models.wine_item_details import WineItemDetails


class CreateWineInventoryItemRequest(WineItemDetails):
    name: str = Field(min_length=1, max_length=255)
    quantity: int = Field(default=0, ge=0, le=2147483647)


class UpdateWineInventoryItemRequest(WineItemDetails):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    quantity: int | None = Field(default=None, ge=0, le=2147483647)

    @model_validator(mode="after")
    def core_fields_cannot_be_cleared(self):
        for field in ("name", "quantity"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self
