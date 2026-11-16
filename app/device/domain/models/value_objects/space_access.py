from enum import Enum


class SpaceType(str, Enum):
    COLLECTOR = "COLLECTOR"
    BUSINESS = "BUSINESS"


class SubscriptionPlan(str, Enum):
    FREE = "FREE"
    PRO = "PRO"
    BUSINESS = "BUSINESS"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class SpaceRole(str, Enum):
    OWNER = "OWNER"
    SOMMELIER = "SOMMELIER"
    WAITER = "WAITER"
    INVENTORY_CLERK = "INVENTORY_CLERK"
