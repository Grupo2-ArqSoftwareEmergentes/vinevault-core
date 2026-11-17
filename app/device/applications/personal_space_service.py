from dataclasses import dataclass
from uuid import UUID

from app.device.domain.models import Space
from app.device.domain.models.value_objects import UserId
from app.device.domain.models.value_objects.space_access import SpaceType
from app.wine_cellar.domain.models import WineCellar


class OrganizationNotFoundError(ValueError):
    pass


class OrganizationAccessDeniedError(ValueError):
    pass


@dataclass(frozen=True)
class CreatedSpace:
    space: Space
    default_wine_cellar: WineCellar


class PersonalSpaceService:
    """Orchestrate Space and WineCellar creation through one transaction boundary."""

    def __init__(self, unit_of_work):
        self.unit_of_work = unit_of_work

    async def create(
        self, user_id: int, name: str, organization_id: UUID | None = None,
        space_type: SpaceType = SpaceType.COLLECTOR,
    ) -> CreatedSpace:
        async with self.unit_of_work as work:
            await work.organizations.lock_space_creation(user_id)
            await work.quotas.require_space_slot(user_id, space_type.value)
            if organization_id is None:
                organization = await work.organizations.resolve_personal_organization(user_id)
            else:
                organization = await work.organizations.find_by_id(organization_id)
                if organization is None:
                    raise OrganizationNotFoundError("Organization not found")
                if organization.owner_user_id.user_id != user_id:
                    raise OrganizationAccessDeniedError("Organization does not belong to user")

            space = await work.spaces.save(Space(
                name=name,
                organization_id=organization.id,
                owner_user_id=UserId(user_id=user_id),
                space_type=space_type,
            ))
            await work.members.add_owner(space.id, user_id)
            cellar = await work.wine_cellars.save(WineCellar.create_default(space.id))
        return CreatedSpace(space=space, default_wine_cellar=cellar)
