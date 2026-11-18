from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, field_serializer, model_validator


class OriginType(str, Enum):
    STORE = "STORE"
    GIFT = "GIFT"
    TRIP = "TRIP"
    SUPPLIER = "SUPPLIER"


Tag = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]


class WineItemDetails(BaseModel):
    """One optional detail schema shared by Collector and Business; omission means NULL."""
    model_config = ConfigDict(str_strip_whitespace=True, allow_inf_nan=False)

    winery: str | None = Field(default=None, max_length=255)
    vintage: str | None = Field(default=None, pattern=r"^(NV|[0-9]{4})$")
    physical_location: str | None = Field(default=None, max_length=255)
    country: str | None = Field(default=None, max_length=100)
    region: str | None = Field(default=None, max_length=255)
    appellation: str | None = Field(default=None, max_length=255)
    wine_type: str | None = Field(default=None, max_length=255)
    bottle_format: str | None = Field(default=None, max_length=50)
    aging: str | None = Field(default=None, max_length=255)
    alcohol_percentage: Decimal | None = Field(default=None, ge=0, le=100, max_digits=5, decimal_places=2)
    consumption_window: str | None = Field(default=None, max_length=255)
    purchase_price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    sale_price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    min_stock_alert: int | None = Field(default=None, ge=0, le=2147483647)
    supplier_name: str | None = Field(default=None, max_length=255)
    origin_type: OriginType | None = None
    purchase_date: date | None = None
    batch_invoice_number: str | None = Field(default=None, max_length=100)
    # Legacy technical metrics: never required by the simplified tasting form.
    rating: Decimal | None = Field(default=None, ge=1, le=100, max_digits=5, decimal_places=2)
    body_slider: Decimal | None = Field(default=None, ge=0, le=5, max_digits=3, decimal_places=2)
    acidity_slider: Decimal | None = Field(default=None, ge=0, le=5, max_digits=3, decimal_places=2)
    tannins_slider: Decimal | None = Field(default=None, ge=0, le=5, max_digits=3, decimal_places=2)
    aroma_tags: list[Tag] | None = Field(default=None, max_length=50)
    tasting_notes: str | None = Field(default=None, max_length=4000)
    occasion_notes: str | None = Field(default=None, max_length=4000)
    company_notes: str | None = Field(default=None, max_length=4000)
    would_buy_again: bool | None = None
    # Legacy age is optional; never infer a vintage from it.
    age_years: int | None = Field(default=None, ge=0, le=2147483647)

    @model_validator(mode="before")
    @classmethod
    def consistent_name_aliases(cls, value):
        if isinstance(value, dict) and "name" in value and "wine_name" in value:
            if value["name"] != value["wine_name"]:
                raise ValueError("Conflicting name and wine_name")
        if isinstance(value, dict) and "wine_name" in value:
            value = dict(value)
            value.setdefault("name", value.pop("wine_name"))
        return value

    @field_serializer(
        "purchase_price", "sale_price", "alcohol_percentage", "rating",
        "body_slider", "acidity_slider", "tannins_slider", when_used="json",
    )
    def serialize_decimal(self, value: Decimal | None) -> str | None:
        return format(value, ".2f") if value is not None else None

    @field_validator("vintage", mode="before")
    @classmethod
    def normalize_vintage(cls, value):
        if isinstance(value, bool):
            raise ValueError("Vintage must be a year or NV")
        if isinstance(value, int):
            return str(value)
        if isinstance(value, str):
            return value.strip().upper() or None
        return value

    @field_validator("origin_type", mode="before")
    @classmethod
    def normalize_origin(cls, value):
        if isinstance(value, str):
            aliases = {"TIENDA": "STORE", "REGALO": "GIFT", "VIAJE": "TRIP", "PROVEEDOR": "SUPPLIER"}
            normalized = value.strip().upper()
            return aliases.get(normalized, normalized) or None
        return value

    @field_validator(
        "winery", "physical_location", "country", "region", "appellation", "wine_type",
        "bottle_format", "aging", "consumption_window", "supplier_name", "batch_invoice_number",
        "tasting_notes", "occasion_notes", "company_notes", mode="before",
    )
    @classmethod
    def blank_optional_text_is_null(cls, value):
        if isinstance(value, str):
            return value.strip() or None
        return value
