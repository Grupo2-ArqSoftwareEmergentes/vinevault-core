from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ActiveSubscriptionORM(Base):
    """Paid/simulated monthly entitlement. Rows are never deleted on cancellation."""
    __tablename__ = "active_subscriptions"
    __table_args__ = (
        CheckConstraint("kind IN ('UPGRADE_PRO','EXTRA_SPACE')", name="active_subscription_kind"),
        CheckConstraint("status IN ('ACTIVE','EXPIRED')", name="active_subscription_status"),
        CheckConstraint("currency = 'PEN'", name="active_subscription_currency"),
        CheckConstraint("quantity BETWEEN 1 AND 100", name="active_subscription_quantity"),
        CheckConstraint("unit_amount >= 0 AND total_amount = unit_amount * quantity", name="active_subscription_quote"),
        CheckConstraint("current_period_end > started_at", name="active_subscription_period"),
        CheckConstraint("(kind = 'UPGRADE_PRO' AND space_id IS NOT NULL AND quantity = 1) OR (kind = 'EXTRA_SPACE' AND space_id IS NULL)", name="active_subscription_scope"),
        Index("ix_active_subscriptions_requester", "requester_user_id"),
        Index("ix_active_subscriptions_period_end", "current_period_end"),
        Index("uq_active_pro_subscription", "space_id", unique=True, postgresql_where=text("kind = 'UPGRADE_PRO' AND status = 'ACTIVE'")),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    requester_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    intent_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("subscription_intents.id", ondelete="SET NULL"), unique=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="ACTIVE")
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    space_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("spaces.id", ondelete="CASCADE"))
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="PEN")
    unit_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    current_period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    catalog_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    @property
    def monthly_amount(self) -> Decimal:
        return self.total_amount

    @property
    def access_until(self) -> datetime:
        return self.current_period_end

    @property
    def auto_renews(self) -> bool:
        return self.status == "ACTIVE" and not self.cancel_at_period_end
