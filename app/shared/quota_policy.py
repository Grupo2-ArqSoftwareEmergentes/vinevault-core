from dataclasses import dataclass


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
    if len(owned) >= 2 + extra:
        return False
    free_counts = {kind: sum(kind == space_type and plan == "FREE" for space_type, plan in owned) for kind in ("COLLECTOR", "BUSINESS")}
    free_counts[purpose] += 1
    return sum(max(0, count - 1) for count in free_counts.values()) <= extra


def cellar_limit(plan: str, extra: int) -> int:
    return (1 if plan == "FREE" else 3) + extra


def inventory_limit(plan: str, purpose: str) -> tuple[str, int | None]:
    resource = "bottles" if purpose == "COLLECTOR" else "skus"
    maximum = (50 if resource == "bottles" else 25) if plan == "FREE" else None
    return resource, maximum


def validate_inventory_growth(plan: str, purpose: str, before: InventoryUsage, after: InventoryUsage) -> None:
    resource, limit = inventory_limit(plan, purpose)
    current, previous = getattr(after, resource), getattr(before, resource)
    # Existing over-quota data can be corrected/reduced, but never grow further.
    if limit is not None and current > limit and current > previous:
        raise QuotaExceededError("ITEM_LIMIT_REACHED", "El espacio alcanzó el límite de inventario de su plan.", current, limit)
