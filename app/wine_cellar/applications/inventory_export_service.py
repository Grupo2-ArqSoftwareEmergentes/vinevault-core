from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.device.infrastructure.database.models.space_orm import SpaceORM
from app.subscriptions.infrastructure.database.entitlements import effective_tier
from app.wine_cellar.domain.models.inventory_export import InventoryExportData
from app.wine_cellar.infrastructure.database.models.wine_cellar_orm import WineCellarORM
from app.wine_cellar.infrastructure.database.models.wine_inventory_item_orm import WineInventoryItemORM


MAX_EXPORT_ITEMS = 10000


class InventoryExportNotFoundError(LookupError):
    pass


class InventoryExportTooLargeError(ValueError):
    pass


class InventoryExportService:
    """Read a tenant-filtered report snapshot after the route's membership guard."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def scope(self, space_id: UUID, cellar_id: UUID | None) -> tuple[SpaceORM, str]:
        """Validate space/cellar scope before expensive rendering or plan-feature checks."""
        space = await self.session.scalar(select(SpaceORM).where(SpaceORM.id == space_id))
        if space is None:
            raise InventoryExportNotFoundError("Space not found")
        if cellar_id is not None:
            cellar = await self.session.scalar(select(WineCellarORM.id).where(
                WineCellarORM.id == cellar_id, WineCellarORM.space_id == space_id,
            ))
            if cellar is None:
                raise InventoryExportNotFoundError("Wine cellar not found in this space")
        return space, await effective_tier(self.session, space)

    async def load(self, space_id: UUID, cellar_id: UUID | None, *, scope: tuple[SpaceORM, str] | None = None) -> InventoryExportData:
        space, _ = scope or await self.scope(space_id, cellar_id)
        cellar_name = None
        if cellar_id is not None:
            cellar = (await self.session.execute(select(WineCellarORM.name).where(
                WineCellarORM.id == cellar_id, WineCellarORM.space_id == space_id,
            ))).one_or_none()
            if cellar is None:
                raise InventoryExportNotFoundError("Wine cellar not found in this space")
            cellar_name = cellar.name
        item, cellar = WineInventoryItemORM, WineCellarORM
        fields = ("id", "wine_cellar_id", "wine_name", "winery", "vintage", "quantity", "physical_location",
                  "country", "region", "appellation", "wine_type", "age_years", "bottle_format", "aging",
                  "alcohol_percentage", "consumption_window", "purchase_price", "origin_type", "purchase_date",
                  "sale_price", "min_stock_alert", "supplier_name", "batch_invoice_number", "tasting_notes",
                  "occasion_notes", "company_notes", "would_buy_again")
        query = select(*(getattr(item, field).label(field) for field in fields), cellar.name.label("cellar_name")).join(
            cellar, item.wine_cellar_id == cellar.id,
        ).where(cellar.space_id == space_id)
        if cellar_id is not None:
            query = query.where(cellar.id == cellar_id)
        rows = (await self.session.execute(query.order_by(cellar.name, cellar.id, item.wine_name, item.id).limit(MAX_EXPORT_ITEMS + 1))).mappings().all()
        if len(rows) > MAX_EXPORT_ITEMS:
            raise InventoryExportTooLargeError(f"Export exceeds {MAX_EXPORT_ITEMS} items; select a smaller cellar")
        return InventoryExportData(space_id=space.id, space_name=space.name, purpose=space.space_type.value,
                                   cellar_id=cellar_id, cellar_name=cellar_name, generated_at=datetime.now(timezone.utc),
                                   items=[dict(row) for row in rows])
