"""Atomic, repeatable reconciliation of the development factory inventory."""
from pathlib import Path
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.device.domain.models import Device
from app.device.domain.models.value_objects import ApiKey
from app.device.infrastructure.database.models.device_orm import DeviceORM


FACTORY_DEVICES_FILE = Path(__file__).with_name("factory_devices.txt")
FACTORY_DEVICE_COUNT = 50


def factory_device_specs() -> list[tuple[str, str, str, str, str]]:
    specs = [
        tuple(part.strip() for part in line.split("|"))
        for raw in FACTORY_DEVICES_FILE.read_text(encoding="utf-8").splitlines()
        if (line := raw.strip()) and not line.startswith("#")
    ]
    expected = [
        (f"SN-{i:04d}", f"Sensor {i:04d}", f"Sensor {i:04d}", f"VINE-A{i:03d}", "air-quality-v1")
        for i in range(1, FACTORY_DEVICE_COUNT + 1)
    ]
    if specs != expected:
        raise ValueError("Factory inventory must contain the canonical SN-0001 through SN-0050 records")
    return specs


def _unique_api_key(occupied: set[str]) -> str:
    candidate = ApiKey.generate().value
    while candidate in occupied:
        candidate = ApiKey.generate().value
    occupied.add(candidate)
    return candidate


async def reconcile_factory_devices(session: AsyncSession) -> list[tuple[Device, str]]:
    """Own one transaction; preserve identities, credentials and tenant assignments.

    Serialize startup seeders and other device writers before reading identifiers.
    The short table lock also prevents a concurrent insert from taking a chosen
    hardware ID/API key between our lookup and flush. No unrelated rows are deleted.
    Canonical hardware IDs are reserved by serial; conflicts abort without stealing
    another device's identity or partially normalizing the inventory.
    """
    specs = factory_device_specs()
    async with session.begin():
        await session.execute(text("LOCK TABLE devices IN SHARE ROW EXCLUSIVE MODE"))
        existing = {row.serial_number: row for row in await session.scalars(
            select(DeviceORM).where(DeviceORM.serial_number.in_([spec[0] for spec in specs]))
        )}
        identifiers = (await session.execute(select(
            DeviceORM.serial_number, DeviceORM.hardware_id, DeviceORM.api_key,
        ))).all()
        hardware_owners = {row.hardware_id: row.serial_number for row in identifiers}
        for serial, _, _, hardware_id, _ in specs:
            owner = hardware_owners.get(hardware_id)
            if owner is not None and owner != serial:
                raise ValueError(
                    f"Cannot normalize {serial}: hardware ID {hardware_id} belongs to {owner}; "
                    "resolve the hardware ID conflict before restarting"
                )
        api_keys = {row.api_key for row in identifiers}
        changed = []
        for serial, name, factory_name, hardware_id, device_type in specs:
            row = existing.get(serial)
            if row is None:
                row = DeviceORM(
                    serial_number=serial, name=name, factory_name=factory_name,
                    hardware_id=hardware_id,
                    api_key=_unique_api_key(api_keys), device_type=device_type,
                )
                session.add(row)
                changed.append((row, "CREATED"))
                continue

            before = (row.name, row.factory_name, row.hardware_id, row.api_key, row.device_type)
            row.name, row.factory_name, row.device_type = name, factory_name, device_type
            row.hardware_id = hardware_id
            if not row.api_key or not row.api_key.strip():
                row.api_key = _unique_api_key(api_keys)
            if before != (row.name, row.factory_name, row.hardware_id, row.api_key, row.device_type):
                changed.append((row, "UPDATED"))

        await session.flush()
        result = [(row.to_domain(), change_type) for row, change_type in changed]
    return result
