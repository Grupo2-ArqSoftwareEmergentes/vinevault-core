from datetime import datetime

from fastapi.encoders import jsonable_encoder

from app.device.infrastructure.database.repositories import DeviceAssignmentRepository, DeviceRepository
from app.device.infrastructure.kafka import KafkaDeviceEventPublisher
from app.device.applications.command_handlers import AlertIncidentServiceImpl
from app.telemetry.domain.commands import RecordDeviceTelemetryCommand
from app.telemetry.domain.models import DeviceTelemetryRecord
from app.telemetry.infrastructure.database.repositories import TelemetryRepository


class TelemetryCommandServiceImpl:
    def __init__(
        self,
        device_repo: DeviceRepository,
        assignment_repo: DeviceAssignmentRepository,
        telemetry_repo: TelemetryRepository,
        device_event_publisher: KafkaDeviceEventPublisher | None = None,
        alert_incident_service: AlertIncidentServiceImpl | None = None,
    ):
        self._device_repo = device_repo
        self._assignment_repo = assignment_repo
        self._telemetry_repo = telemetry_repo
        self._device_event_publisher = device_event_publisher
        self._alert_incident_service = alert_incident_service

    async def handle_record_device_telemetry(
        self,
        command: RecordDeviceTelemetryCommand,
        *,
        publish_event: bool = True,
    ) -> DeviceTelemetryRecord:
        device = None
        if command.device_id is not None:
            device = await self._device_repo.find_by_id(command.device_id)
        elif command.hardware_id is not None:
            device = await self._device_repo.find_by_hardware_id(command.hardware_id)

        if device is None:
            raise ValueError("Device not found")

        assignment = await self._assignment_repo.find_by_device_id(device.id)
        occurred_at = command.occurred_at or datetime.utcnow()
        record = DeviceTelemetryRecord(
            device=device,
            assignment_id=assignment.id if assignment else None,
            space_id=assignment.space_id if assignment else None,
            source=command.source,
            payload=jsonable_encoder(command.payload),
            occurred_at=occurred_at,
        )
        saved = await self._telemetry_repo.save(record)
        if self._alert_incident_service is not None:
            await self._alert_incident_service.evaluate_telemetry(saved, assignment=assignment)
        if publish_event and self._device_event_publisher is not None:
            await self._device_event_publisher.publish_device_telemetry_recorded(
                saved,
                occurred_at=occurred_at,
            )
        return saved
