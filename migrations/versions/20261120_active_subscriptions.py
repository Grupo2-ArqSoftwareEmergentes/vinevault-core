"""Active monthly subscriptions with simulated activation and cancel-at-period-end."""
from alembic import op

from app.subscriptions.infrastructure.database.models import ActiveSubscriptionORM


revision = "20261120_active_subscriptions"
down_revision = "20261120_user_preferred_language"
branch_labels = None
depends_on = None


def upgrade():
    ActiveSubscriptionORM.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    raise RuntimeError("Destructive downgrade disabled: restore a verified backup to avoid losing billing history")
