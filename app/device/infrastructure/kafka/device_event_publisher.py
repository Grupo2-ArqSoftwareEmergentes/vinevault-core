import json
import logging
from typing import Optional

from app.device.domain.models import Device, DeviceAssignment
from app.device.domain.models.value_objects import DeviceStatus

logger = logging.getLogger(__name__)

DEVICE_CHANGED_TOPIC = "vinevault.provisioning.devices.changed"


class KafkaDeviceEventPublisher:
    def __init__(self, bootstrap_servers: str) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._producer: Optional[AIOKafkaProducer] = None
        self._started = False

    @property
    def is_enabled(self) -> bool:
        return bool(self._bootstrap_servers.strip())

    async def start(self) -> None:
        if not self.is_enabled or self._started:
            return

        try:
            from aiokafka import AIOKafkaProducer

            self._producer = AIOKafkaProducer(
                bootstrap_servers=self._bootstrap_servers,
                value_serializer=lambda value: json.dumps(value).encode("utf-8"),
            )
            await self._producer.start()
            self._started = True
            logger.info(
                "Kafka device event publisher started for %s",
                DEVICE_CHANGED_TOPIC,
            )
        except Exception:
            self._producer = None
            self._started = False
            logger.exception(
                "Kafka device event publisher could not start; device change events will be skipped"
            )
        except ModuleNotFoundError:
            self._producer = None
            self._started = False
            logger.exception(
                "Kafka client dependencies are missing; install kafka-python to enable device change events"
            )

    async def stop(self) -> None:
        if self._producer is None:
            return

        try:
            await self._producer.stop()
        finally:
            self._producer = None
            self._started = False

    def build_device_changed_payload(
        self,
        device: Device,
        *,
        status: DeviceStatus = DeviceStatus.OFFLINE,
    ) -> dict:
        return {
            "device_id": str(device.id),
            "hardware_id": device.hardware_id.value,
            "api_key": device.api_key.value,
            "status": status.value,
        }

    def build_payload_from_assignment(
        self,
        assignment: DeviceAssignment,
        *,
        status_override: DeviceStatus | None = None,
    ) -> dict:
        status = status_override or assignment.status
        return self.build_device_changed_payload(assignment.device, status=status)

    async def publish_device_changed(
        self,
        device: Device,
        *,
        status: DeviceStatus = DeviceStatus.OFFLINE,
    ) -> None:
        await self.publish_payload(self.build_device_changed_payload(device, status=status))

    async def publish_assignment_changed(
        self,
        assignment: DeviceAssignment,
        *,
        status_override: DeviceStatus | None = None,
    ) -> None:
        await self.publish_payload(
            self.build_payload_from_assignment(assignment, status_override=status_override)
        )

    async def publish_payload(self, payload: dict) -> None:
        if self._producer is None:
            logger.warning(
                "Kafka producer unavailable, skipping device change event for topic %s",
                DEVICE_CHANGED_TOPIC,
            )
            return

        try:
            await self._producer.send_and_wait(DEVICE_CHANGED_TOPIC, payload)
        except Exception:
            logger.exception(
                "Failed to publish device change event to %s",
                DEVICE_CHANGED_TOPIC,
            )
