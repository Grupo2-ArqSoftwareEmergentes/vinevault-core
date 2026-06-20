from abc import ABC, abstractmethod
from typing import List, Optional
from uuid import UUID

from ..models import Device, DeviceAssignment
from ..commands import (
    ClaimDeviceCommand, PairDeviceCommand, ResetDeviceAssignmentCommand,
    SeedDevicesCommand, UpdateDeviceNameCommand
)


class DeviceCommandService(ABC):
    @abstractmethod
    async def handle_seed_devices(self, command: SeedDevicesCommand) -> List[Device]:
        pass

    @abstractmethod
    async def handle_pair_device(self, command: PairDeviceCommand) -> DeviceAssignment:
        pass

    @abstractmethod
    async def handle_claim_device(self, command: ClaimDeviceCommand) -> DeviceAssignment:
        pass

    @abstractmethod
    async def handle_reset_device_assignment(self, command: ResetDeviceAssignmentCommand) -> None:
        pass

    @abstractmethod
    async def handle_update_device_name(self, command: UpdateDeviceNameCommand) -> None:
        pass

    @abstractmethod
    async def find_by_id(self, device_id: UUID) -> Optional[Device]:
        pass

    @abstractmethod
    async def find_by_hardware_id(self, hardware_id: str) -> Optional[Device]:
        pass

    @abstractmethod
    async def find_by_api_key(self, api_key: str) -> Optional[Device]:
        pass