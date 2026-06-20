from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class WineCellarORM(Base):
    __tablename__ = "wine_cellars"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("spaces.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    device_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("devices.id"),
        unique=True,
        nullable=True,
        index=True,
    )
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_domain(self) -> "WineCellar":
        from app.wine_cellar.domain.models import WineCellar

        return WineCellar(
            id=self.id,
            space_id=self.space_id,
            name=self.name,
            description=self.description,
            device_id=self.device_id,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )

    @classmethod
    def from_domain(cls, wine_cellar: "WineCellar") -> "WineCellarORM":
        return cls(
            id=wine_cellar.id,
            space_id=wine_cellar.space_id,
            name=wine_cellar.name,
            description=wine_cellar.description,
            device_id=wine_cellar.device_id,
            created_at=wine_cellar.created_at,
            updated_at=wine_cellar.updated_at,
        )
