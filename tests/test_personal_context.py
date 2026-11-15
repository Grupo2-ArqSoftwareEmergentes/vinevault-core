"""API integration checks against PostgreSQL, isolated in a temporary schema.

Set TEST_DATABASE_URL to an explicit postgresql+asyncpg:// URL before running.
The normal app lifespan (including factory/edge seeds) is deliberately not run.
"""
import asyncio
import os
import unittest
from uuid import uuid4

import httpx
from sqlalchemy import event, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base, get_db
from app.core.security import create_access_token
from app.device.infrastructure.database.models.organization_orm import OrganizationORM
from app.main import app


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "Set TEST_DATABASE_URL to run PostgreSQL checks")
class PersonalContextTests(unittest.IsolatedAsyncioTestCase):
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
        return response.json()

    async def create_cellar(self, space, user_id=1):
        response = await self.client.post(
            f"/api/v1/spaces/{space['id']}/wine-cellars",
            json={"name": "Cava"}, headers=self.headers(user_id),
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

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
        self.assertEqual(context.json()["wine_cellars"], [])
        self.assertEqual(set(context.json()["spaces"][0]), {"id", "name"})

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
        response = await self.client.get(
            f"/api/v1/organizations/{org_id}/spaces", headers=self.headers()
        )
        self.assertEqual(len(response.json()), 2)

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
        self.assertEqual(len(statements), 2, statements)
        self.assertEqual(response.status_code, 200)
        context = response.json()
        self.assertEqual(len(context["spaces"]), 2)
        self.assertEqual(len(context["wine_cellars"]), 2)
        self.assertNotIn(foreign_cellar["id"], [c["id"] for c in context["wine_cellars"]])
        for parameter in ("space_id", "spaceId"):
            response = await self.client.get(
                "/api/v1/wine-cellars", params={parameter: own["id"]}, headers=self.headers()
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual([c["id"] for c in response.json()], [own_cellar["id"]])
        all_cellars = await self.client.get("/api/v1/wine-cellars", headers=self.headers())
        self.assertEqual(len(all_cellars.json()), 2)
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
        self.assertEqual(response.json(), {"spaces": [], "wine_cellars": []})

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
        responses = await asyncio.gather(*[
            self.client.post("/api/v1/spaces", json={"name": f"Espacio {i}"}, headers=self.headers())
            for i in range(6)
        ])
        self.assertEqual(sorted(r.status_code for r in responses), [201] * 5 + [409])
        self.assertEqual(len({r.json()["organization_id"] for r in responses if r.status_code == 201}), 1)
        async with self.sessions() as session:
            self.assertEqual(await session.scalar(select(func.count()).select_from(OrganizationORM)), 1)

    async def test_foreign_keys_prevent_deleting_occupied_parents(self):
        space = await self.create_space()
        cellar = await self.create_cellar(space)
        response = await self.client.delete(f"/api/v1/spaces/{space['id']}", headers=self.headers())
        self.assertEqual(response.status_code, 409)
        response = await self.client.delete(
            f"/api/v1/organizations/{space['organization_id']}", headers=self.headers()
        )
        self.assertEqual(response.status_code, 409)
        response = await self.client.delete(
            f"/api/v1/wine-cellars/{cellar['id']}", headers=self.headers()
        )
        self.assertEqual(response.status_code, 204)
        response = await self.client.delete(f"/api/v1/spaces/{space['id']}", headers=self.headers())
        self.assertEqual(response.status_code, 204)

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


if __name__ == "__main__":
    unittest.main()
