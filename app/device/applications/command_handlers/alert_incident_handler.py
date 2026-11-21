import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from app.device.domain.models import AlertIncident, DeviceAssignment
from app.device.domain.models.value_objects import (
    AlertMetricType,
    AlertStatus,
    DeviceMetricThresholdConfiguration,
    MetricThreshold,
)
from app.device.infrastructure.database.repositories import (
    AlertIncidentRepository,
    DeviceAssignmentRepository,
)
from app.device.infrastructure.kafka.device_event_publisher import DEVICE_ALERT_INCIDENT_CHANGED_TOPIC
from app.shared.infrastructure.database.repositories import IntegrationOutboxRepository
from app.telemetry.domain.models import DeviceTelemetryRecord


@dataclass(frozen=True)
class _MetricRule:
    threshold_metric: MetricThreshold
    alert_metric: AlertMetricType
    payload_key: str
    direction: str


class AlertIncidentServiceImpl:
    _RULES = (
        _MetricRule(MetricThreshold.TEMPERATURE_MIN, AlertMetricType.TEMPERATURE, "temperature", "below"),
        _MetricRule(MetricThreshold.TEMPERATURE_MAX, AlertMetricType.TEMPERATURE, "temperature", "above"),
        _MetricRule(MetricThreshold.HUMIDITY_MIN, AlertMetricType.HUMIDITY, "humidity", "below"),
        _MetricRule(MetricThreshold.HUMIDITY_MAX, AlertMetricType.HUMIDITY, "humidity", "above"),
    )

    def __init__(
        self,
        assignment_repo: DeviceAssignmentRepository,
        alert_incident_repo: AlertIncidentRepository,
        outbox_repo: IntegrationOutboxRepository | None = None,
    ) -> None:
        self._assignment_repo = assignment_repo
        self._alert_incident_repo = alert_incident_repo
        self._outbox_repo = outbox_repo

    async def evaluate_telemetry(
        self,
        record: DeviceTelemetryRecord,
        *,
        assignment: DeviceAssignment | None = None,
    ) -> list[AlertIncident]:
        assignment = assignment or await self._assignment_repo.find_by_device_id(record.device.id)
        if assignment is None:
            return []

        changes: list[AlertIncident] = []
        for rule in self._RULES:
            threshold_config = self._load_threshold_config(assignment, rule.threshold_metric)
            if threshold_config is None or not threshold_config.enabled:
                continue

            actual_value = self._extract_metric_value(record.payload, rule.payload_key)
            if actual_value is None:
                continue

            breached = self._is_breached(actual_value, threshold_config.value, rule.direction)
            active_incident = await self._alert_incident_repo.find_active_by_device_id_and_threshold_metric(
                record.device.id,
                rule.threshold_metric.value,
                assignment_id=assignment.id,
                space_id=assignment.space_id,
            )

            if breached:
                if active_incident is None:
                    incident = self._build_incident(
                        record=record,
                        assignment=assignment,
                        rule=rule,
                        threshold_value=threshold_config.value,
                        actual_value=actual_value,
                        status=AlertStatus.ACTIVE,
                        occurred_at=record.occurred_at,
                    )
                    saved = await self._alert_incident_repo.save(incident)
                    await self._publish_alert_event(saved)
                    changes.append(saved)
                else:
                    updated = active_incident.model_copy(
                        update={
                            "actual_value": actual_value,
                            "message": self._build_message(rule, threshold_config.value, actual_value, active=True),
                            "updated_at": datetime.utcnow(),
                        }
                    )
                    saved = await self._alert_incident_repo.save(updated)
                    changes.append(saved)
                continue

            if active_incident is not None:
                resolved = active_incident.model_copy(
                    update={
                        "status": AlertStatus.RESOLVED,
                        "actual_value": actual_value,
                        "message": self._build_message(rule, threshold_config.value, actual_value, active=False),
                        "resolved_at": record.occurred_at,
                        "updated_at": datetime.utcnow(),
                    }
                )
                saved = await self._alert_incident_repo.save(resolved)
                await self._publish_alert_event(saved)
                changes.append(saved)

        return changes

    def _build_incident(
        self,
        *,
        record: DeviceTelemetryRecord,
        assignment: DeviceAssignment,
        rule: _MetricRule,
        threshold_value: Decimal,
        actual_value: Decimal,
        status: AlertStatus,
        occurred_at: datetime,
    ) -> AlertIncident:
        return AlertIncident(
            device=record.device,
            assignment_id=assignment.id,
            space_id=assignment.space_id,
            metric=rule.alert_metric,
            threshold_metric=rule.threshold_metric,
            threshold_value=threshold_value,
            actual_value=actual_value,
            message=self._build_message(rule, threshold_value, actual_value, active=True),
            status=status,
            occurred_at=occurred_at,
        )

    async def _publish_alert_event(self, incident: AlertIncident) -> None:
        if self._outbox_repo is None:
            return

        await self._outbox_repo.enqueue_event(
            topic=DEVICE_ALERT_INCIDENT_CHANGED_TOPIC,
            message_key=incident.device.hardware_id.value,
            event_type="DeviceAlertIncidentChanged",
            aggregate_type="AlertIncident",
            aggregate_id=str(incident.id),
            payload=self._build_alert_payload(incident),
        )

    @staticmethod
    def _build_alert_payload(incident: AlertIncident) -> dict:
        return {
            "alert_id": str(incident.id),
            "device_id": str(incident.device.id),
            "hardware_id": incident.device.hardware_id.value,
            "space_id": str(incident.space_id) if incident.space_id else None,
            "metric": incident.metric.value.lower(),
            "threshold_metric": incident.threshold_metric.value,
            "threshold_value": float(incident.threshold_value),
            "actual_value": float(incident.actual_value),
            "message": incident.message,
            "status": incident.status.value,
            "occurred_at": incident.occurred_at.isoformat(),
            "resolved_at": incident.resolved_at.isoformat() if incident.resolved_at else None,
        }

    @staticmethod
    def _load_threshold_config(
        assignment: DeviceAssignment,
        metric: MetricThreshold,
    ) -> Optional[DeviceMetricThresholdConfiguration]:
        config_json = assignment.find_configuration_value(f"threshold.{metric.value}")
        if not config_json:
            return None
        try:
            data = json.loads(config_json)
            return DeviceMetricThresholdConfiguration(
                metric=metric,
                value=Decimal(str(data["value"])),
                enabled=data.get("enabled", True),
            )
        except Exception:
            return None

    @staticmethod
    def _extract_metric_value(payload: dict, key: str) -> Decimal | None:
        raw_value = payload.get(key)
        if raw_value is None:
            return None
        try:
            return Decimal(str(raw_value))
        except (InvalidOperation, TypeError, ValueError):
            return None

    @staticmethod
    def _is_breached(actual_value: Decimal, threshold_value: Decimal, direction: str) -> bool:
        if direction == "below":
            return actual_value < threshold_value
        return actual_value > threshold_value

    @staticmethod
    def _build_message(
        rule: _MetricRule,
        threshold_value: Decimal,
        actual_value: Decimal,
        *,
        active: bool,
    ) -> str:
        metric_name = "Temperature" if rule.alert_metric == AlertMetricType.TEMPERATURE else "Humidity"
        if active:
            if rule.direction == "above":
                return f"{metric_name} above configured maximum"
            return f"{metric_name} below configured minimum"

        return f"{metric_name} back within configured range"
