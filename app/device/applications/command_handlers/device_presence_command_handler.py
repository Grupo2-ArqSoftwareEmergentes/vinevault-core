import logging

from app.device.domain.commands import UpdateDevicePresenceStatusCommand
from app.device.domain.models import DeviceAssignment
from app.device.infrastructure.database.repositories import DeviceAssignmentRepository, DeviceRepository
from app.device.infrastructure.kafka import KafkaDeviceEventPublisher

logger = logging.getLogger(__name__)


class DevicePresenceCommandServiceImpl:
    def __init__(
        self,
        device_repo: DeviceRepository,
        assignment_repo: DeviceAssignmentRepository,
        device_event_publisher: KafkaDeviceEventPublisher | None = None,
    ):
        self._device_repo = device_repo
        self._assignment_repo = assignment_repo
        self._device_event_publisher = device_event_publisher

    async def handle_update_device_presence_status(
        self,
        command: UpdateDevicePresenceStatusCommand,
        *,
        publish_event: bool = True,
    ) -> DeviceAssignment:
        assignment = None

        if command.device_id is not None:
            assignment = await self._assignment_repo.find_by_device_id(command.device_id)
        elif command.hardware_id is not None:
            device = await self._device_repo.find_by_hardware_id(command.hardware_id.value)
            if device is not None:
                assignment = await self._assignment_repo.find_by_device_id(device.id)

        if assignment is None:
            logger.warning(
                "Device assignment not found for presence update device_id=%s hardware_id=%s status=%s occurred_at=%s",
                str(command.device_id) if command.device_id is not None else None,
                command.hardware_id.value if command.hardware_id is not None else None,
                command.status.value if hasattr(command.status, "value") else str(command.status),
                command.occurred_at.isoformat() if command.occurred_at else None,
            )
            raise ValueError("Device assignment not found")

        logger.info(
            "Updating device presence device_id=%s assignment_id=%s previous_status=%s new_status=%s occurred_at=%s",
            str(assignment.device.id),
            str(assignment.id),
            assignment.status.value,
            command.status.value,
            command.occurred_at.isoformat() if command.occurred_at else None,
        )
        assignment.update_presence(command.status, command.occurred_at)
        saved = await self._assignment_repo.save(assignment)
        logger.info(
            "Device presence updated and saved device_id=%s assignment_id=%s status=%s last_seen_at=%s",
            str(saved.device.id),
            str(saved.id),
            saved.status.value,
            saved.last_seen_at.isoformat() if saved.last_seen_at else None,
        )

        if publish_event and self._device_event_publisher is not None:
            await self._device_event_publisher.publish_device_presence_changed(
                saved.device,
                status=saved.status,
                occurred_at=command.occurred_at,
            )

        return saved
