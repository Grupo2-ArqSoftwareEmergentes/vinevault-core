from uuid import UUID

from pydantic import BaseModel


class ContextSpaceResponse(BaseModel):
    id: UUID
    name: str


class ContextWineCellarResponse(BaseModel):
    id: UUID
    name: str
    space_id: UUID


class UserContextResponse(BaseModel):
    spaces: list[ContextSpaceResponse]
    wine_cellars: list[ContextWineCellarResponse]
