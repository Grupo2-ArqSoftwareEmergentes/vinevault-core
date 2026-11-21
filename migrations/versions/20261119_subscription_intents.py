"""Preparatory subscription purchase intents; never grants entitlements or charges users."""
from alembic import op

from app.subscriptions.infrastructure.database.models import SubscriptionIntentORM


revision = "20261119_subscription_intents"
down_revision = "20261118_simplified_tasting"
branch_labels = None
depends_on = None


def upgrade():
    SubscriptionIntentORM.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    raise RuntimeError("Destructive downgrade disabled: restore a verified backup to avoid losing purchase intents")
