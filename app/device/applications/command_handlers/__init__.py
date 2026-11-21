from .device_command_handler import DeviceCommandServiceImpl, IllegalStateError
from .alert_incident_handler import AlertIncidentServiceImpl
from app.device.domain.commands import AcknowledgeDeviceCommand
from app.device.domain.models import DeviceCommand
from app.device.domain.models.value_objects import DeviceCommandStatus
from .device_presence_command_handler import DevicePresenceCommandServiceImpl


class DeviceControlCommandServiceImpl:
    def __init__(self, assignment_repo, device_command_repo, device_event_publisher=None):
        self.assignment_repo = assignment_repo
        self.device_command_repo = device_command_repo
        self.device_event_publisher = device_event_publisher

    async def handle_acknowledge_device_command(
        self,
        command: AcknowledgeDeviceCommand,
        *,
        publish_event: bool = True,
    ) -> DeviceCommand:
        assignment = await self.assignment_repo.find_by_device_id(command.device_id)
        if not assignment:
            raise ValueError("Device assignment not found")

        stored_command = await self.device_command_repo.find_by_id(command.command_id)
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

        saved = await self.device_command_repo.save(stored_command)
        if publish_event and self.device_event_publisher is not None:
            await self.device_event_publisher.publish_device_command_acknowledged(
                saved,
                acknowledged_at=command.occurred_at,
            )
        return saved


class DeviceThresholdCommandServiceImpl:
    def __init__(self, assignment_repo):
        self.assignment_repo = assignment_repo


class OrganizationCommandServiceImpl:
    def __init__(self, organization_repo, space_repo, assignment_repo):
        self.organization_repo = organization_repo
        self.space_repo = space_repo
        self.assignment_repo = assignment_repo


class SpaceCommandServiceImpl:
    def __init__(self, space_repo, organization_repo, assignment_repo):
        self.space_repo = space_repo
        self.organization_repo = organization_repo
        self.assignment_repo = assignment_repo
