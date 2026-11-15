from app.wine_cellar.interfaces.rest.resources.wine_cellar_response import WineCellarResponse
from .space_response import SpaceResponse


class CreatedSpaceResponse(SpaceResponse):
    default_wine_cellar: WineCellarResponse
