"""Account space allowances and per-space cellar allowances; canonical FREE/PRO plans."""
from alembic import op
import sqlalchemy as sa

revision = "20261117_resource_quotas"
down_revision = "20261116_unified_wine_items"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    for table, column, constraint in (
        ("users", "extra_spaces_allowance", "user_extra_spaces_nonnegative"),
        ("spaces", "extra_cellars_allowance", "space_extra_cellars_nonnegative"),
    ):
        columns = {entry["name"] for entry in sa.inspect(connection).get_columns(table)}
        if column not in columns:
            op.add_column(table, sa.Column(column, sa.Integer(), nullable=False, server_default="0"))
        checks = {entry["name"] for entry in sa.inspect(connection).get_check_constraints(table)}
        if constraint not in checks:
            op.create_check_constraint(constraint, table, f"{column} >= 0")
    # BUSINESS was a legacy plan value, not the BUSINESS space purpose. Preserve paid entitlements.
    op.execute("UPDATE spaces SET subscription_plan = 'PRO' WHERE subscription_plan = 'BUSINESS'")
    checks = {entry["name"] for entry in sa.inspect(connection).get_check_constraints("spaces")}
    if "space_subscription_plan" in checks:
        op.drop_constraint("space_subscription_plan", "spaces", type_="check")
    op.alter_column("spaces", "subscription_plan", type_=sa.String(4))
    op.create_check_constraint("space_subscription_plan", "spaces", "subscription_plan IN ('FREE', 'PRO')")


def downgrade():
    raise RuntimeError("Destructive downgrade disabled; restore a verified backup to retain purchased allowances")
