from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class DeviceCommandORM(Base):
    __tablename__ = "device_commands"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="PENDING")
    payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    executed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    device = relationship("DeviceORM", back_populates="commands")

    def to_domain(self) -> "DeviceCommand":
        from app.device.domain.models import DeviceCommand
        from app.device.domain.models.value_objects import DeviceCommandStatus, DeviceCommandType

        return DeviceCommand(
            id=self.id,
            device=self.device.to_domain(),
            type=DeviceCommandType(self.type),
            status=DeviceCommandStatus(self.status),
            payload=self.payload,
            sent_at=self.sent_at,
            executed_at=self.executed_at,
            failure_reason=self.failure_reason,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )

    @classmethod
    def from_domain(cls, command: "DeviceCommand") -> "DeviceCommandORM":
        return cls(
            id=command.id,
            device_id=command.device.id,
            type=command.type.value,
            status=command.status.value,
            payload=command.payload,
            sent_at=command.sent_at,
            executed_at=command.executed_at,
            failure_reason=command.failure_reason,
            created_at=command.created_at,
            updated_at=command.updated_at,
        )
