from typing import Protocol, Optional
from uuid import UUID

from app.device.domain.models import DeviceAssignment


class DeviceContextFacade(Protocol):
    async def get_assignment(self, device_id: UUID) -> Optional[DeviceAssignment]:
        ...


class ThresholdContextFacade(Protocol):
    ...
