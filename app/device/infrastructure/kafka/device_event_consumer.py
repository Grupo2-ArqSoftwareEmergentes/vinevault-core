import asyncio
import json
import logging
from contextlib import suppress
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from app.core.database import AsyncSessionLocal
from app.device.applications.command_handlers import DeviceControlCommandServiceImpl
from app.device.applications.command_handlers.alert_incident_handler import AlertIncidentServiceImpl
from app.device.applications.command_handlers.device_presence_command_handler import DevicePresenceCommandServiceImpl
from app.device.infrastructure.database.repositories import (
    AlertIncidentRepository,
    DeviceAssignmentRepository,
    DeviceCommandRepository,
    DeviceRepository,
)
from app.device.domain.models.value_objects import DeviceStatus, HardwareId
from app.shared.infrastructure.database.repositories import IntegrationOutboxRepository
from app.telemetry.applications.command_handlers import TelemetryCommandServiceImpl
from app.telemetry.infrastructure.database.repositories import TelemetryRepository

from .device_event_publisher import (
    DEVICE_COMMAND_ACKNOWLEDGED_TOPIC,
    DEVICE_PRESENCE_CHANGED_TOPIC,
    DEVICE_TELEMETRY_RECORDED_TOPIC,
    DEVICE_SYNC_REQUESTED_TOPIC,
    KafkaDeviceEventPublisher,
)

logger = logging.getLogger(__name__)


