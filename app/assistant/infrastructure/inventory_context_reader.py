import json
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.domain.models import CellarSummary, ContextSummary, InventoryContext, InventoryTotals, SpaceSummary
from app.wine_cellar.infrastructure.database.models.wine_cellar_orm import WineCellarORM as Cellar
from app.wine_cellar.infrastructure.database.models.wine_inventory_item_orm import WineInventoryItemORM as Item


MAX_ITEMS = 40
MAX_DETAIL_CHARACTERS = 12000


class SQLInventoryContextReader:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _totals(self, space: SpaceSummary, cellar: CellarSummary | None) -> InventoryTotals:
        scope = [Cellar.space_id == space.id]
        if cellar:
            scope.append(Cellar.id == cellar.id)
        columns = [
            func.count(Item.id).label("items"),
            func.coalesce(func.sum(Item.quantity), 0).label("bottles"),
            func.coalesce(func.sum(Item.purchase_price * Item.quantity), 0).label("purchase_value_known"),
            func.count(Item.id).filter(Item.purchase_price.is_(None)).label("items_missing_purchase_price"),
        ]
        if space.purpose == "BUSINESS":
            columns.extend([
                func.coalesce(func.sum(Item.sale_price * Item.quantity), 0).label("sale_value_known"),
                func.count(Item.id).filter(Item.sale_price.is_(None)).label("items_missing_sale_price"),
            ])
        row = (await self.session.execute(select(*columns).select_from(Item).join(Cellar, Item.wine_cellar_id == Cellar.id).where(*scope))).one()
        cellars = await self.session.scalar(select(func.count(Cellar.id)).where(*scope))
        return InventoryTotals(**dict(row._mapping), cellars=cellars)

    async def read(self, space: SpaceSummary, cellar: CellarSummary | None) -> InventoryContext:
        space_totals = await self._totals(space, None)
        scope_totals = await self._totals(space, cellar) if cellar else space_totals
        scope = [Cellar.space_id == space.id]
        if cellar:
            scope.append(Cellar.id == cellar.id)
        # Explicit SQL projection: bounded notes, no device credentials, no full ORM materialization.
        columns = [Item.id, Item.wine_cellar_id.label("cellar_id"), Item.wine_name.label("name"),
                   Item.winery, Item.vintage, Item.quantity, Item.wine_type, Item.purchase_price,
                   Item.consumption_window, func.left(Item.tasting_notes, 160).label("tasting_notes"),
                   func.left(Item.company_notes, 160).label("internal_notes")]
        if space.purpose == "BUSINESS":
            columns.extend([Item.sale_price, Item.min_stock_alert])
        rows = (await self.session.execute(select(*columns).select_from(Item).join(Cellar, Item.wine_cellar_id == Cellar.id)
                                          .where(*scope).order_by((Item.quantity > 0).desc(), Item.wine_name, Item.id).limit(MAX_ITEMS))).all()
        items, used = [], 0
        for row in rows:
            item = {key: str(value) if isinstance(value, Decimal) or key in {"id", "cellar_id"} else value
                    for key, value in row._mapping.items() if value is not None}
            size = len(json.dumps(item, ensure_ascii=False, separators=(",", ":")))
            if used + size > MAX_DETAIL_CHARACTERS:
                break
            items.append(item)
            used += size
        summary = ContextSummary(space=space, cellar=cellar, space_totals=space_totals, scope_totals=scope_totals,
                                 items_considered=len(items), truncated=len(items) < scope_totals.items)
        return InventoryContext(summary=summary, items=items)
