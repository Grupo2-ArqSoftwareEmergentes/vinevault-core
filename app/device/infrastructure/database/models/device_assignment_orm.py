from datetime import datetime
from typing import Optional, Dict, Any
import uuid

from sqlalchemy import DateTime, ForeignKey, JSON, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class DeviceAssignmentORM(Base):
    __tablename__ = "device_assignments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("devices.id"), unique=True, nullable=False)
    owner_user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    space_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("spaces.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="OFFLINE")
    configuration: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    claim_token: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, unique=True)
    activated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    device = relationship("DeviceORM", back_populates="assignment")

    def to_domain(self) -> "DeviceAssignment":
        from app.device.domain.models import DeviceAssignment
        from app.device.domain.models.value_objects import ClaimToken, DeviceStatus, UserId

        owner_user_id = UserId(user_id=int(self.owner_user_id)) if self.owner_user_id else None
        claim_token = ClaimToken(value=self.claim_token) if self.claim_token else None
        return DeviceAssignment(
            id=self.id,
            device=self.device.to_domain(),
            owner_user_id=owner_user_id,
            space_id=self.space_id,
            status=DeviceStatus(self.status),
            configuration=dict(self.configuration or {}),
            claim_token=claim_token,
            activated_at=self.activated_at,
            last_seen_at=self.last_seen_at,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )

    @classmethod
    def from_domain(cls, assignment: "DeviceAssignment") -> "DeviceAssignmentORM":
        return cls(
            id=assignment.id,
            device_id=assignment.device.id,
            owner_user_id=str(assignment.owner_user_id.user_id) if assignment.owner_user_id else None,
            space_id=assignment.space_id,
            status=assignment.status.value,
            configuration=dict(assignment.configuration or {}),
            claim_token=assignment.claim_token.value if assignment.claim_token else None,
            activated_at=assignment.activated_at,
            last_seen_at=assignment.last_seen_at,
            created_at=assignment.created_at,
            updated_at=assignment.updated_at,
        )
