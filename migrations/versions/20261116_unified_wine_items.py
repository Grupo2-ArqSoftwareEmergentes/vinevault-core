"""Unified nullable wine details and transactional stock exit history."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from app.wine_cellar.infrastructure.database.models.stock_movement_orm import StockMovementORM

revision = "20261116_unified_wine_items"
down_revision = "20261116_space_memberships"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    table = "wine_inventory_items"
    columns = {column["name"] for column in sa.inspect(connection).get_columns(table)}
    if "name" not in columns:
        op.alter_column(table, "wine_name", new_column_name="name")
    elif "wine_name" in columns:
        raise RuntimeError("Both name and wine_name columns exist; reconcile the duplicate values before migration")
    op.alter_column(table, "wine_type", nullable=True)
    op.alter_column(table, "age_years", nullable=True, server_default=None)

    additions = [
        ("winery", sa.String(255)), ("vintage", sa.String(4)),
        ("physical_location", sa.String(255)), ("country", sa.String(100)),
        ("region", sa.String(255)), ("appellation", sa.String(255)),
        ("bottle_format", sa.String(50)), ("aging", sa.String(255)),
        ("alcohol_percentage", sa.Numeric(5, 2)), ("consumption_window", sa.String(255)),
        ("purchase_price", sa.Numeric(12, 2)), ("sale_price", sa.Numeric(12, 2)),
        ("min_stock_alert", sa.Integer()), ("supplier_name", sa.String(255)),
        ("origin_type", sa.String(8)), ("purchase_date", sa.Date()),
        ("batch_invoice_number", sa.String(100)), ("rating", sa.Numeric(5, 2)),
        ("body_slider", sa.Numeric(3, 2)), ("acidity_slider", sa.Numeric(3, 2)),
        ("tannins_slider", sa.Numeric(3, 2)), ("aroma_tags", JSONB(none_as_null=True)),
        ("occasion_notes", sa.Text()), ("company_notes", sa.Text()), ("would_buy_again", sa.Boolean()),
    ]
    for name, column_type in additions:
        if name not in columns:
            op.add_column(table, sa.Column(name, column_type, nullable=True))

    checks = {
        "wine_item_name_nonblank": "length(trim(name)) > 0",
        "wine_item_quantity_nonnegative": "quantity >= 0",
        "wine_item_age_nonnegative": "age_years >= 0",
        "wine_item_prices_nonnegative": "purchase_price >= 0 AND sale_price >= 0",
        "wine_item_min_stock_nonnegative": "min_stock_alert >= 0",
        "wine_item_alcohol_range": "alcohol_percentage BETWEEN 0 AND 100",
        "wine_item_rating_range": "rating BETWEEN 1 AND 100",
        "wine_item_sliders_range": "body_slider BETWEEN 0 AND 5 AND acidity_slider BETWEEN 0 AND 5 AND tannins_slider BETWEEN 0 AND 5",
        "wine_item_aroma_array": "jsonb_typeof(aroma_tags) = 'array'",
        "wine_item_vintage_format": "vintage ~ '^(NV|[0-9]{4})$'",
        "wine_origin_type": "origin_type IN ('STORE', 'GIFT', 'TRIP', 'SUPPLIER')",
    }
    existing_checks = {check["name"] for check in sa.inspect(connection).get_check_constraints(table)}
    for name, condition in checks.items():
        if name not in existing_checks:
            op.create_check_constraint(name, table, condition)
    StockMovementORM.__table__.create(connection, checkfirst=True)


def downgrade():
    raise RuntimeError("Destructive downgrade disabled: restore a verified backup to avoid losing wine details and stock history")
