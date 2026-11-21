"""Real telemetry -> incidents -> tenant-authorized space query, without app startup."""
import json
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import UUID, uuid4

from sqlalchemy import select

from app.dependencies import get_current_edge_device
from app.device.domain.models import EdgeDevice
from app.device.domain.models.value_objects import ApiKey
from app.device.infrastructure.database.models.device_orm import DeviceORM
from app.device.infrastructure.database.models.device_assignment_orm import DeviceAssignmentORM
from app.device.infrastructure.database.models.alert_incident_orm import AlertIncidentORM
from app.device.infrastructure.database.models.space_member_orm import SpaceMemberORM
from app.device.infrastructure.kafka.device_event_consumer import KafkaEdgeEventConsumer
from app.main import app
from app.wine_cellar.infrastructure.database.models.wine_cellar_orm import WineCellarORM
from test_personal_context import PostgresAPITestCase


class SpaceAlertTests(PostgresAPITestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        app.dependency_overrides[get_current_edge_device] = lambda: EdgeDevice(name="Test edge", api_key=ApiKey.generate())
        self.space = await self.create_space("Coleccion2")
        self.device_id, self.assignment_id = await self.sensor(self.space)

    async def asyncTearDown(self):
        app.dependency_overrides.pop(get_current_edge_device, None)
        await super().asyncTearDown()

    async def sensor(self, space, index=1, *, linked=False):
        async with self.sessions() as session:
            device = DeviceORM(serial_number=f"SN-{index:04d}", name=f"Sensor {index:04d}", factory_name="Factory",
                hardware_id=f"VINE-A{index:03d}", api_key=f"isolated-alert-{index}", device_type="air-quality-v1")
            session.add(device)
            await session.flush()
            assignment = DeviceAssignmentORM(device_id=device.id, space_id=UUID(space["id"]), owner_user_id="1",
                configuration={"threshold.humidity_min": json.dumps({"value": "65.000000", "enabled": True})})
            session.add(assignment)
            if linked:
                (await session.get(WineCellarORM, UUID(space["default_wine_cellar"]["id"]))).device_id = device.id
            await session.commit()
            return device.id, assignment.id

    async def reading(self, humidity=60.2, index=1):
        result = await self.client.post("/api/v1/edges/devices/telemetry", json={
            "hardware_id": f"VINE-A{index:03d}", "occurred_at": datetime.now(timezone.utc).isoformat(),
            "payload": {"humidity": humidity, "temperature": 14},
        })
        self.assertEqual(result.status_code, 201, result.text)

    async def alerts(self, *, active=False, space=None, user_id=1, language="es"):
        return await self.client.get("/api/v1/alerts", params={"space_id": (space or self.space)["id"], "active_only": active},
            headers={**self.headers(user_id), "Accept-Language": language})

    async def test_unlinked_breach_is_immediate_and_assignment_changes_update_the_label(self):
        await self.reading()
        response = await self.alerts(active=True)
        self.assertEqual(response.status_code, 200, response.text)
        incident, = response.json()
        self.assertIsNone(incident["cellar_name"])
        self.assertEqual(incident["space_id"], self.space["id"])
        self.assertEqual(incident["device_name"], "Sensor 0001")
        self.assertEqual(incident["serial_number"], "SN-0001")
        self.assertEqual(incident["threshold_value"], "65")
        self.assertEqual(incident["actual_value"], "60.2")
        self.assertEqual(incident["message"], "Humedad por debajo del mínimo")
        self.assertTrue(incident["occurred_at"].endswith(("Z", "+00:00")))
        en, = (await self.alerts(language="en")).json()
        self.assertEqual(en["message"], "Humidity below configured minimum")
        cellar = self.space["default_wine_cellar"]
        moved = await self.client.put(f"/api/v1/devices/{self.device_id}/cellar", json={"cellar_id": cellar["id"]}, headers=self.headers())
        self.assertEqual(moved.status_code, 200, moved.text)
        updated, = (await self.alerts(active=True)).json()
        self.assertEqual(updated["id"], incident["id"])
        self.assertEqual(updated["cellar_name"], cellar["name"])
        async with self.sessions() as session:
            (await session.get(WineCellarORM, UUID(cellar["id"]))).name = "Cava Principal"
            await session.commit()
        self.assertEqual((await self.alerts()).json()[0]["cellar_name"], "Cava Principal")

    async def test_space_query_combines_linked_and_unlinked_and_history_keeps_resolved(self):
        await self.sensor(self.space, 2, linked=True)
        await self.reading(index=1)
        await self.reading(index=2)
        self.assertEqual(len((await self.alerts(active=True)).json()), 2)
        await self.reading(humidity=55, index=1)  # update, not another incident
        self.assertEqual(len((await self.alerts(active=True)).json()), 2)
        await self.reading(humidity=70, index=1)
        self.assertEqual(len((await self.alerts(active=True)).json()), 1)
        history = (await self.alerts()).json()
        self.assertEqual(len(history), 2)
        resolved, = [a for a in history if a["status"] == "RESOLVED"]
        self.assertIsNotNone(resolved["resolved_at"])
        self.assertEqual(resolved["message"], "Humedad dentro del rango configurado")
        self.assertIsNone(resolved["cellar_name"])

    async def test_authorization_and_cross_space_isolation(self):
        other = await self.create_space("Other", user_id=2)
        await self.sensor(other, 2)
        await self.reading(index=1)
        await self.reading(index=2)
        self.assertEqual((await self.alerts(user_id=2)).status_code, 403)
        self.assertEqual((await self.alerts(space=other)).status_code, 403)
        self.assertEqual(len((await self.alerts()).json()), 1)
        self.assertEqual((await self.client.get("/api/v1/alerts", headers=self.headers())).status_code, 422)
        self.assertEqual((await self.client.get("/api/v1/alerts", params={"space_id": str(uuid4())}, headers=self.headers())).status_code, 404)
        async with self.sessions() as session:
            session.add(SpaceMemberORM(space_id=UUID(self.space["id"]), user_id=3, role="WAITER"))
            await session.commit()
        self.assertEqual(len((await self.alerts(user_id=3)).json()), 1)

    async def test_prior_assignment_cannot_suppress_or_resolve_alerts_in_new_space(self):
        await self.reading()
        other = await self.create_space("New space")
        async with self.sessions() as session:
            assignment = await session.get(DeviceAssignmentORM, self.assignment_id)
            assignment.space_id = UUID(other["id"])
            await session.commit()
        await self.reading(humidity=50)
        current = (await self.alerts(active=True, space=other)).json()
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0]["space_id"], other["id"])
        self.assertEqual((await self.alerts()).json(), [])
        legacy = await self.client.get(f"/api/v1/devices/{self.device_id}/alerts", headers=self.headers())
        self.assertEqual(len(legacy.json()), 1)
        self.assertEqual(legacy.json()[0]["space_id"], other["id"])
        async with self.sessions() as session:
            incidents = (await session.scalars(select(AlertIncidentORM))).all()
            self.assertEqual(len(incidents), 2)
            self.assertTrue(all(a.status == "ACTIVE" for a in incidents))

    async def test_kafka_path_generates_unlinked_alerts_and_disabled_threshold_does_not(self):
        consumer = KafkaEdgeEventConsumer("", group_id="isolated-alert-test")
        with patch("app.device.infrastructure.kafka.device_event_consumer.AsyncSessionLocal", self.sessions):
            await consumer._handle_device_telemetry_recorded({"device_id": str(self.device_id),
                "occurred_at": datetime.now(timezone.utc).isoformat(), "humidity": 60})
        self.assertEqual(len((await self.alerts(active=True)).json()), 1)
        await self.sensor(self.space, 2)
        async with self.sessions() as session:
            assignment = await session.scalar(select(DeviceAssignmentORM).where(DeviceAssignmentORM.device_id != self.device_id))
            assignment.configuration = {"threshold.humidity_min": json.dumps({"value": 65, "enabled": False})}
            await session.commit()
        await self.reading(index=2)
        self.assertEqual(len((await self.alerts(active=True)).json()), 1)
