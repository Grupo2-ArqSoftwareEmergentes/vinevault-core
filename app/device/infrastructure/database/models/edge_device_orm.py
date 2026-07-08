from datetime import datetime
import uuid

from sqlalchemy import String, DateTime, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class EdgeDeviceORM(Base):
    __tablename__ = "edge_devices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    api_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_domain(self) -> "EdgeDevice":
        from app.device.domain.models import EdgeDevice
        from app.device.domain.models.value_objects import ApiKey

        return EdgeDevice(
            id=self.id,
            name=self.name,
            api_key=ApiKey(value=self.api_key),
            active=self.active,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )

    @classmethod
    def from_domain(cls, edge_device: "EdgeDevice") -> "EdgeDeviceORM":
        return cls(
            id=edge_device.id,
            name=edge_device.name,
            api_key=edge_device.api_key.value,
            active=edge_device.active,
            created_at=edge_device.created_at,
            updated_at=edge_device.updated_at,
        )
