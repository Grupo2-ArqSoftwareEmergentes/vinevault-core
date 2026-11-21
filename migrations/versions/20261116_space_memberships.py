"""Space-scoped purpose, subscription and memberships; preserve existing identities/data."""
from alembic import op
from sqlalchemy import inspect, text

from app.core.database import Base
from app.device.infrastructure.database.models.space_member_orm import SpaceMemberORM

revision = "20261116_space_memberships"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    tables = set(inspect(connection).get_table_names())
    if not tables.intersection({"users", "spaces"}):
        Base.metadata.create_all(connection)
        return
    if not {"users", "spaces"}.issubset(tables):
        raise RuntimeError("Partial legacy schema: users and spaces must both exist")
    # Fail before modifying legacy data if ownership cannot be linked to a real identity.
    orphans = connection.scalar(text("""
        SELECT count(*) FROM spaces s
        WHERE NOT EXISTS (SELECT 1 FROM users u WHERE CAST(u.id AS text) = s.owner_user_id)
    """))
    if orphans:
        raise RuntimeError("Spaces with missing owner identities exist; reconcile them before migration")
    user_columns = {column["name"] for column in inspect(connection).get_columns("users")}
    if "full_name" not in user_columns:
        op.execute("ALTER TABLE users ADD COLUMN full_name VARCHAR(255) NOT NULL DEFAULT ''")
        op.execute("UPDATE users SET full_name = username")
    space_columns = {column["name"] for column in inspect(connection).get_columns("spaces")}
    definitions = {
        "space_type": ("COLLECTOR", "'COLLECTOR', 'BUSINESS'", "space_type", 9),
        "subscription_plan": ("FREE", "'FREE', 'PRO', 'BUSINESS'", "space_subscription_plan", 8),
        "subscription_status": ("ACTIVE", "'ACTIVE', 'EXPIRED'", "space_subscription_status", 7),
    }
    for column, (default, values, constraint, length) in definitions.items():
        if column not in space_columns:
            op.execute(f"ALTER TABLE spaces ADD COLUMN {column} VARCHAR({length}) NOT NULL DEFAULT '{default}'")
            op.create_check_constraint(constraint, "spaces", f"{column} IN ({values})")
    SpaceMemberORM.__table__.create(connection, checkfirst=True)
    op.execute("""
        INSERT INTO space_members (space_id, user_id, role)
        SELECT s.id, u.id, 'OWNER' FROM spaces s
        JOIN users u ON CAST(u.id AS text) = s.owner_user_id
        ON CONFLICT (space_id, user_id) DO NOTHING
    """)


def downgrade():
    # Membership removal would discard collaborators and change authorization semantics.
    raise RuntimeError("Destructive downgrade disabled; restore a verified backup to revert this migration")
