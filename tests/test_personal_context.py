"""API integration checks against PostgreSQL, isolated in a temporary schema.

Set TEST_DATABASE_URL to an explicit postgresql+asyncpg:// URL before running.
The normal app lifespan (including factory/edge seeds) is deliberately not run.
"""
import asyncio
import os
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx
from sqlalchemy import event, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base, get_db
from app.core.security import create_access_token
from app.device.infrastructure.database.models.organization_orm import OrganizationORM
from app.device.infrastructure.database.models.space_orm import SpaceORM
from app.device.infrastructure.database.models.device_orm import DeviceORM
from app.device.infrastructure.database.models.device_assignment_orm import DeviceAssignmentORM
from app.device.infrastructure.database.repositories.space_repository import SpaceRepository
from app.wine_cellar.infrastructure.database.models.wine_cellar_orm import WineCellarORM
from app.wine_cellar.infrastructure.database.models.wine_inventory_item_orm import WineInventoryItemORM
from app.wine_cellar.infrastructure.database.repositories.wine_cellar_repository import WineCellarRepository
from app.wine_cellar.infrastructure.database.repositories.wine_inventory_repository import WineInventoryRepository
from app.main import app
from app.iam.models import User


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "Set TEST_DATABASE_URL to run PostgreSQL checks")
class PostgresAPITestCase(unittest.IsolatedAsyncioTestCase):
    # Non-quota suites get explicit purchased capacity for their multi-space/cellar fixtures.
    extra_spaces_allowance = 10
    extra_cellars_allowance = 10

    async def asyncSetUp(self):
        self.schema = f"test_personal_context_{uuid4().hex}"
        url = os.environ["TEST_DATABASE_URL"]
        self.admin_engine = create_async_engine(url)
        async with self.admin_engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.engine = create_async_engine(
            url, connect_args={"server_settings": {"search_path": self.schema}}
        )
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with self.sessions() as session:
            session.add_all([
                User(id=i, username=f"testuser{i}", email=f"test{i}@example.com", hashed_password="not-used", full_name=f"User {i}", extra_spaces_allowance=self.extra_spaces_allowance)
                for i in (1, 2, 3)
            ])
            await session.flush()
            await session.execute(text("SELECT setval(pg_get_serial_sequence('users', 'id'), 3, true)"))
            await session.commit()

        async def override_db():
            async with self.sessions() as session:
                yield session

        app.dependency_overrides[get_db] = override_db
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    async def asyncTearDown(self):
        await self.client.aclose()
        app.dependency_overrides.pop(get_db, None)
        await self.engine.dispose()
        async with self.admin_engine.begin() as connection:
            # Only remove the unique schema created by this test, never public tables.
            await connection.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        await self.admin_engine.dispose()

    def headers(self, user_id=1):
        return {"Authorization": f"Bearer {create_access_token({'sub': str(user_id)})}"}

    async def create_space(self, name="Casa", user_id=1):
        response = await self.client.post(
            "/api/v1/spaces", json={"name": name}, headers=self.headers(user_id)
        )
        self.assertEqual(response.status_code, 201, response.text)
        resource = response.json()
        if self.extra_cellars_allowance:
            async with self.sessions() as session:
                space = await session.get(SpaceORM, UUID(resource["id"]))
                space.extra_cellars_allowance = self.extra_cellars_allowance
                await session.commit()
            resource["extra_cellars_allowance"] = self.extra_cellars_allowance
        return resource

    async def create_cellar(self, space, user_id=1):
        response = await self.client.post(
            f"/api/v1/spaces/{space['id']}/wine-cellars",
            json={"name": "Cava"}, headers=self.headers(user_id),
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    async def create_inventory(self, cellar, user_id=1):
        response = await self.client.post(
            f"/api/v1/wine-cellars/{cellar['id']}/inventory",
            json={"wine_name": "Reserva", "wine_type": "Tinto", "age_years": 2, "quantity": 3},
            headers=self.headers(user_id),
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

class PersonalContextTests(PostgresAPITestCase):
    async def test_personal_organization_is_transparent_and_reused(self):
        first = await self.create_space()
        second = await self.create_space("Departamento")
        self.assertEqual(first["organization_id"], second["organization_id"])
        self.assertEqual(first["owner_user_id"], 1)
        async with self.sessions() as session:
            self.assertEqual(await session.scalar(select(func.count()).select_from(OrganizationORM)), 1)
        context = await self.client.get("/api/v1/user/context", headers=self.headers())
        self.assertEqual(context.status_code, 200)
        self.assertEqual(len(context.json()["spaces"]), 2)
        self.assertEqual(len(context.json()["wine_cellars"]), 2)
        self.assertEqual(context.json()["spaces"][0]["role"], "OWNER")

    async def test_existing_organization_and_legacy_routes_still_work(self):
        organization = await self.client.post(
            "/api/v1/organizations", json={"name": "Existente"}, headers=self.headers()
        )
        self.assertEqual(organization.status_code, 201)
        org_id = organization.json()["id"]
        direct = await self.create_space()
        self.assertEqual(direct["organization_id"], org_id)
        legacy = await self.client.post(
            f"/api/v1/organizations/{org_id}/spaces",
            json={"name": "Legado"}, headers=self.headers(),
        )
        self.assertEqual(legacy.status_code, 201, legacy.text)
        self.assertEqual(legacy.json()["default_wine_cellar"]["space_id"], legacy.json()["id"])
        response = await self.client.get(
            f"/api/v1/organizations/{org_id}/spaces", headers=self.headers()
        )
        self.assertEqual(len(response.json()), 2)
        async with self.sessions() as session:
            for space_id in (direct["id"], legacy.json()["id"]):
                self.assertEqual(await session.scalar(
                    select(func.count()).select_from(WineCellarORM)
                    .where(WineCellarORM.space_id == space_id)
                ), 1)

    async def test_context_and_cellar_filter_are_tenant_scoped(self):
        own = await self.create_space()
        other_space = await self.create_space("Otro espacio")
        foreign = await self.create_space(user_id=2)
        own_cellar = await self.create_cellar(own)
        await self.create_cellar(other_space)
        foreign_cellar = await self.create_cellar(foreign, user_id=2)
        statements = []

        def record_statement(connection, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(self.engine.sync_engine, "before_cursor_execute", record_statement)
        try:
            response = await self.client.get("/api/v1/user/context", headers=self.headers())
        finally:
            event.remove(self.engine.sync_engine, "before_cursor_execute", record_statement)
        self.assertEqual(len(statements), 8, statements)  # identity, directory, effective tiers/extras and bounded quota aggregates
        self.assertEqual(response.status_code, 200)
        context = response.json()
        self.assertEqual(len(context["spaces"]), 2)
        self.assertEqual(len(context["wine_cellars"]), 4)
        self.assertNotIn(foreign_cellar["id"], [c["id"] for c in context["wine_cellars"]])
        for parameter in ("space_id", "spaceId"):
            response = await self.client.get(
                "/api/v1/wine-cellars", params={parameter: own["id"]}, headers=self.headers()
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                {c["id"] for c in response.json()},
                {own_cellar["id"], own["default_wine_cellar"]["id"]},
            )
        all_cellars = await self.client.get("/api/v1/wine-cellars", headers=self.headers())
        self.assertEqual(len(all_cellars.json()), 4)
        forbidden_paths = [
            f"/api/v1/wine-cellars?spaceId={foreign['id']}",
            f"/api/v1/spaces/{foreign['id']}/wine-cellars",
            f"/api/v1/spaces/{foreign['id']}",
        ]
        for path in forbidden_paths:
            response = await self.client.get(path, headers=self.headers())
            self.assertEqual(response.status_code, 403, response.text)
        response = await self.client.put(
            f"/api/v1/wine-cellars/{foreign_cellar['id']}",
            json={"name": "Intrusión"}, headers=self.headers(),
        )
        self.assertEqual(response.status_code, 403)
        response = await self.client.post(
            f"/api/v1/spaces/{foreign['id']}/wine-cellars",
            json={"name": "Intrusión"}, headers=self.headers(),
        )
        self.assertEqual(response.status_code, 403)
        response = await self.client.get("/api/v1/user/context", headers=self.headers(3))
        self.assertEqual(response.json()["spaces"], [])
        self.assertEqual(response.json()["wine_cellars"], [])

    async def test_jwt_is_required_and_invalid_input_does_not_create_organization(self):
        for headers in ({}, {"Authorization": "Bearer invalid"}):
            for path in ("/api/v1/user/context", "/api/v1/wine-cellars", "/api/v1/spaces"):
                response = await self.client.get(path, headers=headers)
                self.assertIn(response.status_code, (401, 403))
            response = await self.client.post("/api/v1/spaces", json={"name": "Casa"}, headers=headers)
            self.assertIn(response.status_code, (401, 403))
        response = await self.client.post(
            "/api/v1/spaces", json={"name": "   "}, headers=self.headers()
        )
        self.assertEqual(response.status_code, 422)
        async with self.sessions() as session:
            self.assertEqual(await session.scalar(select(func.count()).select_from(OrganizationORM)), 0)

    async def test_parallel_first_spaces_share_organization_and_limit_is_preserved(self):
        async with self.sessions() as session:
            user = await session.get(User, 1)
            user.extra_spaces_allowance = 0
            await session.commit()
        responses = await asyncio.gather(*[
            self.client.post("/api/v1/spaces", json={"name": f"Espacio {i}", "space_type": "COLLECTOR" if i % 2 else "BUSINESS"}, headers=self.headers())
            for i in range(6)
        ])
        self.assertEqual(sorted(r.status_code for r in responses), [201] * 2 + [403] * 4)
        self.assertEqual(len({r.json()["organization_id"] for r in responses if r.status_code == 201}), 1)
        async with self.sessions() as session:
            self.assertEqual(await session.scalar(select(func.count()).select_from(OrganizationORM)), 1)
            self.assertEqual(await session.scalar(select(func.count()).select_from(SpaceORM)), 2)
            self.assertEqual(await session.scalar(select(func.count()).select_from(WineCellarORM)), 2)

    async def test_space_can_be_deleted_with_its_default_cellar(self):
        space = await self.create_space()
        response = await self.client.delete(
            f"/api/v1/organizations/{space['organization_id']}", headers=self.headers()
        )
        self.assertEqual(response.status_code, 409)
        response = await self.client.delete(f"/api/v1/spaces/{space['id']}", headers=self.headers())
        self.assertEqual(response.status_code, 204)
        async with self.sessions() as session:
            self.assertIsNone(await session.get(SpaceORM, UUID(space["id"])))
            self.assertEqual(await session.scalar(select(func.count()).select_from(WineCellarORM)), 0)
            self.assertEqual(await session.scalar(select(func.count()).select_from(OrganizationORM)), 1)

    async def test_invalid_missing_and_conflicting_space_filters(self):
        for params, expected_status in (
            ({"spaceId": "not-a-uuid"}, 422),
            ({"spaceId": str(uuid4())}, 404),
            ({"space_id": str(uuid4()), "spaceId": str(uuid4())}, 422),
        ):
            response = await self.client.get(
                "/api/v1/wine-cellars", params=params, headers=self.headers()
            )
            self.assertEqual(response.status_code, expected_status, response.text)

    async def test_creating_space_creates_exactly_one_default_cellar(self):
        space = await self.create_space()
        cellar = space["default_wine_cellar"]
        self.assertEqual(cellar["name"], "Cava Principal")
        self.assertEqual(cellar["description"], "Cava inicial creada automáticamente")
        self.assertEqual(cellar["space_id"], space["id"])
        self.assertIsNone(cellar["device_id"])
        async with self.sessions() as session:
            self.assertEqual(await session.scalar(select(func.count()).select_from(WineCellarORM)), 1)
        response = await self.client.get("/api/v1/user/context", headers=self.headers())
        self.assertEqual(response.json()["wine_cellars"], [{
            "id": cellar["id"], "name": "Cava Principal", "space_id": space["id"],
        }])

    async def test_failure_after_cellar_insert_rolls_back_entire_creation(self):
        original_save = WineCellarRepository.save

        async def failing_save(repository, cellar):
            await original_save(repository, cellar)
            raise RuntimeError("Injected failure after cellar flush")

        with patch.object(WineCellarRepository, "save", failing_save):
            with self.assertRaisesRegex(RuntimeError, "Injected failure"):
                await self.client.post(
                    "/api/v1/spaces", json={"name": "No persistir"}, headers=self.headers()
                )
        async with self.sessions() as session:
            for model in (OrganizationORM, SpaceORM, WineCellarORM):
                self.assertEqual(await session.scalar(select(func.count()).select_from(model)), 0)

        # The legacy route must roll back space/cellar without deleting an existing organization.
        response = await self.client.post(
            "/api/v1/organizations", json={"name": "Existente"}, headers=self.headers()
        )
        org_id = response.json()["id"]
        with patch.object(WineCellarRepository, "save", failing_save):
            with self.assertRaisesRegex(RuntimeError, "Injected failure"):
                await self.client.post(
                    f"/api/v1/organizations/{org_id}/spaces",
                    json={"name": "No persistir"}, headers=self.headers(),
                )
        async with self.sessions() as session:
            self.assertEqual(await session.scalar(select(func.count()).select_from(OrganizationORM)), 1)
            for model in (SpaceORM, WineCellarORM):
                self.assertEqual(await session.scalar(select(func.count()).select_from(model)), 0)

    async def test_mixed_creation_routes_share_space_limit(self):
        async with self.sessions() as session:
            user = await session.get(User, 1)
            user.extra_spaces_allowance = 0
            await session.commit()
        response = await self.client.post(
            "/api/v1/organizations", json={"name": "Personal"}, headers=self.headers()
        )
        org_id = response.json()["id"]
        responses = await asyncio.gather(*[
            self.client.post(
                "/api/v1/spaces" if i % 2 else f"/api/v1/organizations/{org_id}/spaces",
                json={"name": f"Espacio {i}", "space_type": "COLLECTOR" if i % 2 else "BUSINESS"}, headers=self.headers(),
            ) for i in range(6)
        ])
        self.assertEqual(sorted(r.status_code for r in responses), [201] * 2 + [403] * 4)
        async with self.sessions() as session:
            self.assertEqual(await session.scalar(select(func.count()).select_from(SpaceORM)), 2)
            self.assertEqual(await session.scalar(select(func.count()).select_from(WineCellarORM)), 2)

    async def test_legacy_creation_rejects_foreign_organization_without_side_effects(self):
        foreign = await self.create_space(user_id=2)
        for org_id, expected in ((foreign["organization_id"], 403), (str(uuid4()), 404)):
            response = await self.client.post(
                f"/api/v1/organizations/{org_id}/spaces",
                json={"name": "No autorizado"}, headers=self.headers(),
            )
            self.assertEqual(response.status_code, expected)
        async with self.sessions() as session:
            self.assertEqual(await session.scalar(select(func.count()).select_from(SpaceORM)), 1)
            self.assertEqual(await session.scalar(select(func.count()).select_from(WineCellarORM)), 1)

    async def test_deleting_space_removes_all_its_cellars_and_inventory_only(self):
        own = await self.create_space()
        another = await self.create_space("Conservar")
        foreign = await self.create_space(user_id=2)
        extra_cellar = await self.create_cellar(own)
        for cellar, user_id in (
            (own["default_wine_cellar"], 1), (extra_cellar, 1),
            (another["default_wine_cellar"], 1), (foreign["default_wine_cellar"], 2),
        ):
            await self.create_inventory(cellar, user_id)
        response = await self.client.delete(f"/api/v1/spaces/{own['id']}", headers=self.headers())
        self.assertEqual(response.status_code, 204, response.text)
        async with self.sessions() as session:
            for model in (SpaceORM, WineCellarORM, WineInventoryItemORM):
                self.assertEqual(await session.scalar(select(func.count()).select_from(model)), 2)
        context = await self.client.get("/api/v1/user/context", headers=self.headers())
        self.assertEqual([s["id"] for s in context.json()["spaces"]], [another["id"]])
        self.assertEqual([c["id"] for c in context.json()["wine_cellars"]], [another["default_wine_cellar"]["id"]])
        response = await self.client.delete(f"/api/v1/spaces/{own['id']}", headers=self.headers())
        self.assertEqual(response.status_code, 404)

    async def test_empty_space_can_still_be_deleted(self):
        space = await self.create_space()
        response = await self.client.delete(
            f"/api/v1/wine-cellars/{space['default_wine_cellar']['id']}", headers=self.headers()
        )
        self.assertEqual(response.status_code, 204)
        response = await self.client.delete(f"/api/v1/spaces/{space['id']}", headers=self.headers())
        self.assertEqual(response.status_code, 204)
        async with self.sessions() as session:
            self.assertEqual(await session.scalar(select(func.count()).select_from(SpaceORM)), 0)

    async def test_space_deletion_requires_owner_and_jwt(self):
        space = await self.create_space(user_id=2)
        await self.create_inventory(space["default_wine_cellar"], user_id=2)
        for headers, statuses in (({}, (401, 403)), (self.headers(), (403,))):
            response = await self.client.delete(f"/api/v1/spaces/{space['id']}", headers=headers)
            self.assertIn(response.status_code, statuses)
        async with self.sessions() as session:
            for model in (SpaceORM, WineCellarORM, WineInventoryItemORM):
                self.assertEqual(await session.scalar(select(func.count()).select_from(model)), 1)

    async def test_failed_space_deletion_restores_cellars_and_inventory(self):
        space = await self.create_space()
        await self.create_inventory(space["default_wine_cellar"])
        original_delete = SpaceRepository.delete

        async def failing_delete(repository, space_id):
            await original_delete(repository, space_id)
            raise RuntimeError("Injected failure after space delete")

        with patch.object(SpaceRepository, "delete", failing_delete):
            with self.assertRaisesRegex(RuntimeError, "Injected failure"):
                await self.client.delete(f"/api/v1/spaces/{space['id']}", headers=self.headers())
        async with self.sessions() as session:
            for model in (SpaceORM, WineCellarORM, WineInventoryItemORM):
                self.assertEqual(await session.scalar(select(func.count()).select_from(model)), 1)

    async def test_space_with_assigned_device_still_cannot_be_deleted(self):
        space = await self.create_space()
        await self.create_inventory(space["default_wine_cellar"])
        async with self.sessions() as session:
            device = DeviceORM(
                serial_number="delete-test", name="Sensor", factory_name="Factory",
                hardware_id="delete-hardware", api_key="delete-api-key", device_type="SENSOR",
            )
            session.add(device)
            await session.flush()
            session.add(DeviceAssignmentORM(
                device_id=device.id, space_id=UUID(space["id"]), owner_user_id="1",
            ))
            await session.commit()
        response = await self.client.delete(f"/api/v1/spaces/{space['id']}", headers=self.headers())
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"], "Space has devices")
        async with self.sessions() as session:
            for model in (SpaceORM, WineCellarORM, WineInventoryItemORM, DeviceAssignmentORM, DeviceORM):
                self.assertEqual(await session.scalar(select(func.count()).select_from(model)), 1)

    async def test_ai_empty_cellar_early_exit_uses_real_database_without_google(self):
        from app.inventory_intelligence.infrastructure.gemini.gemini_client import GeminiClientImpl
        from app.inventory_intelligence.applications.prompt_builder import PromptBuilder

        space = await self.create_space()
        cellar_id = space["default_wine_cellar"]["id"]
        with patch.object(GeminiClientImpl, "_create_client") as google, patch.object(PromptBuilder, "build_prompt") as prompt:
            for route in ("analyze-stock", "recommend-purchases", "monthly-report", "chat"):
                payload = {"wine_cellar_id": cellar_id}
                if route == "chat":
                    payload["user_query"] = "Analiza mi inventario"
                response = await self.client.post(
                    f"/api/v1/ai/{route}", json=payload, headers=self.headers(),
                )
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["status"], "empty")
                self.assertEqual(response.json()["tokens_used"], 0)
                self.assertTrue(response.json()["content"])
            google.assert_not_called()
            prompt.assert_not_called()

    async def test_ai_inventory_snapshot_bounds_rows_and_aggregates_large_cellars(self):
        space = await self.create_space()
        cellar_id = UUID(space["default_wine_cellar"]["id"])
        async with self.sessions() as session:
            repository = WineInventoryRepository(session)
            self.assertEqual((await repository.get_analysis_snapshot(cellar_id)).item_count, 0)
            session.add_all([
                WineInventoryItemORM(
                    wine_cellar_id=cellar_id, wine_name=f"Vino {i}", wine_type=f"Tipo {i % 15:02}",
                    age_years=i % 8, quantity=i + 1,
                ) for i in range(40)
            ])
            await session.commit()
            snapshot = await repository.get_analysis_snapshot(cellar_id)
            self.assertEqual(snapshot.item_count, 40)
            self.assertEqual(len(snapshot.inventory), 40)
            self.assertEqual(snapshot.total_quantity, sum(range(1, 41)))
            session.add_all([
                WineInventoryItemORM(
                    wine_cellar_id=cellar_id, wine_name=f"Vino {i}", wine_type=f"Tipo {i % 15:02}",
                    age_years=i % 8, quantity=i + 1,
                ) for i in range(40, 65)
            ])
            await session.commit()
            snapshot = await repository.get_analysis_snapshot(cellar_id)
            self.assertEqual(snapshot.item_count, 65)
            self.assertEqual(snapshot.inventory, [])
            self.assertEqual(len(snapshot.categories), 12)
            self.assertEqual(sum(category.items for category in snapshot.categories) + snapshot.other_items, 65)
            self.assertEqual(
                sum(category.quantity for category in snapshot.categories) + snapshot.other_quantity,
                sum(range(1, 66)),
            )
            self.assertEqual((snapshot.min_age_years, snapshot.max_age_years), (0, 7))

    async def test_ai_snapshot_does_not_include_other_cellars_or_tenants(self):
        own = await self.create_space()
        foreign = await self.create_space(user_id=2)
        await self.create_inventory(foreign["default_wine_cellar"], user_id=2)
        async with self.sessions() as session:
            snapshot = await WineInventoryRepository(session).get_analysis_snapshot(
                UUID(own["default_wine_cellar"]["id"])
            )
            self.assertEqual(snapshot.item_count, 0)
            self.assertEqual(snapshot.total_quantity, 0)


if __name__ == "__main__":
    unittest.main()
