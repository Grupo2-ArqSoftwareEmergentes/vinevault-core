"""Immutable product catalogue. Amounts are explicit monthly tariffs, not FX conversions."""
from dataclasses import asdict, dataclass
from decimal import Decimal
from types import MappingProxyType
from .errors import SubscriptionError


CATALOG_VERSION = "2026-11-19"
COURTESY_PURPOSE_SLOTS = MappingProxyType({"COLLECTOR": 1, "BUSINESS": 1})


@dataclass(frozen=True)
class Price:
    currency: str
    amount: Decimal
    interval: str = "MONTH"


@dataclass(frozen=True)
class PlanLimits:
    cellars: int
    bottles: int | None
    skus: int | None


@dataclass(frozen=True)
class PlanDefinition:
    purpose: str
    tier: str
    scope: str
    prices: tuple[Price, ...]
    limits: PlanLimits
    ai_analysis_enabled: bool = True


PLANS = MappingProxyType({
    ("COLLECTOR", "FREE"): PlanDefinition("COLLECTOR", "FREE", "SPACE", (Price("USD", Decimal("0.00")), Price("PEN", Decimal("0.00"))), PlanLimits(1, 50, None)),
    ("BUSINESS", "FREE"): PlanDefinition("BUSINESS", "FREE", "SPACE", (Price("USD", Decimal("0.00")), Price("PEN", Decimal("0.00"))), PlanLimits(1, None, 25)),
    ("COLLECTOR", "PRO"): PlanDefinition("COLLECTOR", "PRO", "SPACE", (Price("PEN", Decimal("29.99")),), PlanLimits(3, None, None)),
    ("BUSINESS", "PRO"): PlanDefinition("BUSINESS", "PRO", "SPACE", (Price("PEN", Decimal("79.99")),), PlanLimits(3, None, None)),
})
EXTRA_SPACE_PRICES = (Price("USD", Decimal("5.00")), Price("PEN", Decimal("20.00")))


def get_plan(purpose: str, tier: str) -> PlanDefinition:
    return PLANS[(purpose, tier)]


def account_space_limit(extra: int) -> int:
    return sum(COURTESY_PURPOSE_SLOTS.values()) + extra


def require_analysis_feature(purpose: str, tier: str) -> None:
    if not get_plan(purpose, tier).ai_analysis_enabled:
        raise SubscriptionError("PLAN_FEATURE_UNAVAILABLE", "Analysis is not available for this plan", 403)


def price_in(prices: tuple[Price, ...], currency: str) -> Price:
    for price in prices:
        if price.currency == currency:
            return price
    raise ValueError("Currency is not available for this product")


def catalog() -> dict:
    return {
        "version": CATALOG_VERSION, "billing_mode": "PREPARATORY", "plan_scope": "SPACE",
        "courtesy_spaces": dict(COURTESY_PURPOSE_SLOTS),
        "plans": [asdict(plan) for plan in PLANS.values()],
        "addons": [{"code": "EXTRA_SPACE", "scope": "ACCOUNT", "unit": "SPACE_SLOT", "prices": [asdict(price) for price in EXTRA_SPACE_PRICES]}],
    }
