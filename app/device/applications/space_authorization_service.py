from enum import Enum
from uuid import UUID
from typing import Protocol

from app.device.domain.models.value_objects.space_access import SpaceRole


class SpacePermission(str, Enum):
    READ = "READ"
    CONFIGURE = "CONFIGURE"
    INVENTORY = "INVENTORY"
    ANALYZE = "ANALYZE"
    MANAGE = "MANAGE"


ALLOWED_ROLES = {
    SpacePermission.READ: frozenset(SpaceRole),
    SpacePermission.CONFIGURE: frozenset({SpaceRole.OWNER, SpaceRole.SOMMELIER}),
    SpacePermission.INVENTORY: frozenset({SpaceRole.OWNER, SpaceRole.SOMMELIER, SpaceRole.INVENTORY_CLERK}),
    SpacePermission.ANALYZE: frozenset({SpaceRole.OWNER, SpaceRole.SOMMELIER, SpaceRole.INVENTORY_CLERK}),
    SpacePermission.MANAGE: frozenset({SpaceRole.OWNER}),
}


class SpaceMembershipReader(Protocol):
    async def role_for(self, space_id: UUID, user_id: int) -> SpaceRole | None: ...


class SpaceAuthorizationService:
    def __init__(self, memberships: SpaceMembershipReader):
        self.memberships = memberships

    async def require(self, space_id: UUID, user_id: int, permission: SpacePermission) -> SpaceRole:
        role = await self.memberships.role_for(space_id, user_id)
        if role is None or role not in ALLOWED_ROLES[permission]:
            raise PermissionError("Insufficient permissions for this space")
        return role
