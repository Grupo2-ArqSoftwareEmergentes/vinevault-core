from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import DateTime, String, ForeignKey, Enum
from app.device.domain.models.value_objects.space_access import SpaceType, SubscriptionPlan, SubscriptionStatus
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class SpaceORM(Base):
    __tablename__ = "spaces"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    space_type: Mapped[SpaceType] = mapped_column(Enum(SpaceType, native_enum=False, create_constraint=True, name="space_type"), nullable=False, server_default="COLLECTOR")
    subscription_plan: Mapped[SubscriptionPlan] = mapped_column(Enum(SubscriptionPlan, native_enum=False, create_constraint=True, name="space_subscription_plan"), nullable=False, server_default="FREE")
    subscription_status: Mapped[SubscriptionStatus] = mapped_column(Enum(SubscriptionStatus, native_enum=False, create_constraint=True, name="space_subscription_status"), nullable=False, server_default="ACTIVE")
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_domain(self) -> "Space":
        from app.device.domain.models import Space
        from app.device.domain.models.value_objects import UserId

        return Space(
            id=self.id,
            name=self.name,
            organization_id=self.organization_id,
            owner_user_id=UserId(user_id=int(self.owner_user_id)),
            space_type=self.space_type,
            subscription_plan=self.subscription_plan,
            subscription_status=self.subscription_status,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )

    @classmethod
    def from_domain(cls, space: "Space") -> "SpaceORM":
        return cls(
            id=space.id,
            name=space.name,
            organization_id=space.organization_id,
            owner_user_id=str(space.owner_user_id.user_id),
            space_type=space.space_type,
            subscription_plan=space.subscription_plan,
            subscription_status=space.subscription_status,
            created_at=space.created_at,
            updated_at=space.updated_at,
        )
