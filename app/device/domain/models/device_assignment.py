from datetime import datetime
from typing import Optional, Dict, List
from uuid import UUID, uuid4
from pydantic import BaseModel, Field

from .device import Device
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
        self.status = status
        if status != DeviceStatus.OFFLINE:
            self.last_seen_at = occurred_at or datetime.utcnow()

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
