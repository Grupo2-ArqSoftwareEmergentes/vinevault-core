import unittest
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import delete, select, text, func
from sqlalchemy.exc import IntegrityError

from test_personal_context import PostgresAPITestCase
from app.core.database import Base
from app.core.security import create_access_token
from app.device.applications.space_authorization_service import SpaceAuthorizationService, SpacePermission, ALLOWED_ROLES
from app.device.domain.models.value_objects.space_access import SpaceRole
from app.device.infrastructure.database.models.space_member_orm import SpaceMemberORM
from app.device.infrastructure.database.models.space_orm import SpaceORM
from app.device.infrastructure.database.models.organization_orm import OrganizationORM
from app.device.infrastructure.database.models.device_orm import DeviceORM
from app.device.infrastructure.database.models.device_assignment_orm import DeviceAssignmentORM
from app.device.infrastructure.database.repositories.space_member_repository import SpaceMemberRepository
from app.wine_cellar.infrastructure.database.models.wine_cellar_orm import WineCellarORM
from app.iam.models import User


class SpaceRolePolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_role_matrix_and_missing_membership_are_deny_by_default(self):
        repository = SimpleNamespace(role_for=AsyncMock())
        policy = SpaceAuthorizationService(repository)
        for role in [None, *SpaceRole]:
            repository.role_for.return_value = role
            for permission in SpacePermission:
                if role in ALLOWED_ROLES[permission]:
                    self.assertEqual(await policy.require(uuid4(), 1, permission), role)
                else:
                    with self.assertRaises(PermissionError):
                        await policy.require(uuid4(), 1, permission)


