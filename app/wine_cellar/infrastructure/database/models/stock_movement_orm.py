from datetime import datetime
from uuid import UUID as DomainUUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.wine_cellar.domain.models.stock_movement import StockExitReason, StockMovement


class StockMovementORM(Base):
    __tablename__ = "wine_stock_movements"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="stock_movement_positive_quantity"),
        CheckConstraint("stock_before >= 0 AND stock_after >= 0 AND stock_before - stock_after = quantity", name="stock_movement_balance"),
    )

    id: Mapped[DomainUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    inventory_item_id: Mapped[DomainUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("wine_inventory_items.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    reason: Mapped[StockExitReason] = mapped_column(Enum(
        StockExitReason, native_enum=False, create_constraint=True, name="stock_exit_reason",
        values_callable=lambda values: [value.value for value in values],
    ), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    stock_before: Mapped[int] = mapped_column(Integer, nullable=False)
    stock_after: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    def to_domain(self) -> StockMovement:
        return StockMovement(**{field: getattr(self, field) for field in StockMovement.model_fields})
