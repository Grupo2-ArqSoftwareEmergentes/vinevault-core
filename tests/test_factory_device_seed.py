"""Startup factory seed checks, isolated from public data and Kafka."""
import asyncio
import unittest
from unittest.mock import AsyncMock, patch
from uuid import UUID

from sqlalchemy import delete, select

from app.device.domain.models.value_objects import HardwareId
from app.device.infrastructure.database.models.device_assignment_orm import DeviceAssignmentORM
from app.device.infrastructure.database.models.device_orm import DeviceORM
from app.device.infrastructure.seeds.factory_inventory import factory_device_specs, reconcile_factory_devices
from app.main import seed_factory_devices, seed_fixed_factory_devices
from test_personal_context import PostgresAPITestCase


class FactoryManifestTests(unittest.TestCase):
    def test_manifest_has_exactly_fifty_canonical_devices(self):
        specs = factory_device_specs()
        self.assertEqual(len(specs), 50)
        for index, (serial, name, factory_name, hardware_id, device_type) in enumerate(specs, 1):
            self.assertEqual(serial, f"SN-{index:04d}")
            self.assertEqual(name, f"Sensor {index:04d}")
            self.assertEqual(factory_name, name)
            self.assertEqual(hardware_id, f"VINE-A{index:03d}")
            self.assertEqual(device_type, "air-quality-v1")
            HardwareId(value=hardware_id)


