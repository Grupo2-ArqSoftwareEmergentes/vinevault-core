"""UTC freshness/power policy and real REST/Kafka persistence in temporary schemas."""
import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock
from uuid import UUID

from app.dependencies import get_current_edge_device
from app.device.domain.models import Device, DeviceAssignment, EdgeDevice
from app.device.domain.models.value_objects import ApiKey, DeviceStatus, DeviceType, HardwareId
from app.device.infrastructure.database.models.device_assignment_orm import DeviceAssignmentORM
from app.device.infrastructure.database.models.device_orm import DeviceORM
from app.device.infrastructure.kafka.device_event_consumer import KafkaEdgeEventConsumer
from app.main import app
from app.telemetry.infrastructure.database.repositories import TelemetryRepository
from test_personal_context import PostgresAPITestCase


class ConnectionPolicyTests(unittest.TestCase):
    def assignment(self):
        return DeviceAssignment(device=Device(serial_number="SN-0001", name="Sensor 0001", factory_name="Sensor 0001",
            hardware_id=HardwareId(value="VINE-A001"), api_key=ApiKey.generate(), device_type=DeviceType(value="air-quality-v1")))

    def test_five_minute_boundary_naive_aware_and_utc_offsets(self):
        now = datetime(2026, 11, 21, 12, tzinfo=timezone.utc)
        assignment = self.assignment()
        for age, online in [(0, True), (120, True), (300, True), (301, False), (3600, False)]:
            for offset in [timezone.utc, timezone(timedelta(hours=-5))]:
                assignment.last_seen_at = (now - timedelta(seconds=age)).astimezone(offset)
                status, actual, seen = assignment.connection(now=now)
                self.assertEqual(actual, online)
                self.assertEqual(status, DeviceStatus.ONLINE if online else DeviceStatus.OFFLINE)
                self.assertEqual(seen.tzinfo, timezone.utc)
            assignment.last_seen_at = (now - timedelta(seconds=age)).replace(tzinfo=None)
            self.assertEqual(assignment.connection(now=now)[1], online)

    def test_never_seen_and_future_dates_do_not_assert_online(self):
        assignment = self.assignment()
        now = datetime.now(timezone.utc)
        self.assertFalse(assignment.connection(now=now)[1])
        assignment.last_seen_at = now + timedelta(days=1)
        self.assertFalse(assignment.connection(now=now)[1])

    def test_off_and_disabled_states_win_over_recent_readings(self):
        assignment = self.assignment()
        for state in (DeviceStatus.STANDBY, DeviceStatus.MAINTENANCE, DeviceStatus.DECOMMISSIONED):
            assignment.status = state
            assignment.record_activity()
            self.assertEqual(assignment.connection()[0], state)
            self.assertFalse(assignment.connection()[1])

    def test_late_events_cannot_regress_activity_or_resurrect_manual_standby(self):
        assignment = self.assignment()
        now = datetime.now(timezone.utc)
        assignment.record_activity(now - timedelta(minutes=2))
        seen = assignment.last_seen_at
        assignment.record_activity(now - timedelta(minutes=10))
        assignment.update_presence(DeviceStatus.STANDBY, now - timedelta(minutes=9))
        self.assertEqual(assignment.last_seen_at, seen)
        self.assertEqual(assignment.status, DeviceStatus.ONLINE)
        assignment.request_power("STANDBY")
        assignment.update_presence(DeviceStatus.ONLINE)
        assignment.record_activity()
        self.assertEqual(assignment.status, DeviceStatus.STANDBY)
        self.assertFalse(assignment.connection()[1])

    def test_disabled_heartbeat_is_preserved_and_a_bad_future_clock_can_recover(self):
        assignment = self.assignment()
        assignment.status = DeviceStatus.MAINTENANCE
        assignment.update_presence(DeviceStatus.ONLINE)
        self.assertEqual(assignment.status, DeviceStatus.MAINTENANCE)
        self.assertFalse(assignment.connection()[1])
        assignment.status = DeviceStatus.OFFLINE
        assignment.last_seen_at = datetime.now(timezone.utc) + timedelta(days=1)
        assignment.record_activity()
        self.assertTrue(assignment.connection()[1])


