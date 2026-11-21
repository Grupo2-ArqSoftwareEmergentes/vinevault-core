"""Optional cellar selection is an atomic part of claiming a device."""
import asyncio
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

from sqlalchemy import select

from app.device.infrastructure.database.models.device_orm import DeviceORM
from app.device.infrastructure.database.models.device_assignment_orm import DeviceAssignmentORM
from app.wine_cellar.infrastructure.database.models.wine_cellar_orm import WineCellarORM
from app.wine_cellar.interfaces.acl import DeviceCellarACL
from test_personal_context import PostgresAPITestCase


class DeviceCellarBindingTests(PostgresAPITestCase):
    async def pair(self, index=1):
        async with self.sessions() as session:
            session.add(DeviceORM(serial_number=f"SN-{index:04d}", name=f"Mi sensor {index}", factory_name=f"Factory {index}",
                hardware_id=f"VINE-A{index:03d}", api_key=f"isolated-cellar-binding-{index}", device_type="air-quality-v1"))
            await session.commit()
        response = await self.client.post("/api/v1/devices/pair", json={"hardware_id": f"VINE-A{index:03d}"}, headers=self.headers())
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    async def claim(self, pairing, space, cellar_id=None, user_id=1):
        return await self.client.post("/api/v1/devices/claim", json={
            "claim_token": pairing["claim_token"], "space_id": space["id"], "cellar_id": cellar_id,
        }, headers=self.headers(user_id))

    async def assert_unclaimed(self, pairing):
        async with self.sessions() as session:
            assignment = await session.scalar(select(DeviceAssignmentORM).where(DeviceAssignmentORM.device_id == UUID(pairing["device_id"])))
            self.assertIsNone(assignment.space_id)
            self.assertIsNone(assignment.owner_user_id)
            self.assertEqual(assignment.claim_token, pairing["claim_token"])

    async def test_claim_list_detail_and_unlink_return_consistent_cellar_fields_and_device_name(self):
        space = await self.create_space("Mi colección")
        cellar = space["default_wine_cellar"]
        pairing = await self.pair()
        claimed = await self.claim(pairing, space, cellar["id"])
        self.assertEqual(claimed.status_code, 200, claimed.text)
        for item in [claimed.json(),
            (await self.client.get(f"/api/v1/devices/{pairing['device_id']}", headers=self.headers())).json(),
            (await self.client.get(f"/api/v1/devices?space_id={space['id']}", headers=self.headers())).json()["items"][0]]:
            self.assertEqual(item["cellar_id"], cellar["id"])
            self.assertEqual(item["cellar_name"], cellar["name"])
            self.assertEqual(item["name"], "Mi sensor 1")
            self.assertNotIn("factory_name", item)
        async with self.sessions() as session:
            self.assertEqual((await session.get(WineCellarORM, UUID(cellar["id"]))).device_id, UUID(pairing["device_id"]))
            stored = await session.get(WineCellarORM, UUID(cellar["id"]))
            stored.name = "Cava renombrada"
            await session.commit()
        detail = await self.client.get(f"/api/v1/devices/{pairing['device_id']}", headers=self.headers())
        self.assertEqual(detail.json()["cellar_name"], "Cava renombrada")
        unlinked = await self.client.delete(f"/api/v1/wine-cellars/{cellar['id']}/devices/{pairing['device_id']}", headers=self.headers())
        self.assertEqual(unlinked.status_code, 204, unlinked.text)
        detail = await self.client.get(f"/api/v1/devices/{pairing['device_id']}", headers=self.headers())
        self.assertIsNone(detail.json()["cellar_id"])
        self.assertIsNone(detail.json()["cellar_name"])

    async def test_without_optional_cellar_claim_stays_unlinked(self):
        space = await self.create_space()
        pairing = await self.pair()
        response = await self.claim(pairing, space)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json()["cellar_id"])
        self.assertIsNone(response.json()["cellar_name"])

    async def test_cross_space_missing_and_occupied_cellars_do_not_consume_token(self):
        space = await self.create_space()
        other = await self.create_space("Otra colección")
        pairing = await self.pair()
        for cellar_id, status in [(other["default_wine_cellar"]["id"], 409), (str(uuid4()), 404)]:
            response = await self.claim(pairing, space, cellar_id)
            self.assertEqual(response.status_code, status, response.text)
            await self.assert_unclaimed(pairing)
        occupied = await self.pair(2)
        response = await self.claim(occupied, space, space["default_wine_cellar"]["id"])
        self.assertEqual(response.status_code, 200, response.text)
        response = await self.claim(pairing, space, space["default_wine_cellar"]["id"])
        self.assertEqual(response.status_code, 409, response.text)
        await self.assert_unclaimed(pairing)

    async def test_other_account_cannot_claim_or_associate_to_the_space(self):
        space = await self.create_space()
        pairing = await self.pair()
        denied = await self.claim(pairing, space, space["default_wine_cellar"]["id"], user_id=2)
        self.assertEqual(denied.status_code, 403, denied.text)
        await self.assert_unclaimed(pairing)

    async def test_concurrent_claims_to_one_cellar_have_one_winner(self):
        space = await self.create_space()
        first, second = await self.pair(), await self.pair(2)
        results = await asyncio.gather(*(self.claim(pairing, space, space["default_wine_cellar"]["id"]) for pairing in (first, second)))
        self.assertEqual(sorted(response.status_code for response in results), [200, 409])
        loser = first if results[0].status_code == 409 else second
        await self.assert_unclaimed(loser)
        listed = await self.client.get(f"/api/v1/devices?space_id={space['id']}", headers=self.headers())
        self.assertEqual(listed.json()["total"], 1)
        self.assertEqual(listed.json()["items"][0]["cellar_id"], space["default_wine_cellar"]["id"])

    async def test_failed_cellar_write_rolls_back_device_claim(self):
        space = await self.create_space()
        pairing = await self.pair()
        with patch.object(DeviceCellarACL, "link", AsyncMock(side_effect=RuntimeError("storage unavailable"))):
            with self.assertRaises(RuntimeError):
                await self.claim(pairing, space, space["default_wine_cellar"]["id"])
        await self.assert_unclaimed(pairing)
        async with self.sessions() as session:
            self.assertIsNone((await session.get(WineCellarORM, UUID(space["default_wine_cellar"]["id"]))).device_id)
