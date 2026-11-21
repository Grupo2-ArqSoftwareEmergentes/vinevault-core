"""Nullable tasting notes and backwards-compatible optional technical metrics."""
from alembic import op
import sqlalchemy as sa


revision = "20261118_simplified_tasting"
down_revision = "20261117_resource_quotas"
branch_labels = None
depends_on = None


def upgrade():
    table = "wine_inventory_items"
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}
    if "tasting_notes" not in columns:
        op.add_column(table, sa.Column("tasting_notes", sa.Text(), nullable=True))
    for name in (
        "rating", "body_slider", "acidity_slider", "tannins_slider", "aroma_tags",
        "tasting_notes", "company_notes", "would_buy_again",
    ):
        op.alter_column(table, name, nullable=True)


def downgrade():
    raise RuntimeError("Destructive downgrade disabled: restore a verified backup to avoid losing tasting notes")
