from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SubscriptionIntentORM(Base):
    __tablename__ = "subscription_intents"
    __table_args__ = (
        UniqueConstraint("requester_user_id", "idempotency_key", name="subscription_intent_idempotency"),
        CheckConstraint("kind IN ('UPGRADE_PRO','EXTRA_SPACE')", name="subscription_intent_kind"),
        CheckConstraint("status IN ('PENDING_PAYMENT','CANCELLED','FULFILLED')", name="subscription_intent_status"),
        CheckConstraint("currency IN ('USD','PEN')", name="subscription_intent_currency"),
        CheckConstraint("quantity BETWEEN 1 AND 100 AND unit_amount >= 0 AND total_amount = unit_amount * quantity", name="subscription_intent_quote"),
        CheckConstraint("(kind = 'UPGRADE_PRO' AND space_id IS NOT NULL AND quantity = 1 AND target_plan IS NOT NULL AND target_plan = 'PRO') OR (kind = 'EXTRA_SPACE' AND space_id IS NULL AND cellar_id IS NULL AND target_plan IS NULL)", name="subscription_intent_scope"),
        Index("ix_subscription_intents_requester", "requester_user_id"),
        Index("uq_subscription_pending_upgrade", "space_id", unique=True, postgresql_where=text("kind = 'UPGRADE_PRO' AND status = 'PENDING_PAYMENT'")),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    requester_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    idempotency_key: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING_PAYMENT")
    space_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("spaces.id", ondelete="CASCADE"))
    cellar_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("wine_cellars.id", ondelete="SET NULL"))
    target_plan: Mapped[str | None] = mapped_column(String(10))
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    unit_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    catalog_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
