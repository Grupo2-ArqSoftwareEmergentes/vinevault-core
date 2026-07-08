from datetime import datetime
import uuid

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class WineInventoryItemORM(Base):
    __tablename__ = "wine_inventory_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    wine_cellar_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("wine_cellars.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    wine_name: Mapped[str] = mapped_column(String(255), nullable=False)
    wine_type: Mapped[str] = mapped_column(String(255), nullable=False)
    age_years: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
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
        )
