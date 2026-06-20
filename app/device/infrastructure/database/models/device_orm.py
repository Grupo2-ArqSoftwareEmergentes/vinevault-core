from sqlalchemy import String, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship, Mapped, mapped_column
from datetime import datetime
import uuid

from .base import Base


class DeviceORM(Base):
    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    serial_number: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    factory_name: Mapped[str] = mapped_column(String(255), nullable=False)
    hardware_id: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    api_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    device_type: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    assignment = relationship("DeviceAssignmentORM", back_populates="device", uselist=False)
    commands = relationship("DeviceCommandORM", back_populates="device")

    def to_domain(self) -> "Device":
        from app.device.domain.models import Device
        from app.device.domain.models.value_objects import HardwareId, ApiKey, DeviceType
        
        return Device(
            id=self.id,
            serial_number=self.serial_number,
            name=self.name,
            factory_name=self.factory_name,
            hardware_id=HardwareId(value=self.hardware_id),
            api_key=ApiKey(value=self.api_key),
            device_type=DeviceType(value=self.device_type),
            created_at=self.created_at,
            updated_at=self.updated_at
        )

    @classmethod
    def from_domain(cls, device: "Device") -> "DeviceORM":
        return cls(
            id=device.id,
            serial_number=device.serial_number,
            name=device.name,
            factory_name=device.factory_name,
            hardware_id=device.hardware_id.value,
            api_key=device.api_key.value,
            device_type=device.device_type.value,
            created_at=device.created_at,
            updated_at=device.updated_at
        )