class FactoryDeviceSeedTests(PostgresAPITestCase):
    async def seed(self, publisher=None):
        with patch("app.main.AsyncSessionLocal", self.sessions):
            await seed_factory_devices(publisher)

    async def snapshot(self):
        async with self.sessions() as session:
            return (await session.execute(select(
                DeviceORM.id, DeviceORM.serial_number, DeviceORM.name, DeviceORM.factory_name,
                DeviceORM.hardware_id, DeviceORM.api_key, DeviceORM.device_type,
                DeviceORM.created_at, DeviceORM.updated_at,
            ).order_by(DeviceORM.serial_number))).all()

    async def test_empty_database_and_repeated_startup_are_idempotent(self):
        publisher = AsyncMock()
        await self.seed(publisher)
        rows = await self.snapshot()
        self.assertEqual(len(rows), 50)
        self.assertEqual(publisher.publish_device_changed.await_count, 50)
        for index, row in enumerate(rows, 1):
            self.assertEqual(row.serial_number, f"SN-{index:04d}")
            self.assertEqual(row.name, f"Sensor {index:04d}")
            self.assertEqual(row.factory_name, row.name)
            self.assertEqual(row.hardware_id, f"VINE-A{index:03d}")
            self.assertEqual(row.device_type, "air-quality-v1")
            self.assertTrue(row.api_key.strip())
        self.assertEqual(len({row.api_key for row in rows}), 50)
        publisher.reset_mock()
        await self.seed(publisher)
        with patch("app.main.AsyncSessionLocal", self.sessions):
            await seed_fixed_factory_devices(publisher)
        self.assertEqual(await self.snapshot(), rows)
        publisher.publish_device_changed.assert_not_awaited()
        publisher.publish_assignment_changed.assert_not_awaited()

    async def test_legacy_seven_are_normalized_without_losing_identity_or_assignments(self):
        space = await self.create_space()
        async with self.sessions() as session:
            devices = [DeviceORM(
                serial_number=f"SN-{i:04d}", name=f"Sensor {i}" if i <= 5 else f"Sensor {i:04d}",
                factory_name=f"Sensor {i}" if i <= 5 else f"Sensor {i:04d}",
                hardware_id=f"VINE-A{i:03d}" if i <= 5 else f"HW-{i:04d}",
                api_key=f"existing-key-{i}", device_type="air-quality-v1",
            ) for i in range(1, 8)]
            session.add_all(devices)
            await session.flush()
            assignment = DeviceAssignmentORM(
                device_id=devices[5].id, owner_user_id="1", space_id=UUID(space["id"]),
                status="ONLINE", configuration={"preserve": "yes"},
            )
            session.add(assignment)
            await session.commit()
            identities = [(d.id, d.hardware_id, d.api_key) for d in devices]
            assignment_id = assignment.id

        publisher = AsyncMock()
        await self.seed(publisher)
        rows = await self.snapshot()
        self.assertEqual(len(rows), 50)
        for i, row in enumerate(rows[:7], 1):
            self.assertEqual((row.id, row.api_key), (identities[i - 1][0], identities[i - 1][2]))
            self.assertEqual(row.hardware_id, f"VINE-A{i:03d}")
            self.assertEqual(row.name, f"Sensor {i:04d}")
            self.assertEqual(row.factory_name, row.name)
        async with self.sessions() as session:
            assignment = await session.get(DeviceAssignmentORM, assignment_id)
            self.assertEqual(assignment.space_id, UUID(space["id"]))
            self.assertEqual(assignment.status, "ONLINE")
            self.assertEqual(assignment.configuration, {"preserve": "yes"})
        publisher.publish_assignment_changed.assert_awaited_once()
        published = publisher.publish_assignment_changed.call_args.args[0]
        self.assertEqual(published.device.name, "Sensor 0006")
        self.assertEqual(published.device.hardware_id.value, "VINE-A006")
        self.assertEqual(published.status.value, "ONLINE")
        self.assertEqual(published.space_id, UUID(space["id"]))
        events = [call.args[0] for call in publisher.publish_device_changed.call_args_list
                  if call.args[0].serial_number == "SN-0007"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].hardware_id.value, "VINE-A007")
        publisher.reset_mock()
        await self.seed(publisher)
        self.assertEqual(await self.snapshot(), rows)
        publisher.publish_device_changed.assert_not_awaited()
        publisher.publish_assignment_changed.assert_not_awaited()

    async def test_missing_records_are_recreated_without_touching_other_forty_eight(self):
        await self.seed()
        before = await self.snapshot()
        missing = {"SN-0008", "SN-0050"}
        async with self.sessions() as session:
            await session.execute(delete(DeviceORM).where(DeviceORM.serial_number.in_(missing)))
            await session.commit()
        publisher = AsyncMock()
        await self.seed(publisher)
        after = await self.snapshot()
        self.assertEqual(len(after), 50)
        self.assertEqual([r for r in after if r.serial_number not in missing],
                         [r for r in before if r.serial_number not in missing])
        self.assertEqual(publisher.publish_device_changed.await_count, 2)

    async def test_simultaneous_startups_create_only_fifty_devices(self):
        await asyncio.gather(self.seed(), self.seed(), self.seed())
        self.assertEqual(len(await self.snapshot()), 50)

    async def test_hardware_collision_aborts_without_mutating_any_devices(self):
        async with self.sessions() as session:
            session.add_all([
                DeviceORM(serial_number="CUSTOM-1", name="Custom", factory_name="Custom",
                          hardware_id="VINE-A001", api_key="custom-key", device_type="custom-v1"),
                DeviceORM(serial_number="SN-0007", name="Old", factory_name="Old",
                          hardware_id="invalid", api_key=" ", device_type="legacy"),
            ])
            await session.commit()
        before = await self.snapshot()
        publisher = AsyncMock()
        with self.assertRaisesRegex(ValueError, "VINE-A001 belongs to CUSTOM-1"):
            await self.seed(publisher)
        self.assertEqual(await self.snapshot(), before)
        publisher.publish_device_changed.assert_not_awaited()
        publisher.publish_assignment_changed.assert_not_awaited()

    async def test_blank_legacy_fields_are_repaired_and_unrelated_devices_preserved(self):
        async with self.sessions() as session:
            session.add_all([
                DeviceORM(serial_number="CUSTOM-1", name="Custom", factory_name="Custom",
                          hardware_id="VINE-Z999", api_key="custom-key", device_type="custom-v1"),
                DeviceORM(serial_number="SN-0007", name="Old", factory_name="Old",
                          hardware_id="invalid", api_key=" ", device_type="legacy"),
            ])
            await session.commit()
        await self.seed()
        rows = await self.snapshot()
        self.assertEqual(len(rows), 51)  # Never delete unrelated devices to force a total of 50.
        custom = next(row for row in rows if row.serial_number == "CUSTOM-1")
        self.assertEqual((custom.name, custom.hardware_id, custom.api_key, custom.device_type),
                         ("Custom", "VINE-Z999", "custom-key", "custom-v1"))
        factory = [row for row in rows if row.serial_number.startswith("SN-")]
        self.assertEqual(len(factory), 50)
        for row in factory:
            HardwareId(value=row.hardware_id)
            self.assertEqual(row.hardware_id, f"VINE-A{int(row.serial_number[3:]):03d}")
            self.assertTrue(row.api_key.strip())
            self.assertEqual(row.device_type, "air-quality-v1")
        self.assertEqual(len({row.hardware_id for row in rows}), 51)
        self.assertEqual(len({row.api_key for row in rows}), 51)
        await self.seed()
        self.assertEqual(await self.snapshot(), rows)

    async def test_failure_rolls_back_the_entire_seed(self):
        async with self.sessions() as session:
            with patch.object(DeviceORM, "to_domain", side_effect=RuntimeError("simulated failure")):
                with self.assertRaisesRegex(RuntimeError, "simulated failure"):
                    await reconcile_factory_devices(session)
        self.assertEqual(await self.snapshot(), [])
