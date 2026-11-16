from sqlalchemy.ext.asyncio import AsyncSession

from app.device.infrastructure.database.repositories import DeviceAssignmentRepository, SpaceRepository
from app.wine_cellar.infrastructure.database.repositories import WineCellarRepository
from app.device.infrastructure.database.repositories.space_member_repository import SpaceMemberRepository


class SpaceDeletionUnitOfWork:
    """Delete inventory, cellars and space with a single commit or full rollback."""

    def __init__(self, session: AsyncSession):
        self._session = session
        self.spaces = SpaceRepository(session, auto_commit=False)
        self.wine_cellars = WineCellarRepository(session, auto_commit=False)
        self.assignments = DeviceAssignmentRepository(session)
        self.members = SpaceMemberRepository(session)

    async def __aenter__(self):
        if not self._session.in_transaction():
            await self._session.begin()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        if exc_type is None:
            await self._session.commit()
        else:
            await self._session.rollback()
