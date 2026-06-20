from typing import Optional
from uuid import UUID

from app.device.infrastructure.database.repositories import (
    DeviceAssignmentRepository,
    DeviceRepository,
    OrganizationRepository,
    SpaceRepository,
)
from app.device.domain.models import DeviceAssignment, Device


class DeviceQueryServiceImpl:
    def __init__(
        self,
        device_repo: DeviceRepository,
        assignment_repo: DeviceAssignmentRepository,
        organization_repo: Optional[OrganizationRepository] = None,
        space_repo: Optional[SpaceRepository] = None,
    ):
        self._device_repo = device_repo
        self._assignment_repo = assignment_repo
        self._organization_repo = organization_repo
        self._space_repo = space_repo

    async def find_assignment_by_device_id(self, device_id: UUID) -> Optional[DeviceAssignment]:
        return await self._assignment_repo.find_by_device_id(device_id)

    async def find_device_by_id(self, device_id: UUID) -> Optional[Device]:
        return await self._device_repo.find_by_id(device_id)


class DeviceStatusQueryServiceImpl:
    def __init__(self, assignment_repo: DeviceAssignmentRepository):
        self._assignment_repo = assignment_repo


class DeviceThresholdQueryServiceImpl:
    def __init__(self, assignment_repo: DeviceAssignmentRepository):
        self._assignment_repo = assignment_repo

    async def find_assignment_by_device_id(self, device_id: UUID) -> Optional[DeviceAssignment]:
        return await self._assignment_repo.find_by_device_id(device_id)


class DeviceCommandQueryServiceImpl:
    def __init__(self, assignment_repo: DeviceAssignmentRepository):
        self._assignment_repo = assignment_repo
