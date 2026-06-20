from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class OrganizationORM(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_domain(self) -> "Organization":
        from app.device.domain.models import Organization
        from app.device.domain.models.value_objects import UserId

        return Organization(
            id=self.id,
            name=self.name,
            owner_user_id=UserId(user_id=int(self.owner_user_id)),
            created_at=self.created_at,
            updated_at=self.updated_at,
        )

    @classmethod
    def from_domain(cls, organization: "Organization") -> "OrganizationORM":
        return cls(
            id=organization.id,
            name=organization.name,
            owner_user_id=str(organization.owner_user_id.user_id),
            created_at=organization.created_at,
            updated_at=organization.updated_at,
        )
