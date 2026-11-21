"""Device-facing cellar association facade; owns cellar persistence and validation."""
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.infrastructure.database.resource_quota_repository import ResourceQuotaRepository
from app.wine_cellar.domain.models import WineCellar
from app.wine_cellar.infrastructure.database.models.wine_cellar_orm import WineCellarORM
from app.wine_cellar.infrastructure.database.repositories.wine_cellar_repository import WineCellarRepository


class CellarDeviceLinkError(ValueError):
    def __init__(self, detail: str, status_code: int = 409):
        super().__init__(detail)
        self.status_code = status_code


class DeviceCellarACL:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.cellars = WineCellarRepository(session, auto_commit=False)

    async def prepare_link(self, cellar_id: UUID, space_id: UUID, *, device_id: UUID | None = None, require_available: bool = True) -> WineCellar:
        # Same lock ordering as other cellar writers: space, then resource.
        await ResourceQuotaRepository(self.session).lock_space(space_id)
        result = await self.session.execute(select(WineCellarORM).where(
            WineCellarORM.id == cellar_id
        ).with_for_update().execution_options(populate_existing=True))
        cellar = result.scalar_one_or_none()
        if cellar is None:
            raise CellarDeviceLinkError("Wine cellar not found", 404)
        if cellar.space_id != space_id:
            raise CellarDeviceLinkError("Wine cellar does not belong to the selected space")
        if require_available and cellar.device_id is not None and cellar.device_id != device_id:
            raise CellarDeviceLinkError("Wine cellar already has a linked device")
        return cellar.to_domain()

    async def link(self, cellar: WineCellar, device_id: UUID) -> None:
        existing = await self.cellars.find_by_device_id(device_id)
        if existing is not None and existing.id != cellar.id:
            raise CellarDeviceLinkError("Device is already linked to another wine cellar")
        cellar.link_device(device_id)
        await self.cellars.save(cellar)

    async def links_for_devices(self, device_ids: list[UUID], space_id: UUID | None) -> dict[UUID, tuple[UUID, str]]:
        if not device_ids or space_id is None:
            return {}
        rows = await self.session.execute(select(WineCellarORM.device_id, WineCellarORM.id, WineCellarORM.name).where(
            WineCellarORM.space_id == space_id, WineCellarORM.device_id.in_(device_ids)
        ))
        return {device_id: (cellar_id, name) for device_id, cellar_id, name in rows}
