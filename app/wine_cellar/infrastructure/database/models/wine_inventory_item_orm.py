from datetime import datetime, date
from decimal import Decimal
import uuid

from sqlalchemy import DateTime, Date, ForeignKey, Integer, String, Text, Numeric, Boolean, Enum, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, synonym
from app.wine_cellar.domain.models.wine_item_details import WineItemDetails, OriginType

from app.core.database import Base


class WineInventoryItemORM(Base):
    __tablename__ = "wine_inventory_items"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="wine_item_name_nonblank"),
        CheckConstraint("quantity >= 0", name="wine_item_quantity_nonnegative"),
        CheckConstraint("age_years >= 0", name="wine_item_age_nonnegative"),
        CheckConstraint("purchase_price >= 0 AND sale_price >= 0", name="wine_item_prices_nonnegative"),
        CheckConstraint("min_stock_alert >= 0", name="wine_item_min_stock_nonnegative"),
        CheckConstraint("alcohol_percentage BETWEEN 0 AND 100", name="wine_item_alcohol_range"),
        CheckConstraint("rating BETWEEN 1 AND 100", name="wine_item_rating_range"),
        CheckConstraint("body_slider BETWEEN 0 AND 5 AND acidity_slider BETWEEN 0 AND 5 AND tannins_slider BETWEEN 0 AND 5", name="wine_item_sliders_range"),
        CheckConstraint("jsonb_typeof(aroma_tags) = 'array'", name="wine_item_aroma_array"),
        CheckConstraint("vintage ~ '^(NV|[0-9]{4})$'", name="wine_item_vintage_format"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    wine_cellar_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("wine_cellars.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    wine_name: Mapped[str] = mapped_column("name", String(255), nullable=False)
    name = synonym("wine_name")
    wine_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    age_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    winery: Mapped[str | None] = mapped_column(String(255))
    vintage: Mapped[str | None] = mapped_column(String(4))
    physical_location: Mapped[str | None] = mapped_column(String(255))
    country: Mapped[str | None] = mapped_column(String(100))
    region: Mapped[str | None] = mapped_column(String(255))
    appellation: Mapped[str | None] = mapped_column(String(255))
    bottle_format: Mapped[str | None] = mapped_column(String(50))
    aging: Mapped[str | None] = mapped_column(String(255))
    alcohol_percentage: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    consumption_window: Mapped[str | None] = mapped_column(String(255))
    purchase_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    sale_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    min_stock_alert: Mapped[int | None] = mapped_column(Integer)
    supplier_name: Mapped[str | None] = mapped_column(String(255))
    origin_type: Mapped[OriginType | None] = mapped_column(Enum(OriginType, native_enum=False, create_constraint=True, name="wine_origin_type"))
    purchase_date: Mapped[date | None] = mapped_column(Date)
    batch_invoice_number: Mapped[str | None] = mapped_column(String(100))
    rating: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    body_slider: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    acidity_slider: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    tannins_slider: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    aroma_tags: Mapped[list[str] | None] = mapped_column(JSONB(none_as_null=True))
    occasion_notes: Mapped[str | None] = mapped_column(Text)
    company_notes: Mapped[str | None] = mapped_column(Text)
    would_buy_again: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_domain(self) -> "WineInventoryItem":
        from app.wine_cellar.domain.models import WineInventoryItem

        return WineInventoryItem(
            id=self.id,
            wine_cellar_id=self.wine_cellar_id,
            wine_name=self.wine_name,
            wine_type=self.wine_type,
            age_years=self.age_years,
            quantity=self.quantity,
            created_at=self.created_at,
            updated_at=self.updated_at,
            **{field: getattr(self, field) for field in WineItemDetails.model_fields if field not in {"wine_type", "age_years"}},
        )

    @classmethod
    def from_domain(cls, wine_item: "WineInventoryItem") -> "WineInventoryItemORM":
        return cls(
            id=wine_item.id,
            wine_cellar_id=wine_item.wine_cellar_id,
            wine_name=wine_item.wine_name,
            wine_type=wine_item.wine_type,
            age_years=wine_item.age_years,
            quantity=wine_item.quantity,
            created_at=wine_item.created_at,
            updated_at=wine_item.updated_at,
            **{field: getattr(wine_item, field) for field in WineItemDetails.model_fields if field not in {"wine_type", "age_years"}},
        )
