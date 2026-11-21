"""Immutable product catalogue. Amounts are explicit monthly tariffs, not FX conversions."""
from dataclasses import asdict, dataclass, field, fields
from decimal import Decimal
from types import MappingProxyType
from .errors import SubscriptionError


CATALOG_VERSION = "2026-11-20"
COURTESY_PURPOSE_SLOTS = MappingProxyType({"COLLECTOR": 1, "BUSINESS": 1})
CYCLE_DAYS = 30
FEATURE_LABELS = MappingProxyType({
    "stock_analysis": "El análisis de stock con IA",
    "sommelier_analysis": "El análisis sommelier",
    "pdf_report": "El reporte PDF",
    "member_management": "La gestión de miembros",
    "advanced_alerts": "Las alertas avanzadas",
    "assistant_chat": "El asistente con IA",
    "autocomplete": "El autocompletado con IA",
})


@dataclass(frozen=True)
class PlanFeatures:
    autocomplete: bool = False
    assistant_chat: bool = False
    stock_analysis: bool = False
    sommelier_analysis: bool = False
    excel_export: bool = True
    pdf_report: bool = False

    def get(self, name: str, default: bool = False) -> bool:
        return getattr(self, name, default)

    def __iter__(self):
        return (field.name for field in fields(self))


FREE_FEATURES = PlanFeatures()
PRO_FEATURES = PlanFeatures(**dict.fromkeys(PlanFeatures.__dataclass_fields__, True))


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
    features: PlanFeatures
    ai_analysis_enabled: bool = field(init=False)

    def __post_init__(self):
        object.__setattr__(self, "ai_analysis_enabled", self.features.get("stock_analysis", False))


PLANS = MappingProxyType({
    ("COLLECTOR", "FREE"): PlanDefinition("COLLECTOR", "FREE", "SPACE", (Price("USD", Decimal("0.00")), Price("PEN", Decimal("0.00"))), PlanLimits(1, 50, None), FREE_FEATURES),
    ("BUSINESS", "FREE"): PlanDefinition("BUSINESS", "FREE", "SPACE", (Price("USD", Decimal("0.00")), Price("PEN", Decimal("0.00"))), PlanLimits(1, None, 25), FREE_FEATURES),
    ("COLLECTOR", "PRO"): PlanDefinition("COLLECTOR", "PRO", "SPACE", (Price("PEN", Decimal("29.99")),), PlanLimits(3, None, None), PRO_FEATURES),
    ("BUSINESS", "PRO"): PlanDefinition("BUSINESS", "PRO", "SPACE", (Price("PEN", Decimal("79.99")),), PlanLimits(3, None, None), PRO_FEATURES),
})
EXTRA_SPACE_PRICES = (Price("USD", Decimal("5.00")), Price("PEN", Decimal("20.00")))


def get_plan(purpose: str, tier: str) -> PlanDefinition:
    return PLANS[(purpose, tier)]


def feature_enabled(purpose: str, tier: str, feature: str) -> bool:
    return get_plan(purpose, tier).features.get(feature, False)


def require_feature(purpose: str, tier: str, feature: str) -> None:
    """Single gate for every plan-exclusive capability."""
    if not feature_enabled(purpose, tier, feature):
        label = FEATURE_LABELS.get(feature, "Esta función")
        raise SubscriptionError("PLAN_FEATURE_UNAVAILABLE", f"{label} requiere plan PRO.", 403)


def plans_with_feature(feature: str) -> list[tuple[str, str]]:
    return [(plan.purpose, plan.tier) for plan in PLANS.values() if plan.features.get(feature, False)]


def account_space_limit(extra: int) -> int:
    return sum(COURTESY_PURPOSE_SLOTS.values()) + extra


def price_in(prices: tuple[Price, ...], currency: str) -> Price:
    for price in prices:
        if price.currency == currency:
            return price
    raise ValueError("Currency is not available for this product")


def catalog() -> dict:
    return {
        "version": CATALOG_VERSION, "billing_mode": "PREPARATORY", "plan_scope": "SPACE",
        "courtesy_spaces": dict(COURTESY_PURPOSE_SLOTS),
        "cycle_days": CYCLE_DAYS, "simulated_payment_available": True, "activation_currency": "PEN",
        "plans": [asdict(plan) for plan in PLANS.values()],
        "addons": [{"code": "EXTRA_SPACE", "scope": "ACCOUNT", "unit": "SPACE_SLOT", "prices": [asdict(price) for price in EXTRA_SPACE_PRICES]}],
    }