class SpaceTenancyTests(PostgresAPITestCase):
    async def add_member(self, space, role, user_id=2):
        async with self.sessions() as session:
            session.add(SpaceMemberORM(space_id=UUID(space["id"]), user_id=user_id, role=role))
            await session.commit()

    async def test_onboarding_creates_owner_free_space_and_one_cellar_atomically(self):
        for purpose in ("Collector", "BUSINESS"):
            response = await self.client.post(
                "/api/v1/user/onboarding", json={"name": purpose, "space_type": purpose}, headers=self.headers(),
            )
            self.assertEqual(response.status_code, 201, response.text)
            space = response.json()
            self.assertEqual(space["space_type"], purpose.upper())
            self.assertEqual(space["subscription_plan"], "FREE")
            self.assertEqual(space["subscription_status"], "ACTIVE")
            self.assertEqual(space["role"], "OWNER")
            self.assertEqual(space["default_wine_cellar"]["space_id"], space["id"])
            async with self.sessions() as session:
                self.assertEqual(await session.scalar(select(SpaceMemberORM.role).where(
                    SpaceMemberORM.space_id == UUID(space["id"]), SpaceMemberORM.user_id == 1,
                )), SpaceRole.OWNER)
                self.assertEqual(await session.scalar(select(func.count()).select_from(WineCellarORM).where(
                    WineCellarORM.space_id == UUID(space["id"]),
                )), 1)
        for payload in ({"name": "Sin tipo"}, {"name": "Inválido", "space_type": "CORPORATE"}):
            response = await self.client.post("/api/v1/user/onboarding", json=payload, headers=self.headers())
            self.assertEqual(response.status_code, 422)

    async def test_failed_membership_insert_rolls_back_new_space_and_organization(self):
        original = SpaceMemberRepository.add_owner

        async def fail(repository, space_id, user_id):
            await original(repository, space_id, user_id)
            raise RuntimeError("membership failure")

        with patch.object(SpaceMemberRepository, "add_owner", fail):
            with self.assertRaisesRegex(RuntimeError, "membership failure"):
                await self.client.post(
                    "/api/v1/user/onboarding", json={"name": "Casa", "space_type": "COLLECTOR"}, headers=self.headers(),
                )
        async with self.sessions() as session:
            for model in (SpaceMemberORM, SpaceORM, WineCellarORM, OrganizationORM):
                self.assertEqual(await session.scalar(select(func.count()).select_from(model)), 0)

    async def test_context_and_roles_are_independent_for_each_space(self):
        owner_space = await self.create_space()
        response = await self.client.post(
            "/api/v1/spaces", json={"name": "Restaurante", "space_type": "BUSINESS"}, headers=self.headers(2),
        )
        shared = response.json()
        await self.add_member(shared, SpaceRole.WAITER, user_id=1)
        async with self.sessions() as session:
            stored = await session.get(SpaceORM, UUID(shared["id"]))
            stored.subscription_plan = "BUSINESS"
            stored.subscription_status = "EXPIRED"
            await session.commit()
        context = (await self.client.get("/api/v1/user/context", headers=self.headers())).json()
        indexed = {space["id"]: space for space in context["spaces"]}
        self.assertEqual(indexed[owner_space["id"]]["role"], "OWNER")
        self.assertEqual(indexed[owner_space["id"]]["subscription_plan"], "FREE")
        self.assertEqual(indexed[shared["id"]]["role"], "WAITER")
        self.assertEqual(indexed[shared["id"]]["space_type"], "BUSINESS")
        self.assertEqual(indexed[shared["id"]]["subscription_status"], "EXPIRED")
        self.assertEqual(len(context["wine_cellars"]), 2)
        self.assertEqual(len((await self.client.get("/api/v1/spaces", headers=self.headers())).json()), 2)
        self.assertEqual(len((await self.client.get("/api/v1/wine-cellars", headers=self.headers())).json()), 2)

    async def test_waiter_reads_shared_space_but_cannot_modify_it(self):
        space = await self.create_space()
        await self.add_member(space, SpaceRole.WAITER)
        cellar = space["default_wine_cellar"]
        for path in (f"/api/v1/spaces/{space['id']}", f"/api/v1/spaces/{space['id']}/wine-cellars"):
            response = await self.client.get(path, headers=self.headers(2))
            self.assertEqual(response.status_code, 200, response.text)
        operations = [
            ("PATCH", f"/api/v1/spaces/{space['id']}/name", {"name": "No"}),
            ("DELETE", f"/api/v1/spaces/{space['id']}", None),
            ("POST", f"/api/v1/spaces/{space['id']}/wine-cellars", {"name": "No"}),
            ("DELETE", f"/api/v1/wine-cellars/{cellar['id']}", None),
            ("POST", f"/api/v1/wine-cellars/{cellar['id']}/inventory", {"wine_name": "No", "wine_type": "Tinto", "quantity": 1, "age_years": 1}),
            ("POST", "/api/v1/ai/analyze-stock", {"wine_cellar_id": cellar["id"]}),
        ]
        for method, path, body in operations:
            response = await self.client.request(method, path, json=body, headers=self.headers(2))
            self.assertEqual(response.status_code, 403, response.text)
        own = await self.create_space(user_id=2)
        response = await self.client.patch(f"/api/v1/spaces/{own['id']}/name", json={"name": "Permitido"}, headers=self.headers(2))
        self.assertEqual(response.status_code, 200)

    async def test_inventory_clerk_and_sommelier_have_different_write_permissions(self):
        space = await self.create_space()
        await self.add_member(space, SpaceRole.INVENTORY_CLERK)
        await self.create_inventory(space["default_wine_cellar"], user_id=2)
        response = await self.client.post(f"/api/v1/spaces/{space['id']}/wine-cellars", json={"name": "No"}, headers=self.headers(2))
        self.assertEqual(response.status_code, 403)
        async with self.sessions() as session:
            membership = await session.get(SpaceMemberORM, (UUID(space["id"]), 2))
            membership.role = SpaceRole.SOMMELIER
            await session.commit()
        await self.create_cellar(space, user_id=2)
        response = await self.client.delete(f"/api/v1/spaces/{space['id']}", headers=self.headers(2))
        self.assertEqual(response.status_code, 403)

    async def test_creator_marker_and_global_admin_do_not_bypass_membership(self):
        space = await self.create_space()
        async with self.sessions() as session:
            await session.execute(delete(SpaceMemberORM).where(SpaceMemberORM.space_id == UUID(space["id"])))
            user = await session.get(User, 1)
            user.is_superuser = True
            await session.commit()
        response = await self.client.get(f"/api/v1/spaces/{space['id']}", headers=self.headers())
        self.assertEqual(response.status_code, 403)
        context = await self.client.get("/api/v1/user/context", headers=self.headers())
        self.assertEqual(context.json(), {"spaces": [], "wine_cellars": []})

    async def test_revoked_membership_and_refresh_token_are_denied(self):
        space = await self.create_space()
        await self.add_member(space, SpaceRole.WAITER)
        async with self.sessions() as session:
            await session.execute(delete(SpaceMemberORM).where(SpaceMemberORM.space_id == UUID(space["id"]), SpaceMemberORM.user_id == 2))
            await session.commit()
        response = await self.client.get(f"/api/v1/spaces/{space['id']}", headers=self.headers(2))
        self.assertEqual(response.status_code, 403)
        token = create_access_token({"sub": "1", "type": "refresh"})
        response = await self.client.get("/api/v1/user/context", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(response.status_code, 401)

    async def test_client_cannot_escalate_plan_or_role_during_space_creation(self):
        response = await self.client.post("/api/v1/spaces", json={
            "name": "Casa", "space_type": "COLLECTOR", "subscription_plan": "BUSINESS",
            "subscription_status": "EXPIRED", "role": "SOMMELIER",
        }, headers=self.headers())
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["subscription_plan"], "FREE")
        self.assertEqual(response.json()["subscription_status"], "ACTIVE")
        self.assertEqual(response.json()["role"], "OWNER")

    async def test_inactive_and_nonexistent_identities_cannot_access_spaces(self):
        space = await self.create_space()
        async with self.sessions() as session:
            user = await session.get(User, 1)
            user.is_active = False
            await session.commit()
        for user_id in (1, 999):
            response = await self.client.get(f"/api/v1/spaces/{space['id']}", headers=self.headers(user_id))
            self.assertEqual(response.status_code, 401)

    async def test_member_foreign_keys_and_unique_membership_are_enforced(self):
        space = await self.create_space()
        for user_id, space_id in ((1, UUID(space["id"])), (999, UUID(space["id"])), (2, uuid4())):
            async with self.sessions() as session:
                session.add(SpaceMemberORM(space_id=space_id, user_id=user_id, role=SpaceRole.WAITER))
                with self.assertRaises(IntegrityError):
                    await session.commit()

    async def test_device_routes_resolve_membership_not_assignment_creator(self):
        space = await self.create_space()
        await self.add_member(space, SpaceRole.WAITER)
        async with self.sessions() as session:
            device = DeviceORM(serial_number="tenant-device", name="Sensor", factory_name="Factory", hardware_id="VINE-TEST", api_key=uuid4().hex, device_type="air-quality-v1")
            session.add(device)
            await session.flush()
            device_id = str(device.id)
            session.add(DeviceAssignmentORM(device_id=device.id, space_id=UUID(space["id"]), owner_user_id="1"))
            await session.commit()
        for path in (f"/api/v1/devices/{device_id}", f"/api/v1/devices/{device_id}/status", f"/api/v1/devices/{device_id}/thresholds", f"/api/v1/devices/{device_id}/alerts"):
            self.assertEqual((await self.client.get(path, headers=self.headers(2))).status_code, 200)
            self.assertEqual((await self.client.get(path, headers=self.headers(3))).status_code, 403)
        response = await self.client.patch(f"/api/v1/devices/{device_id}/name", json={"name": "No"}, headers=self.headers(2))
        self.assertEqual(response.status_code, 403)
        async with self.sessions() as session:
            membership = await session.get(SpaceMemberORM, (UUID(space["id"]), 2))
            membership.role = SpaceRole.SOMMELIER
            await session.commit()
        response = await self.client.patch(f"/api/v1/devices/{device_id}/name", json={"name": "Nuevo"}, headers=self.headers(2))
        self.assertEqual(response.status_code, 200, response.text)

    async def test_quick_identity_registration_and_email_login(self):
        response = await self.client.post("/api/v1/iam/register", json={
            "email": "new@example.com", "password": "password123", "full_name": "Nueva Persona",
        })
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["full_name"], "Nueva Persona")
        response = await self.client.post("/api/v1/iam/login", data={"username": "new@example.com", "password": "password123"})
        self.assertEqual(response.status_code, 200, response.text)
        headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
        self.assertEqual((await self.client.get("/api/v1/user/context", headers=headers)).json(), {"spaces": [], "wine_cellars": []})
        async with self.sessions() as session:
            self.assertEqual(await session.scalar(select(func.count()).select_from(SpaceORM)), 0)