class KafkaEdgeEventConsumer:
    def __init__(
        self,
        bootstrap_servers: str,
        *,
        group_id: str,
        device_event_publisher: KafkaDeviceEventPublisher | None = None,
    ) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._group_id = group_id
        self._device_event_publisher = device_event_publisher
        self._consumer: Optional[object] = None
        self._task: Optional[asyncio.Task[None]] = None
        self._started = False

    @property
    def is_enabled(self) -> bool:
        return bool(self._bootstrap_servers.strip())

    async def start(self) -> None:
        if not self.is_enabled or self._started:
            return

        try:
            from aiokafka import AIOKafkaConsumer

            self._consumer = AIOKafkaConsumer(
                DEVICE_PRESENCE_CHANGED_TOPIC,
                DEVICE_COMMAND_ACKNOWLEDGED_TOPIC,
                DEVICE_TELEMETRY_RECORDED_TOPIC,
                DEVICE_SYNC_REQUESTED_TOPIC,
                bootstrap_servers=self._bootstrap_servers,
                group_id=self._group_id,
                auto_offset_reset="latest",
                enable_auto_commit=True,
                value_deserializer=lambda value: json.loads(value.decode("utf-8")) if value else {},
                key_deserializer=lambda value: value.decode("utf-8") if value else None,
            )
            await self._consumer.start()
            self._task = asyncio.create_task(self._consume())
            self._started = True
            logger.info("Kafka edge event consumer started")
        except ModuleNotFoundError:
            self._consumer = None
            self._task = None
            self._started = False
            logger.exception(
                "Kafka client dependencies are missing; install aiokafka to enable edge consumption"
            )
        except Exception:
            self._consumer = None
            self._task = None
            self._started = False
            logger.exception("Kafka edge event consumer could not start")

    async def stop(self) -> None:
        task = self._task
        self._task = None

        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

        consumer = self._consumer
        self._consumer = None
        self._started = False
        if consumer is not None:
            await consumer.stop()

    async def _consume(self) -> None:
        if self._consumer is None:
            return

        try:
            async for message in self._consumer:
                payload = message.value or {}
                if not isinstance(payload, dict):
                    logger.warning(
                        "Skipping non-dict Kafka message topic=%s partition=%s offset=%s",
                        message.topic,
                        message.partition,
                        message.offset,
                    )
                    continue
                try:
                    await self._dispatch(message.topic, payload)
                except Exception:
                    logger.exception(
                        "Failed to process Kafka message from %s",
                        message.topic,
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Kafka edge event consumer loop crashed")

    async def _dispatch(self, topic: str, payload: dict[str, Any]) -> None:
        if topic == DEVICE_PRESENCE_CHANGED_TOPIC:
            await self._handle_device_presence_changed(payload)
            return
        if topic == DEVICE_COMMAND_ACKNOWLEDGED_TOPIC:
            await self._handle_device_command_acknowledged(payload)
            return
        if topic == DEVICE_TELEMETRY_RECORDED_TOPIC:
            await self._handle_device_telemetry_recorded(payload)
            return
        if topic == DEVICE_SYNC_REQUESTED_TOPIC:
            await self._handle_device_sync_requested(payload)
            return

        logger.debug("Ignoring unsupported Kafka topic %s", topic)

    async def _handle_device_presence_changed(self, payload: dict[str, Any]) -> None:
        from app.device.domain.commands import UpdateDevicePresenceStatusCommand

        device_id, hardware_id = self._extract_device_reference(payload)
        logger.info(
            "Processing device presence change topic=%s device_id=%s hardware_id=%s status=%s occurred_at=%s",
            DEVICE_PRESENCE_CHANGED_TOPIC,
            str(device_id) if device_id is not None else None,
            hardware_id,
            payload.get("status"),
            payload.get("occurred_at"),
        )
        command = UpdateDevicePresenceStatusCommand(
            device_id=device_id,
            hardware_id=HardwareId(value=hardware_id) if hardware_id is not None else None,
            status=payload.get("status"),
            occurred_at=payload.get("occurred_at"),
        )

        async with AsyncSessionLocal() as session:
            service = DevicePresenceCommandServiceImpl(
                device_repo=DeviceRepository(session),
                assignment_repo=DeviceAssignmentRepository(session),
                device_event_publisher=self._device_event_publisher,
            )
            await service.handle_update_device_presence_status(command, publish_event=False)

    async def _handle_device_command_acknowledged(self, payload: dict[str, Any]) -> None:
        from app.device.domain.commands import AcknowledgeDeviceCommand

        device_id, _hardware_id = self._extract_device_reference(payload)
        if device_id is None:
            raise ValueError("device_id is required for command acknowledgements")

        command = AcknowledgeDeviceCommand(
            device_id=device_id,
            command_id=payload.get("command_id"),
            status=payload.get("status"),
            failure_reason=payload.get("failure_reason"),
            occurred_at=payload.get("acknowledged_at") or payload.get("occurred_at"),
        )

        async with AsyncSessionLocal() as session:
            service = DeviceControlCommandServiceImpl(
                assignment_repo=DeviceAssignmentRepository(session),
                device_command_repo=DeviceCommandRepository(session),
                device_event_publisher=self._device_event_publisher,
            )
            await service.handle_acknowledge_device_command(command, publish_event=False)

    async def _handle_device_telemetry_recorded(self, payload: dict[str, Any]) -> None:
        from app.telemetry.domain.commands import RecordDeviceTelemetryCommand

        device_id, hardware_id = self._extract_device_reference(payload)
        occurred_at = payload.get("occurred_at") or payload.get("recorded_at")
        logger.debug(
            "Processing device telemetry recorded topic=%s device_id=%s hardware_id=%s occurred_at=%s",
            DEVICE_TELEMETRY_RECORDED_TOPIC,
            str(device_id) if device_id is not None else None,
            hardware_id,
            occurred_at,
        )
        command = RecordDeviceTelemetryCommand(
            device_id=device_id,
            hardware_id=hardware_id,
            payload=dict(payload),
            occurred_at=occurred_at,
            source=payload.get("source", "edge"),
        )

        async with AsyncSessionLocal() as session:
            service = TelemetryCommandServiceImpl(
                device_repo=DeviceRepository(session),
                assignment_repo=DeviceAssignmentRepository(session),
                telemetry_repo=TelemetryRepository(session),
                device_event_publisher=self._device_event_publisher,
                alert_incident_service=AlertIncidentServiceImpl(
                    assignment_repo=DeviceAssignmentRepository(session),
                    alert_incident_repo=AlertIncidentRepository(session),
                    outbox_repo=IntegrationOutboxRepository(session),
                ),
            )
            await service.handle_record_device_telemetry(command, publish_event=False)
        logger.debug(
            "Device telemetry recorded processed device_id=%s hardware_id=%s occurred_at=%s",
            str(device_id) if device_id is not None else None,
            hardware_id,
            occurred_at,
        )

    async def _handle_device_sync_requested(self, payload: dict[str, Any]) -> None:
        if self._device_event_publisher is None:
            logger.warning("Kafka publisher unavailable, skipping edge inventory sync response")
            return

        edge_instance_id = payload.get("edge_instance_id")
        requested_at = self._parse_datetime(payload.get("requested_at")) or datetime.utcnow()

        async with AsyncSessionLocal() as session:
            device_repo = DeviceRepository(session)
            assignment_repo = DeviceAssignmentRepository(session)

            page = 0
            size = 500
            while True:
                devices, total = await device_repo.find_all(page=page, size=size)
                if not devices:
                    break

                assignments = await assignment_repo.find_all_by_device_ids([device.id for device in devices])
                assignment_by_device_id = {assignment.device.id: assignment for assignment in assignments}

                for device in devices:
                    assignment = assignment_by_device_id.get(device.id)
                    if assignment is not None:
                        await self._device_event_publisher.publish_assignment_changed(
                            assignment,
                            changed_at=requested_at,
                            change_type="SYNC",
                        )
                    else:
                        await self._device_event_publisher.publish_device_changed(
                            device,
                            status=DeviceStatus.OFFLINE,
                            changed_at=requested_at,
                            change_type="SYNC",
                        )

                if (page + 1) * size >= total:
                    break
                page += 1

        logger.info(
            "Completed edge inventory sync request",
            extra={"edge_instance_id": edge_instance_id},
        )

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None

    @staticmethod
    def _extract_device_reference(payload: dict[str, Any]) -> tuple[UUID | None, str | None]:
        device_id_raw = payload.get("device_id")
        hardware_id_raw = payload.get("hardware_id")

        if isinstance(device_id_raw, UUID):
            return device_id_raw, hardware_id_raw if isinstance(hardware_id_raw, str) and hardware_id_raw.strip() else None

        if isinstance(device_id_raw, str):
            try:
                return UUID(device_id_raw), hardware_id_raw if isinstance(hardware_id_raw, str) and hardware_id_raw.strip() else None
            except ValueError:
                if isinstance(hardware_id_raw, str) and hardware_id_raw.strip():
                    return None, hardware_id_raw.strip()
                return None, device_id_raw.strip()

        if isinstance(hardware_id_raw, str) and hardware_id_raw.strip():
            return None, hardware_id_raw.strip()

        return None, None
