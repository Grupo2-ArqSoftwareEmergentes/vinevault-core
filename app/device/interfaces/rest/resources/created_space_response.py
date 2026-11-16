from app.wine_cellar.interfaces.rest.resources.wine_cellar_response import WineCellarResponse
from .space_response import SpaceResponse
from app.device.domain.models.value_objects.space_access import SpaceRole


class CreatedSpaceResponse(SpaceResponse):
    role: SpaceRole = SpaceRole.OWNER
    default_wine_cellar: WineCellarResponse
