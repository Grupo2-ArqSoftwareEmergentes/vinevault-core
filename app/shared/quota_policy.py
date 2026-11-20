from dataclasses import dataclass
from app.subscriptions.domain.catalog import COURTESY_PURPOSE_SLOTS, account_space_limit, get_plan


class QuotaResourceNotFoundError(LookupError):
    pass


class QuotaExceededError(ValueError):
    def __init__(self, code: str, message: str, current: int, limit: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.current = current
        self.limit = limit


@dataclass(frozen=True)
class InventoryUsage:
    bottles: int
    skus: int


def can_create_space(owned: list[tuple[str, str]], extra: int, purpose: str) -> bool:
    if len(owned) >= account_space_limit(extra):
        return False
    free_counts = {kind: sum(kind == space_type and plan == "FREE" for space_type, plan in owned) for kind in ("COLLECTOR", "BUSINESS")}
    free_counts[purpose] += 1
    return sum(max(0, count - COURTESY_PURPOSE_SLOTS[kind]) for kind, count in free_counts.items()) <= extra


def cellar_limit(plan: str, extra: int, purpose: str = "COLLECTOR") -> int:
    return get_plan(purpose, plan).limits.cellars + extra


def inventory_limit(plan: str, purpose: str) -> tuple[str, int | None]:
    resource = "bottles" if purpose == "COLLECTOR" else "skus"
    maximum = getattr(get_plan(purpose, plan).limits, resource)
    return resource, maximum


def validate_inventory_growth(plan: str, purpose: str, before: InventoryUsage, after: InventoryUsage) -> None:
    resource, limit = inventory_limit(plan, purpose)
    current, previous = getattr(after, resource), getattr(before, resource)
    # Existing over-quota data can be corrected/reduced, but never grow further.
    if limit is not None and current > limit and current > previous:
        raise QuotaExceededError("ITEM_LIMIT_REACHED", "El espacio alcanzó el límite de inventario de su plan.", current, limit)
