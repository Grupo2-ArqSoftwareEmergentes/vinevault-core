from uuid import UUID

from app.wine_cellar.domain.models.stock_movement import StockExitReason, StockMovement


class InventoryItemNotFoundError(ValueError):
    pass


class InsufficientStockError(ValueError):
    pass


class InventoryStockService:
    def __init__(self, unit_of_work):
        self.unit_of_work = unit_of_work

    async def withdraw(
        self, cellar_id: UUID, item_id: UUID, user_id: int,
        quantity: int, reason: StockExitReason, notes: str | None,
    ) -> StockMovement:
        if quantity <= 0:
            raise ValueError("Outgoing quantity must be positive")
        async with self.unit_of_work as work:
            item = await work.inventory.find_by_id(item_id, for_update=True, wine_cellar_id=cellar_id)
            if item is None or item.wine_cellar_id != cellar_id:
                raise InventoryItemNotFoundError("Wine inventory item not found")
            if quantity > item.quantity:
                raise InsufficientStockError("Insufficient stock")
            movement = StockMovement(
                inventory_item_id=item.id, user_id=user_id, reason=reason, quantity=quantity,
                stock_before=item.quantity, stock_after=item.quantity - quantity, notes=notes,
            )
            await work.inventory.save(item.with_changes({"quantity": movement.stock_after}))
            saved = await work.movements.save(movement)
        return saved