class DeviceConnectivityAPITests(PostgresAPITestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        app.dependency_overrides[get_current_edge_device] = lambda: EdgeDevice(name="Isolated test edge", api_key=ApiKey.generate())
        self.space = await self.create_space("Coleccion2")
        async with self.sessions() as session:
            device = DeviceORM(serial_number="SN-0001", name="Sensor 0001", factory_name="Sensor 0001",
                hardware_id="VINE-A001", api_key="isolated-connectivity-test", device_type="air-quality-v1")
            session.add(device)
            await session.flush()
            assignment = DeviceAssignmentORM(device_id=device.id, space_id=UUID(self.space["id"]), owner_user_id="1", status="OFFLINE", configuration={})
            session.add(assignment)
            await session.commit()
            self.device_id, self.assignment_id = device.id, assignment.id

    async def asyncTearDown(self):
        app.dependency_overrides.pop(get_current_edge_device, None)
        await super().asyncTearDown()

    async def reading(self, occurred_at=None):
        result = await self.client.post("/api/v1/edges/devices/telemetry", json={
            "hardware_id": "VINE-A001", "occurred_at": (occurred_at or datetime.now(timezone.utc)).isoformat(),
            "payload": {"signal_strength": -88, "network_name": "Wokwi-GUEST", "wifi_status": "CONNECTED", "temperature": 14, "humidity": 72},
        })
        self.assertEqual(result.status_code, 201, result.text)
        return result

    async def assert_connection(self, online, status=None):
        responses = [
            await self.client.get(f"/api/v1/devices?space_id={self.space['id']}", headers=self.headers()),
            await self.client.get(f"/api/v1/devices/{self.device_id}", headers=self.headers()),
            await self.client.get(f"/api/v1/devices/{self.device_id}/status", headers=self.headers()),
        ]
        for index, response in enumerate(responses):
            self.assertEqual(response.status_code, 200, response.text)
            item = response.json()["items"][0] if index == 0 else response.json()
            self.assertEqual(item["is_online"], online, item)
            self.assertEqual(item["status"], status or ("ONLINE" if online else "OFFLINE"))
            if item["last_seen_at"]:
                self.assertTrue(item["last_seen_at"].endswith("Z"), item)

    async def power(self, intent):
        response = await self.client.post(f"/api/v1/devices/{self.device_id}/commands", json={"type": intent}, headers=self.headers())
        self.assertEqual(response.status_code, 201, response.text)

    async def test_recent_weak_signal_telemetry_persists_and_agrees_in_all_serializers(self):
        await self.assert_connection(False)
        occurred = datetime.now(timezone.utc) - timedelta(minutes=2)
        await self.reading(occurred.astimezone(timezone(timedelta(hours=-5))))
        await self.assert_connection(True)
        async with self.sessions() as session:
            assignment = await session.get(DeviceAssignmentORM, self.assignment_id)
            self.assertEqual(assignment.status, "ONLINE")
            self.assertEqual(assignment.last_seen_at, occurred.replace(tzinfo=None))
            # Legacy deployment: telemetry exists but last_seen/status were never updated.
            assignment.status, assignment.last_seen_at = "OFFLINE", None
            await session.commit()
        await self.assert_connection(True)

    async def test_stale_telemetry_expires_and_heartbeat_recovers_with_utc_offset(self):
        await self.reading(datetime.now(timezone.utc) - timedelta(minutes=6))
        await self.assert_connection(False)
        response = await self.client.post("/api/v1/edges/devices/presence", json={
            "device_id": str(self.device_id), "status": "ONLINE",
            "occurred_at": (datetime.now(timezone.utc) - timedelta(minutes=2)).astimezone(timezone(timedelta(hours=-5))).isoformat(),
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["is_online"])
        await self.assert_connection(True)

    async def test_manual_off_survives_readings_and_online_heartbeats_until_wake_and_new_activity(self):
        await self.reading()
        await self.power("STANDBY")
        await self.reading()
        heartbeat = await self.client.post("/api/v1/edges/devices/presence", json={"device_id": str(self.device_id), "status": "ONLINE"})
        self.assertEqual(heartbeat.status_code, 200, heartbeat.text)
        await self.assert_connection(False, "STANDBY")
        await self.power("WAKE")
        await self.assert_connection(False)  # A command is not proof of liveness.
        await self.reading()
        await self.assert_connection(True)

    async def test_kafka_ingestion_uses_same_activity_path_and_ignores_out_of_order_regression(self):
        consumer = KafkaEdgeEventConsumer("", group_id="isolated-test")
        occurred = datetime.now(timezone.utc) - timedelta(minutes=2)
        with patch("app.device.infrastructure.kafka.device_event_consumer.AsyncSessionLocal", self.sessions):
            await consumer._handle_device_telemetry_recorded({"device_id": str(self.device_id), "hardware_id": "VINE-A001", "occurred_at": occurred.isoformat(), "signal_strength": -88, "network_name": "Wokwi-GUEST"})
            await consumer._handle_device_telemetry_recorded({"device_id": str(self.device_id), "occurred_at": (occurred - timedelta(minutes=8)).isoformat(), "signal_strength": -88})
        await self.assert_connection(True)
        async with self.sessions() as session:
            self.assertEqual((await session.get(DeviceAssignmentORM, self.assignment_id)).last_seen_at, occurred.replace(tzinfo=None))

    async def test_concurrent_telemetry_cannot_undo_manual_off(self):
        await asyncio.gather(self.reading(), self.power("STANDBY"))
        await self.assert_connection(False, "STANDBY")

    async def test_failed_reading_does_not_commit_activity_on_its_own(self):
        with patch.object(TelemetryRepository, 'save', AsyncMock(side_effect=RuntimeError('storage unavailable'))):
            with self.assertRaises(RuntimeError):
                await self.reading()
        await self.assert_connection(False)
        async with self.sessions() as session:
            assignment = await session.get(DeviceAssignmentORM, self.assignment_id)
            self.assertIsNone(assignment.last_seen_at)
            self.assertEqual(assignment.status, 'OFFLINE')
