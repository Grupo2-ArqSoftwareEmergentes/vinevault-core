from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.device.interfaces.rest.resources.user_context_response import AccountQuotaResponse, SpaceQuotaResponse


class PriceResponse(BaseModel):
    currency: Literal["USD", "PEN"]
    amount: Decimal
    interval: Literal["MONTH"]

    @field_serializer("amount", when_used="json")
    def serialize_amount(self, value):
        return format(value, ".2f")


class PlanLimitsResponse(BaseModel):
    cellars: int
    bottles: int | None
    skus: int | None


class PlanResponse(BaseModel):
    purpose: Literal["COLLECTOR", "BUSINESS"]
    tier: Literal["FREE", "PRO"]
    scope: Literal["SPACE"]
    prices: list[PriceResponse]
    limits: PlanLimitsResponse
    ai_analysis_enabled: bool


class AddonResponse(BaseModel):
    code: Literal["EXTRA_SPACE"]
    scope: Literal["ACCOUNT"]
    unit: Literal["SPACE_SLOT"]
    prices: list[PriceResponse]


class CatalogResponse(BaseModel):
    version: str
    billing_mode: Literal["PREPARATORY"]
    plan_scope: Literal["SPACE"]
    courtesy_spaces: dict[str, int]
    cycle_days: int
    simulated_payment_available: bool
    activation_currency: Literal["PEN"]
    plans: list[PlanResponse]
    addons: list[AddonResponse]


class ActiveSubscriptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: Literal["UPGRADE_PRO", "EXTRA_SPACE"]
    status: Literal["ACTIVE", "EXPIRED"]
    cancel_at_period_end: bool
    currency: Literal["PEN"]
    quantity: int
    unit_amount: Decimal
    total_amount: Decimal
    monthly_amount: Decimal
    space_id: UUID | None
    started_at: datetime
    current_period_end: datetime
    access_until: datetime
    auto_renews: bool
    cancelled_at: datetime | None
    catalog_version: str

    @field_serializer("unit_amount", "total_amount", "monthly_amount", when_used="json")
    def serialize_amount(self, value):
        return format(value, ".2f")


class BillingSummaryResponse(BaseModel):
    currency: Literal["PEN"]
    cycle_days: int
    monthly_recurring_total: Decimal
    next_cycle_monthly_total: Decimal
    active_subscriptions: list[ActiveSubscriptionResponse]

    @field_serializer("monthly_recurring_total", "next_cycle_monthly_total", when_used="json")
    def serialize_total(self, value):
        return format(value, ".2f")


class SpaceSubscriptionResponse(BaseModel):
    id: UUID
    name: str
    purpose: Literal["COLLECTOR", "BUSINESS"]
    subscription_plan: Literal["FREE", "PRO"]
    subscription_status: Literal["ACTIVE", "EXPIRED"]
    role: str
    plan: PlanResponse
    extra_cellars_allowance: int
    can_manage_subscription: bool
    can_analyze: bool
    active_subscription: ActiveSubscriptionResponse | None
    quotas: SpaceQuotaResponse


class CellarSubscriptionResponse(BaseModel):
    id: UUID
    name: str
    inherits_space_plan: Literal[True]


class OverviewResponse(BaseModel):
    billing_mode: Literal["PREPARATORY"]
    account_quota: AccountQuotaResponse
    space: SpaceSubscriptionResponse | None
    cellar: CellarSubscriptionResponse | None
    billing: BillingSummaryResponse


class UpgradeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    space_id: UUID
    cellar_id: UUID | None = None
    target_plan: Literal["PRO"] = "PRO"
    currency: Literal["USD", "PEN"] = "PEN"
    idempotency_key: UUID
    confirm_simulated_payment: bool = False


class ExtraSpaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: Literal["USD", "PEN"] = "PEN"
    quantity: int = Field(default=1, strict=True, ge=1, le=100)
    idempotency_key: UUID
    confirm_simulated_payment: bool = False


class SubscriptionIntentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: Literal["UPGRADE_PRO", "EXTRA_SPACE"]
    status: Literal["PENDING_PAYMENT", "CANCELLED", "FULFILLED"]
    idempotency_key: UUID
    space_id: UUID | None
    cellar_id: UUID | None
    target_plan: Literal["PRO"] | None
    currency: Literal["USD", "PEN"]
    unit_amount: Decimal
    quantity: int
    total_amount: Decimal
    catalog_version: str
    created_at: datetime
    interval: Literal["MONTH"] = "MONTH"
    entitlement_scope: Literal["SPACE", "ACCOUNT"]
    billing_mode: Literal["PREPARATORY"] = "PREPARATORY"
    payment_mode: Literal["SIMULATED", "NONE"]
    entitlements_applied: bool
    subscription: ActiveSubscriptionResponse | None = None

    @field_serializer("unit_amount", "total_amount", when_used="json")
    def serialize_amount(self, value):
        return format(value, ".2f")

    @classmethod
    def from_intent(cls, intent, subscription=None):
        values = {field: getattr(intent, field) for field in cls.model_fields if hasattr(intent, field)}
        values["entitlement_scope"] = "SPACE" if intent.kind == "UPGRADE_PRO" else "ACCOUNT"
        values["entitlements_applied"] = intent.status == "FULFILLED"
        values["payment_mode"] = "SIMULATED" if intent.status == "FULFILLED" else "NONE"
        values["subscription"] = subscription
        return cls.model_validate(values)
