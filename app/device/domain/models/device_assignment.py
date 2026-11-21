from datetime import datetime, timezone
from typing import Optional, Dict, List
from uuid import UUID, uuid4
from pydantic import BaseModel, Field

from .device import Device
from .connection import ONLINE_WINDOW, POWER_STATE_KEY, POWER_CHANGED_AT_KEY, utc, activity_time
from .value_objects import ClaimToken, DeviceStatus, UserId, MetricThreshold, DeviceMetricThresholdConfiguration


class DeviceAssignment(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    device: Device
    owner_user_id: Optional[UserId] = None
    space_id: Optional[UUID] = None
    status: DeviceStatus = DeviceStatus.OFFLINE
    configuration: Dict[str, str] = Field(default_factory=dict)
    claim_token: Optional[ClaimToken] = None
    activated_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @staticmethod
    def _to_naive_utc(value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def claim_to_space(self, space_id: UUID, user_id: UserId) -> None:
        if self.owner_user_id is not None:
            raise IllegalStateError("Device already claimed")
        if space_id is None:
            raise ValueError("Space ID must not be null")
        if user_id is None:
            raise ValueError("User ID must not be null")

        self.owner_user_id = user_id
        self.space_id = space_id
        self.claim_token = None
        self._ensure_default_thresholds()
        if self.activated_at is None:
            self.activated_at = datetime.utcnow()

    def update_presence(self, status: DeviceStatus, occurred_at: Optional[datetime] = None) -> None:
        if status is None:
            raise ValueError("Device status must not be null")
        timestamp = activity_time(occurred_at)
        if self.last_seen_at and timestamp < utc(self.last_seen_at) <= datetime.now(timezone.utc):
            return  # Out-of-order events cannot regress presence/activity.
        if self.configuration.get(POWER_STATE_KEY) != 'STANDBY' and self.status not in (DeviceStatus.MAINTENANCE, DeviceStatus.DECOMMISSIONED):
            self.status = status
        if status != DeviceStatus.OFFLINE:
            self.last_seen_at = self._to_naive_utc(timestamp)

    def record_activity(self, occurred_at: datetime | None = None) -> None:
        timestamp = activity_time(occurred_at)
        if self.last_seen_at and timestamp < utc(self.last_seen_at) <= datetime.now(timezone.utc):
            return
        self.last_seen_at = self._to_naive_utc(timestamp)
        if self.status in (DeviceStatus.ONLINE, DeviceStatus.OFFLINE) and self.configuration.get(POWER_STATE_KEY) != 'STANDBY':
            self.status = DeviceStatus.ONLINE

    def request_power(self, command_type: str, now: datetime | None = None) -> None:
        if command_type not in ('STANDBY', 'WAKE'):
            return
        self.configuration[POWER_STATE_KEY] = command_type
        self.configuration[POWER_CHANGED_AT_KEY] = activity_time(now).isoformat()
        self.status = DeviceStatus.STANDBY if command_type == 'STANDBY' else DeviceStatus.OFFLINE

    def connection(self, last_telemetry_at: datetime | None = None, now: datetime | None = None) -> tuple[DeviceStatus, bool, datetime | None]:
        current = utc(now) or datetime.now(timezone.utc)
        times = [utc(value) for value in (self.last_seen_at, last_telemetry_at) if value is not None and utc(value) <= current]
        seen = max(times, default=None)
        blocked = self.status in (DeviceStatus.STANDBY, DeviceStatus.MAINTENANCE, DeviceStatus.DECOMMISSIONED) or self.configuration.get(POWER_STATE_KEY) == 'STANDBY'
        changed = self.configuration.get(POWER_CHANGED_AT_KEY)
        try:
            after_wake = not changed or (seen is not None and seen >= utc(datetime.fromisoformat(changed)))
        except (TypeError, ValueError):
            after_wake = False  # Malformed control metadata fails closed.
        online = bool(not blocked and seen and current - seen <= ONLINE_WINDOW and after_wake)
        status = self.status
        if self.configuration.get(POWER_STATE_KEY) == 'STANDBY':
            status = DeviceStatus.STANDBY
        elif status in (DeviceStatus.ONLINE, DeviceStatus.OFFLINE):
            status = DeviceStatus.ONLINE if online else DeviceStatus.OFFLINE
        return status, online, seen

    def mark_online(self) -> None:
        self.status = DeviceStatus.ONLINE
        self.last_seen_at = datetime.utcnow()

    def mark_standby(self) -> None:
        self.status = DeviceStatus.STANDBY
        self.last_seen_at = datetime.utcnow()

    def mark_offline(self) -> None:
        self.status = DeviceStatus.OFFLINE

    def mark_error(self) -> None:
        self.status = DeviceStatus.ERROR
        self.last_seen_at = datetime.utcnow()

    def find_configuration_value(self, key: str) -> Optional[str]:
        return self.configuration.get(key)

    def put_configuration_value(self, key: str, value: str) -> None:
        if not key or not key.strip():
            raise ValueError("Configuration key must not be blank")
        if value is None:
            raise ValueError("Configuration value must not be null")
        self.configuration[key] = value

    def remove_configuration_value(self, key: str) -> None:
        if not key or not key.strip():
            raise ValueError("Configuration key must not be blank")
        self.configuration.pop(key, None)

    def _ensure_default_thresholds(self) -> None:
        for metric in MetricThreshold:
            key = f"threshold.{metric.value}"
            if key not in self.configuration:
                default_config = DeviceMetricThresholdConfiguration.default_for(metric)
                self.configuration[key] = default_config.model_dump_json()

    def ensure_default_thresholds(self) -> None:
        self._ensure_default_thresholds()


class IllegalStateError(Exception):
    pass