def upgrade_database(connection):
    config = Config("alembic.ini")
    config.attributes["connection"] = connection
    command.upgrade(config, "head")


class SpaceMigrationTests(PostgresAPITestCase):
    async def legacy_schema(self, connection):
        await connection.execute(text("DROP TABLE space_members"))
        for column in ("space_type", "subscription_plan", "subscription_status"):
            await connection.execute(text(f"ALTER TABLE spaces DROP COLUMN {column}"))
        await connection.execute(text("ALTER TABLE users DROP COLUMN full_name"))

    async def test_legacy_upgrade_preserves_data_and_backfills_owner_memberships(self):
        space = await self.create_space()
        async with self.engine.begin() as connection:
            await self.legacy_schema(connection)
            await connection.run_sync(upgrade_database)
        async with self.sessions() as session:
            self.assertEqual(await session.scalar(select(SpaceMemberORM.role)), SpaceRole.OWNER)
            migrated = await session.get(SpaceORM, UUID(space["id"]))
            self.assertEqual(migrated.space_type.value, "COLLECTOR")
            self.assertEqual(migrated.subscription_plan.value, "FREE")
            self.assertEqual(await session.scalar(select(func.count()).select_from(WineCellarORM)), 1)
            self.assertEqual((await session.get(User, 1)).full_name, "testuser1")
        # Running the command again must not duplicate memberships.
        async with self.engine.begin() as connection:
            await connection.run_sync(upgrade_database)

    async def test_fresh_database_can_be_initialized_through_alembic(self):
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)  # Only this test's temporary schema.
            await connection.run_sync(upgrade_database)
        async with self.sessions() as session:
            self.assertEqual(await session.scalar(select(func.count()).select_from(SpaceMemberORM)), 0)

    async def test_orphan_legacy_owner_aborts_migration(self):
        space = await self.create_space()
        async with self.engine.begin() as connection:
            await self.legacy_schema(connection)
            await connection.execute(text("UPDATE spaces SET owner_user_id='999'"))
        with self.assertRaisesRegex(RuntimeError, "missing owner identities"):
            async with self.engine.begin() as connection:
                await connection.run_sync(upgrade_database)
