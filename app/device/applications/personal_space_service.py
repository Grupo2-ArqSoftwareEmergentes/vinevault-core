from app.device.domain.models import Space
from app.device.domain.models.value_objects import UserId


class SpaceLimitReachedError(ValueError):
    pass


class PersonalSpaceService:
    def __init__(self, organization_repo, space_repo):
        self.organization_repo = organization_repo
        self.space_repo = space_repo

    async def create(self, user_id: int, name: str) -> Space:
        organization = await self.organization_repo.resolve_personal_organization(user_id)
        spaces = await self.space_repo.find_all_by_organization_id(organization.id)
        if len(spaces) >= organization.get_max_spaces():
            raise SpaceLimitReachedError("Organization reached max spaces")
        return await self.space_repo.save(Space(
            name=name,
            organization_id=organization.id,
            owner_user_id=UserId(user_id=user_id),
        ))
