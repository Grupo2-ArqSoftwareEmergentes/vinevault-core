import json
import logging
from datetime import datetime
from typing import Any, Optional

from app.device.domain.models import Device, DeviceAssignment, DeviceCommand
from app.device.domain.models.value_objects import AlertMetricType, AlertStatus, DeviceStatus, MetricThreshold
from app.telemetry.domain.models import DeviceTelemetryRecord

logger = logging.getLogger(__name__)

DEVICE_CHANGED_TOPIC = "vinevault.provisioning.devices.changed"
DEVICE_PRESENCE_CHANGED_TOPIC = "vinevault.device.presence.changed"
DEVICE_COMMAND_PENDING_TOPIC = "vinevault.device.commands.pending"
DEVICE_COMMAND_ACKNOWLEDGED_TOPIC = "vinevault.device.commands.acknowledged"
DEVICE_TELEMETRY_RECORDED_TOPIC = "vinevault.device.telemetry.recorded"
DEVICE_SYNC_REQUESTED_TOPIC = "vinevault.provisioning.devices.sync.requested"
DEVICE_ALERT_INCIDENT_CHANGED_TOPIC = "vinevault.device.alert.incident.changed"


class KafkaDeviceEventPublisher:
    def __init__(self, bootstrap_servers: str) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._producer: Optional[object] = None
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
                value_serializer=lambda value: json.dumps(value, default=str).encode("utf-8"),
                key_serializer=lambda value: str(value).encode("utf-8") if value is not None else None,
            )
            await self._producer.start()
            self._started = True
            logger.info("Kafka device event publisher started")
        except ModuleNotFoundError:
            self._producer = None
            self._started = False
            logger.exception(
                "Kafka client dependencies are missing; install kafka-python to enable events"
            )
        except Exception:
            self._producer = None
            self._started = False
            logger.exception(
                "Kafka device event publisher could not start; events will be skipped"
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
        assignment: DeviceAssignment | None = None,
        status: DeviceStatus = DeviceStatus.OFFLINE,
        change_type: str = "UPSERT",
        changed_at: datetime | None = None,
    ) -> dict:
        event_time = changed_at or datetime.utcnow()
        payload: dict[str, Any] = {
            "device_id": str(device.id),
            "serial_number": device.serial_number,
            "name": device.name,
            "factory_name": device.factory_name,
            "hardware_id": device.hardware_id.value,
            "api_key": device.api_key.value,
            "device_type": device.device_type.value,
            "assigned": assignment is not None,
            "status": status.value,
            "change_type": change_type,
            "changed_at": event_time.isoformat(),
            "created_at": device.created_at.isoformat() if device.created_at else None,
            "updated_at": device.updated_at.isoformat() if device.updated_at else None,
        }

        if assignment is not None:
            payload.update(
                {
                    "assignment_id": str(assignment.id),
                    "space_id": str(assignment.space_id) if assignment.space_id else None,
                    "owner_user_id": assignment.owner_user_id.user_id if assignment.owner_user_id else None,
                    "claim_token": assignment.claim_token.value if assignment.claim_token else None,
                    "configuration": assignment.configuration,
                    "activated_at": assignment.activated_at.isoformat() if assignment.activated_at else None,
                    "last_seen_at": assignment.last_seen_at.isoformat() if assignment.last_seen_at else None,
                }
            )
        else:
            payload.update(
                {
                    "assignment_id": None,
                    "space_id": None,
                    "owner_user_id": None,
                    "claim_token": None,
                    "configuration": {},
                    "activated_at": None,
                    "last_seen_at": None,
                }
            )

        return payload

    def build_payload_from_assignment(
        self,
        assignment: DeviceAssignment,
        *,
        changed_at: datetime | None = None,
        change_type: str = "UPSERT",
        status_override: DeviceStatus | None = None,
    ) -> dict:
        status = status_override or assignment.status
        return self.build_device_changed_payload(
            assignment.device,
            assignment=assignment,
            status=status,
            changed_at=changed_at,
            change_type=change_type,
        )

    async def publish_device_changed(
        self,
        device: Device,
        *,
        assignment: DeviceAssignment | None = None,
        status: DeviceStatus = DeviceStatus.OFFLINE,
        changed_at: datetime | None = None,
        change_type: str = "UPSERT",
    ) -> None:
        await self.publish_payload(
            self.build_device_changed_payload(
                device,
                assignment=assignment,
                status=status,
                changed_at=changed_at,
                change_type=change_type,
            ),
            key=device.hardware_id.value,
        )

    async def publish_assignment_changed(
        self,
        assignment: DeviceAssignment,
        *,
        changed_at: datetime | None = None,
        change_type: str = "UPSERT",
        status_override: DeviceStatus | None = None,
    ) -> None:
        await self.publish_payload(
            self.build_payload_from_assignment(
                assignment,
                changed_at=changed_at,
                change_type=change_type,
                status_override=status_override,
            ),
            key=assignment.device.hardware_id.value,
        )

    def build_device_presence_changed_payload(
        self,
        device: Device,
        *,
        status: DeviceStatus,
        occurred_at: datetime | None = None,
    ) -> dict:
        event_time = occurred_at or datetime.utcnow()
        return {
            "device_id": str(device.id),
            "hardware_id": device.hardware_id.value,
            "status": status.value,
            "occurred_at": event_time.isoformat(),
        }

    async def publish_device_presence_changed(
        self,
        device: Device,
        *,
        status: DeviceStatus,
        occurred_at: datetime | None = None,
    ) -> None:
        await self.publish_payload(
            self.build_device_presence_changed_payload(
                device,
                status=status,
                occurred_at=occurred_at,
            ),
            key=device.hardware_id.value,
            topic=DEVICE_PRESENCE_CHANGED_TOPIC,
        )

    def build_device_command_acknowledged_payload(
        self,
        command: DeviceCommand,
        *,
        acknowledged_at: datetime | None = None,
    ) -> dict:
        occurred_at = acknowledged_at or command.executed_at or command.sent_at or datetime.utcnow()
        return {
            "device_id": str(command.device.id),
            "hardware_id": command.device.hardware_id.value,
            "command_id": str(command.id),
            "status": command.status.value,
            "failure_reason": command.failure_reason,
            "acknowledged_at": occurred_at.isoformat(),
        }

    async def publish_device_command_acknowledged(
        self,
        command: DeviceCommand,
        *,
        acknowledged_at: datetime | None = None,
    ) -> None:
        await self.publish_payload(
            self.build_device_command_acknowledged_payload(
                command,
                acknowledged_at=acknowledged_at,
            ),
            key=command.id,
            topic=DEVICE_COMMAND_ACKNOWLEDGED_TOPIC,
        )

    def build_device_command_pending_payload(
        self,
        command: DeviceCommand,
        *,
        issued_at: datetime | None = None,
    ) -> dict:
        occurred_at = issued_at or command.created_at or datetime.utcnow()
        return {
            "command_id": str(command.id),
            "device_id": str(command.device.id),
            "hardware_id": command.device.hardware_id.value,
            "type": command.type.value,
            "command_type": command.type.value,
            "payload": command.payload,
            "issued_at": occurred_at.isoformat(),
        }

    async def publish_device_command_pending(
        self,
        command: DeviceCommand,
        *,
        issued_at: datetime | None = None,
    ) -> None:
        await self.publish_payload(
            self.build_device_command_pending_payload(command, issued_at=issued_at),
            key=command.device.hardware_id.value,
            topic=DEVICE_COMMAND_PENDING_TOPIC,
        )

    def build_device_telemetry_recorded_payload(
        self,
        record: DeviceTelemetryRecord,
        *,
        occurred_at: datetime | None = None,
    ) -> dict:
        event_time = occurred_at or record.occurred_at or datetime.utcnow()
        return {
            "telemetry_id": str(record.id),
            "device_id": str(record.device.id),
            "hardware_id": record.device.hardware_id.value,
            "assignment_id": str(record.assignment_id) if record.assignment_id else None,
            "space_id": str(record.space_id) if record.space_id else None,
            "source": record.source,
            "payload": record.payload,
            "occurred_at": event_time.isoformat(),
        }

    def build_device_alert_incident_changed_payload(
        self,
        *,
        alert_id: Any,
        device: Device,
        metric: AlertMetricType | MetricThreshold,
        threshold_metric: MetricThreshold,
        threshold_value: Any,
        actual_value: Any,
        message: str,
        status: AlertStatus,
        space_id: Any | None = None,
        occurred_at: datetime | None = None,
        resolved_at: datetime | None = None,
    ) -> dict:
        event_time = occurred_at or datetime.utcnow()
        metric_value = self._normalize_alert_metric(metric)
        return {
            "alert_id": str(alert_id),
            "device_id": str(device.id),
            "hardware_id": device.hardware_id.value,
            "space_id": str(space_id) if space_id is not None else None,
            "metric": metric_value.value.lower(),
            "threshold_metric": threshold_metric.value,
            "threshold_value": float(threshold_value),
            "actual_value": float(actual_value),
            "message": message,
            "status": status.value,
            "occurred_at": event_time.isoformat(),
            "resolved_at": resolved_at.isoformat() if resolved_at else None,
        }

    async def publish_device_alert_incident_changed(
        self,
        *,
        alert_id: Any,
        device: Device,
        metric: AlertMetricType | MetricThreshold,
        threshold_metric: MetricThreshold,
        threshold_value: Any,
        actual_value: Any,
        message: str,
        status: AlertStatus,
        space_id: Any | None = None,
        occurred_at: datetime | None = None,
        resolved_at: datetime | None = None,
    ) -> None:
        await self.publish_payload(
            self.build_device_alert_incident_changed_payload(
                alert_id=alert_id,
                device=device,
                metric=metric,
                threshold_metric=threshold_metric,
                threshold_value=threshold_value,
                actual_value=actual_value,
                message=message,
                status=status,
                space_id=space_id,
                occurred_at=occurred_at,
                resolved_at=resolved_at,
            ),
            key=device.hardware_id.value,
            topic=DEVICE_ALERT_INCIDENT_CHANGED_TOPIC,
        )

    async def publish_device_telemetry_recorded(
        self,
        record: DeviceTelemetryRecord,
        *,
        occurred_at: datetime | None = None,
    ) -> None:
        await self.publish_payload(
            self.build_device_telemetry_recorded_payload(
                record,
                occurred_at=occurred_at,
            ),
            key=record.device.hardware_id.value,
            topic=DEVICE_TELEMETRY_RECORDED_TOPIC,
        )

    async def publish_payload(
        self,
        payload: dict,
        *,
        topic: str = DEVICE_CHANGED_TOPIC,
        key: Any | None = None,
    ) -> None:
        if self._producer is None:
            logger.warning(
                "Kafka producer unavailable, skipping event for topic %s",
                topic,
            )
            return

        try:
            await self._producer.send_and_wait(topic, payload, key=key)
        except Exception:
            logger.exception(
                "Failed to publish event to %s",
                topic,
            )

    @staticmethod
    def _normalize_alert_metric(metric: AlertMetricType | MetricThreshold) -> AlertMetricType:
        if isinstance(metric, AlertMetricType):
            return metric
        mapping = {
            MetricThreshold.TEMPERATURE_MIN: AlertMetricType.TEMPERATURE,
            MetricThreshold.TEMPERATURE_MAX: AlertMetricType.TEMPERATURE,
            MetricThreshold.HUMIDITY_MIN: AlertMetricType.HUMIDITY,
            MetricThreshold.HUMIDITY_MAX: AlertMetricType.HUMIDITY,
        }
        return mapping.get(metric, AlertMetricType.TEMPERATURE)
