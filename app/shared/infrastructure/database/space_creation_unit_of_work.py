from sqlalchemy.ext.asyncio import AsyncSession

from app.device.infrastructure.database.repositories import OrganizationRepository, SpaceRepository
from app.wine_cellar.infrastructure.database.repositories import WineCellarRepository


class SpaceCreationUnitOfWork:
    """Own the commit/rollback for organization, space and initial cellar together."""

    def __init__(self, session: AsyncSession):
        self._session = session
        self.organizations = OrganizationRepository(session)
        self.spaces = SpaceRepository(session, auto_commit=False)
        self.wine_cellars = WineCellarRepository(session, auto_commit=False)

    async def __aenter__(self):
        self._transaction = self._session.begin()
        await self._transaction.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return await self._transaction.__aexit__(exc_type, exc_value, traceback)
