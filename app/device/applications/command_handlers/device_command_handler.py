from typing import List, Optional
from uuid import UUID
import secrets

from app.device.domain.models import Device, DeviceAssignment
from app.device.domain.models.value_objects import HardwareId, ApiKey, DeviceType, ClaimToken, UserId
from app.device.domain.commands import (
    ClaimDeviceCommand, PairDeviceCommand, ResetDeviceAssignmentCommand,
    SeedDevicesCommand, UpdateDeviceNameCommand
)
from app.device.domain.services import DeviceCommandService
from app.device.infrastructure.database.repositories import (
    DeviceRepository, DeviceAssignmentRepository, SpaceRepository
)


class DeviceCommandServiceImpl(DeviceCommandService):
    def __init__(
        self,
        device_repo: DeviceRepository,
        assignment_repo: DeviceAssignmentRepository,
        space_repo: SpaceRepository,
    ):
        self._device_repo = device_repo
        self._assignment_repo = assignment_repo
        self._space_repo = space_repo

    async def handle_seed_devices(self, command: SeedDevicesCommand) -> List[Device]:
        expected_serial_numbers = [
            f"SN-{i:04d}" for i in range(1, command.count + 1)
        ]

        # Find existing devices
        existing_devices = await self._device_repo.find_all_by_serial_numbers(
            expected_serial_numbers
        )
        existing_serials = {d.serial_number for d in existing_devices}

        seeded = []
        for serial_number in expected_serial_numbers:
            if serial_number in existing_serials:
                continue

            # Generate unique hardware ID
            hardware_id = await self._generate_unique_hardware_id()
            
            device = Device(
                serial_number=serial_number,
                name=f"Sensor {serial_number[3:]}",
                factory_name=f"Sensor {serial_number[3:]}",
                hardware_id=HardwareId(value=hardware_id),
                api_key=ApiKey.generate(),
                device_type=DeviceType(value="air-quality-v1")
            )
            saved = await self._device_repo.save(device)
            seeded.append(saved)

        return seeded

    async def _generate_unique_hardware_id(self) -> str:
        alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        for _ in range(50):
            suffix = ''.join(secrets.choice(alphabet) for _ in range(4))
            candidate = f"CLAIR-{suffix}"
            if not await self._device_repo.exists_by_hardware_id(candidate):
                return candidate
        raise RuntimeError("Unable to generate a unique hardware id after multiple attempts")

    async def handle_pair_device(self, command: PairDeviceCommand) -> DeviceAssignment:
        device = await self._device_repo.find_by_hardware_id(command.hardware_id)
        if not device:
            raise ValueError("Device not registered in factory inventory")

        existing_assignment = await self._assignment_repo.find_by_device_id(device.id)
        if existing_assignment:
            if existing_assignment.owner_user_id is not None:
                raise IllegalStateError("Device already paired")
            return existing_assignment

        assignment = DeviceAssignment(
            device=device,
            claim_token=ClaimToken.generate()
        )
        return await self._assignment_repo.save(assignment)

    async def handle_claim_device(self, command: ClaimDeviceCommand) -> DeviceAssignment:
        # Validate space ownership
        space = await self._space_repo.find_by_id(command.space_id)
        if not space:
            raise ValueError("Space not found")
        if space.owner_user_id.user_id != command.user_id:
            raise PermissionError("Space does not belong to user")

        # Find assignment by claim token
        assignment = await self._assignment_repo.find_by_claim_token(command.claim_token)
        if not assignment:
            raise ValueError("Invalid claim token")

        if assignment.owner_user_id is not None and assignment.owner_user_id.user_id != command.user_id:
            raise PermissionError("Device assignment belongs to another user")

        # Claim the device
            assignment.claim_to_space(command.space_id, UserId(user_id=command.user_id))
        return await self._assignment_repo.save(assignment)

    async def handle_reset_device_assignment(self, command: ResetDeviceAssignmentCommand) -> None:
        assignment = await self._assignment_repo.find_by_device_id(command.device_id)
        if not assignment:
            raise ValueError("Device assignment not found")

        if assignment.owner_user_id is None or assignment.owner_user_id.user_id != command.user_id:
            raise PermissionError("Device does not belong to user")

        # Reset device name to factory default
        device = assignment.device
        device.reset_name_to_factory_default()
        await self._device_repo.save(device)

        # Delete assignment
        await self._assignment_repo.delete(assignment)

    async def handle_update_device_name(self, command: UpdateDeviceNameCommand) -> None:
        assignment = await self._assignment_repo.find_by_device_id(command.device_id)
        if not assignment:
            raise ValueError("Device assignment not found")

        if assignment.owner_user_id is None or assignment.owner_user_id.user_id != command.user_id:
            raise PermissionError("Device does not belong to user")

        device = assignment.device
        device.update_name(command.name)
        await self._device_repo.save(device)

    async def find_by_id(self, device_id: UUID) -> Optional[Device]:
        return await self._device_repo.find_by_id(device_id)

    async def find_by_hardware_id(self, hardware_id: str) -> Optional[Device]:
        return await self._device_repo.find_by_hardware_id(hardware_id)

    async def find_by_api_key(self, api_key: str) -> Optional[Device]:
        return await self._device_repo.find_by_api_key(api_key)


class IllegalStateError(Exception):
    pass
