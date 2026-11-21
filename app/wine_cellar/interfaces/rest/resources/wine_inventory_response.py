from app.wine_cellar.domain.models import WineInventoryItem


class WineInventoryItemResponse(WineInventoryItem):
    @classmethod
    def from_domain(cls, wine_item: WineInventoryItem) -> "WineInventoryItemResponse":
        return cls.model_validate(wine_item.model_dump())
