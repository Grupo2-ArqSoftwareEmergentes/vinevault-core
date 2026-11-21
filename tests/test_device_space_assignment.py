"""Claim/list consistency in isolated PostgreSQL schemas; no startup seeds/Kafka."""
from uuid import UUID

from sqlalchemy import select

from app.device.infrastructure.database.models.device_assignment_orm import DeviceAssignmentORM
from app.device.infrastructure.database.models.device_orm import DeviceORM
from app.wine_cellar.infrastructure.database.models.wine_cellar_orm import WineCellarORM
from test_personal_context import PostgresAPITestCase


class DeviceSpaceAssignmentTests(PostgresAPITestCase):
    async def pair_sensor(self):
        async with self.sessions() as session:
            session.add(DeviceORM(
                serial_number="SN-0001", name="Sensor 0001", factory_name="Sensor 0001",
                hardware_id="VINE-A001", api_key="isolated-device-assignment-test-key",
                device_type="air-quality-v1",
            ))
            await session.commit()
        response = await self.client.post(
            "/api/v1/devices/pair", json={"hardware_id": "VINE-A001"}, headers=self.headers(),
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    async def list_devices(self, space, user_id=1):
        response = await self.client.get(
            "/api/v1/devices", params={"space_id": space["id"], "page": 0, "size": 100},
            headers=self.headers(user_id),
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def test_claim_commits_space_assignment_visible_without_cellar_link_and_after_new_requests(self):
        space = await self.create_space("Coleccion2")
        other = await self.create_space("Otro espacio")
        cellar_id = UUID(space["default_wine_cellar"]["id"])
        paired = await self.pair_sensor()
        self.assertEqual((await self.list_devices(space))["total"], 0)
        response = await self.client.post(
            "/api/v1/devices/claim",
            json={"claim_token": paired["claim_token"], "space_id": space["id"]},
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 200, response.text)
        claimed = response.json()
        self.assertEqual(claimed["id"], paired["device_id"])
        self.assertEqual(claimed["space_id"], space["id"])
        self.assertEqual(claimed["serial_number"], "SN-0001")
        self.assertEqual(claimed["status"], "OFFLINE")

        # Independent DB session proves persistence, not just a mutated response.
        async with self.sessions() as session:
            assignment = await session.scalar(select(DeviceAssignmentORM).where(
                DeviceAssignmentORM.device_id == UUID(claimed["id"])
            ))
            self.assertEqual(assignment.space_id, UUID(space["id"]))
            self.assertEqual(assignment.owner_user_id, "1")
            self.assertIsNone((await session.get(WineCellarORM, cellar_id)).device_id)

        # Each HTTP GET gets a fresh session, as on immediate refresh/page reload
        # and the sensor picker in Edit cellar; OFFLINE/unlinked is still listed.
        for _ in range(2):
            page = await self.list_devices(space)
            self.assertEqual(page["total"], 1)
            self.assertEqual([item["id"] for item in page["items"]], [claimed["id"]])
            self.assertEqual(page["items"][0]["space_id"], space["id"])
        self.assertEqual((await self.list_devices(other))["items"], [])

        linked = await self.client.post(
            f"/api/v1/wine-cellars/{cellar_id}/devices",
            json={"device_id": claimed["id"]}, headers=self.headers(),
        )
        self.assertEqual(linked.status_code, 200, linked.text)
        self.assertEqual((await self.list_devices(space))["items"][0]["id"], claimed["id"])

    async def test_claim_and_list_do_not_allow_another_users_space(self):
        space = await self.create_space("Coleccion2")
        paired = await self.pair_sensor()
        denied = await self.client.post(
            "/api/v1/devices/claim",
            json={"claim_token": paired["claim_token"], "space_id": space["id"]},
            headers=self.headers(2),
        )
        self.assertEqual(denied.status_code, 403, denied.text)
        denied_list = await self.client.get(
            "/api/v1/devices", params={"space_id": space["id"]}, headers=self.headers(2),
        )
        self.assertEqual(denied_list.status_code, 403, denied_list.text)
        self.assertEqual((await self.list_devices(space))["items"], [])
