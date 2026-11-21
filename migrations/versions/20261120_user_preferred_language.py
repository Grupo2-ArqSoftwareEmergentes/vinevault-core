"""Add preferred_language preference column to users with explicit es/en constraint."""
from alembic import op
import sqlalchemy as sa


revision = "20261120_user_preferred_language"
down_revision = "20261119_subscription_intents"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    columns = {entry["name"] for entry in inspector.get_columns("users")}
    if "preferred_language" not in columns:
        op.add_column(
            "users",
            sa.Column("preferred_language", sa.String(5), nullable=False, server_default="es"),
        )
    checks = {entry["name"] for entry in inspector.get_check_constraints("users")}
    if "user_preferred_language_valid" not in checks:
        op.create_check_constraint(
            "user_preferred_language_valid",
            "users",
            "preferred_language IN ('es', 'en')",
        )


def downgrade():
    raise RuntimeError("Destructive downgrade disabled: restore a verified backup to preserve user language preferences")
