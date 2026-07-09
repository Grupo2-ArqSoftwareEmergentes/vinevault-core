from typing import List, Optional
from uuid import UUID
import secrets

from app.device.domain.models import Device, DeviceAssignment, DeviceCommand
from app.device.domain.models.value_objects import HardwareId, ApiKey, DeviceType, ClaimToken, UserId, DeviceStatus, DeviceCommandStatus
from app.device.domain.commands import (
    AcknowledgeDeviceCommand, ClaimDeviceCommand, PairDeviceCommand, ResetDeviceAssignmentCommand,
    SeedDevicesCommand, UpdateDeviceNameCommand
)
from app.device.domain.services import DeviceCommandService
from app.device.infrastructure.database.repositories import (
    DeviceRepository, DeviceAssignmentRepository, SpaceRepository
)
from app.device.infrastructure.kafka import KafkaDeviceEventPublisher


class DeviceCommandServiceImpl(DeviceCommandService):
    def __init__(
        self,
        device_repo: DeviceRepository,
        assignment_repo: DeviceAssignmentRepository,
        space_repo: SpaceRepository,
        device_command_repo=None,
        device_event_publisher: KafkaDeviceEventPublisher | None = None,
    ):
        self._device_repo = device_repo
        self._assignment_repo = assignment_repo
        self._space_repo = space_repo
        self._device_command_repo = device_command_repo
        self._device_event_publisher = device_event_publisher

    async def handle_seed_devices(self, command: SeedDevicesCommand) -> List[Device]:
        expected_serial_numbers = [
            f"SN-{i:04d}" for i in range(command.start_index, command.start_index + command.count)
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
            await self._publish_device_changed(saved, status=DeviceStatus.OFFLINE, change_type="CREATED")
            seeded.append(saved)

        return seeded

    async def _generate_unique_hardware_id(self) -> str:
        alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        for _ in range(50):
            suffix = ''.join(secrets.choice(alphabet) for _ in range(4))
            candidate = f"VINE-{suffix}"
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
        assignment.ensure_default_thresholds()
        saved = await self._assignment_repo.save(assignment)
        await self._publish_assignment_changed(saved, change_type="CREATED")
        return saved

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
        saved = await self._assignment_repo.save(assignment)
        await self._publish_assignment_changed(saved, change_type="UPDATED")
        return saved

    async def handle_reset_device_assignment(self, command: ResetDeviceAssignmentCommand) -> None:
        assignment = await self._assignment_repo.find_by_device_id(command.device_id)
        if not assignment:
            raise ValueError("Device assignment not found")

        if assignment.owner_user_id is None or assignment.owner_user_id.user_id != command.user_id:
            raise PermissionError("Device does not belong to user")

        # Reset device name to factory default
        device = assignment.device
        device.reset_name_to_factory_default()
        saved_device = await self._device_repo.save(device)

        # Delete assignment
        await self._assignment_repo.delete(assignment)
        await self._publish_device_changed(
            saved_device,
            status=DeviceStatus.DECOMMISSIONED,
            change_type="DELETED",
        )

    async def handle_update_device_name(self, command: UpdateDeviceNameCommand) -> None:
        assignment = await self._assignment_repo.find_by_device_id(command.device_id)
        if not assignment:
            raise ValueError("Device assignment not found")

        if assignment.owner_user_id is None or assignment.owner_user_id.user_id != command.user_id:
            raise PermissionError("Device does not belong to user")

        device = assignment.device
        device.update_name(command.name)
        saved = await self._device_repo.save(device)
        await self._publish_assignment_changed(saved=assignment, device_override=saved, change_type="UPDATED")

    async def handle_acknowledge_device_command(self, command: AcknowledgeDeviceCommand) -> DeviceCommand:
        if self._device_command_repo is None:
            raise ValueError("Device command repository is not configured")

        assignment = await self._assignment_repo.find_by_device_id(command.device_id)
        if not assignment:
            raise ValueError("Device assignment not found")

        stored_command = await self._device_command_repo.find_by_id(command.command_id)
        if not stored_command:
            raise ValueError("Device command not found")
        if stored_command.device.id != command.device_id:
            raise PermissionError("Device command does not belong to device")

        if command.status == DeviceCommandStatus.SENT:
            stored_command.mark_sent(command.occurred_at)
        elif command.status == DeviceCommandStatus.EXECUTED:
            stored_command.mark_executed(command.occurred_at)
        elif command.status == DeviceCommandStatus.FAILED:
            stored_command.mark_failed(command.failure_reason or "Command failed", command.occurred_at)
        else:
            raise ValueError("Unsupported acknowledgement status")

        return await self._device_command_repo.save(stored_command)

    async def find_by_id(self, device_id: UUID) -> Optional[Device]:
        return await self._device_repo.find_by_id(device_id)

    async def find_by_hardware_id(self, hardware_id: str) -> Optional[Device]:
        return await self._device_repo.find_by_hardware_id(hardware_id)

    async def find_by_api_key(self, api_key: str) -> Optional[Device]:
        return await self._device_repo.find_by_api_key(api_key)

    async def _publish_device_changed(
        self,
        device: Device,
        *,
        status: DeviceStatus = DeviceStatus.OFFLINE,
        change_type: str = "UPSERT",
    ) -> None:
        if self._device_event_publisher is None:
            return
        await self._device_event_publisher.publish_device_changed(
            device,
            status=status,
            change_type=change_type,
        )

    async def _publish_assignment_changed(
        self,
        saved: DeviceAssignment,
        *,
        device_override: Device | None = None,
        status_override: DeviceStatus | None = None,
        change_type: str = "UPSERT",
    ) -> None:
        if self._device_event_publisher is None:
            return

        assignment = saved
        if device_override is not None:
            assignment = saved.model_copy(update={"device": device_override})

        await self._device_event_publisher.publish_assignment_changed(
            assignment,
            status_override=status_override,
            change_type=change_type,
        )


class IllegalStateError(Exception):
    pass
