from uuid import UUID
from app.device.domain.models.value_objects.space_access import SpaceRole


class SpaceNotFoundError(ValueError):
    pass


class SpaceAccessDeniedError(ValueError):
    pass


class SpaceHasDevicesError(ValueError):
    pass


class SpaceDeletionService:
    def __init__(self, unit_of_work):
        self.unit_of_work = unit_of_work

    async def delete(self, user_id: int, space_id: UUID) -> None:
        async with self.unit_of_work as work:
            # Lock the parent so new FK references cannot be inserted during deletion.
            space = await work.spaces.find_by_id(space_id, for_update=True)
            if space is None:
                raise SpaceNotFoundError("Space not found")
            if await work.members.role_for(space_id, user_id) != SpaceRole.OWNER:
                raise SpaceAccessDeniedError("Space does not belong to user")
            if await work.assignments.exists_by_space_id(space_id):
                raise SpaceHasDevicesError("Space has devices")
            await work.wine_cellars.delete_all_by_space_id(space_id)
            await work.spaces.delete(space_id)
