from typing import Optional
from uuid import UUID

from app.device.applications.query_handlers import DeviceQueryServiceImpl, DeviceThresholdQueryServiceImpl
from app.device.domain.models import DeviceAssignment


class DeviceContextFacadeImpl:
    def __init__(self, device_query_service: DeviceQueryServiceImpl):
        self._device_query_service = device_query_service

    async def get_assignment(self, device_id: UUID) -> Optional[DeviceAssignment]:
        return await self._device_query_service.find_assignment_by_device_id(device_id)


class ThresholdContextFacadeImpl:
    def __init__(self, threshold_query_service: DeviceThresholdQueryServiceImpl, assignment_repo):
        self._threshold_query_service = threshold_query_service
        self._assignment_repo = assignment_repo
