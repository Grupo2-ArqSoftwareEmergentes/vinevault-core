from sqlalchemy import Enum, ForeignKey, Index, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from uuid import UUID as DomainUUID

from app.core.database import Base
from app.device.domain.models.value_objects.space_access import SpaceRole


class SpaceMemberORM(Base):
    __tablename__ = "space_members"
    __table_args__ = (Index("ix_space_members_user_id", "user_id"),)

    space_id: Mapped[DomainUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("spaces.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[SpaceRole] = mapped_column(
        Enum(SpaceRole, native_enum=False, create_constraint=True, name="space_member_role"), nullable=False,
    )
