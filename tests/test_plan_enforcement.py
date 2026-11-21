"""Free/Pro feature enforcement with real tenant SQL and fully mocked LLMs."""
from datetime import datetime, timedelta, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID

from sqlalchemy import select, update

from app.dependencies import get_assistant_provider, get_gemini_client, get_wine_autocomplete_service
from app.inventory_intelligence.domain.models.wine_autocomplete import WineAutocompleteResult
from app.inventory_intelligence.domain.services.gemini_service import GeminiChunk, GeminiService
from app.main import app
from app.subscriptions.infrastructure.database.models import ActiveSubscriptionORM
from app.device.infrastructure.database.models.space_orm import SpaceORM
from app.wine_cellar.applications.inventory_excel_service import WineInventoryExcelService
from app.wine_cellar.infrastructure.database.models.wine_inventory_item_orm import WineInventoryItemORM
from test_personal_context import PostgresAPITestCase


class StubGemini(GeminiService):
    calls = 0

    async def stream_analysis(self, prompt):
        self.calls += 1
        yield GeminiChunk(text="Análisis simulado.", tokens_used=10)


class PlanEnforcementTests(PostgresAPITestCase):
    extra_spaces_allowance = 0
    extra_cellars_allowance = 0

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.assistant = SimpleNamespace(reply=AsyncMock(return_value="Respuesta simulada."))
        self.autocomplete = SimpleNamespace(suggest=AsyncMock(return_value=WineAutocompleteResult(winery="Bodega")))
        self.gemini = StubGemini()
        app.dependency_overrides.update({
            get_assistant_provider: lambda: self.assistant,
            get_gemini_client: lambda: self.gemini,
            get_wine_autocomplete_service: lambda: self.autocomplete,
        })

    async def asyncTearDown(self):
        for dependency in (get_assistant_provider, get_gemini_client, get_wine_autocomplete_service):
            app.dependency_overrides.pop(dependency, None)
        await super().asyncTearDown()

    async def space(self, purpose="COLLECTOR", user_id=1):
        response = await self.client.post("/api/v1/spaces", headers=self.headers(user_id), json={"name": purpose, "space_type": purpose})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    async def activate(self, space):
        from uuid import uuid4
        response = await self.client.post("/api/v1/subscriptions/plan-change-requests", headers=self.headers(), json={
            "space_id": space["id"], "idempotency_key": str(uuid4()), "confirm_simulated_payment": True,
        })
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["subscription"]["id"]

    async def paid_endpoints(self, space):
        headers = self.headers()
        responses = []
        for mode in ("CHAT", "SOMMELIER_ANALYSIS"):
            responses.append(await self.client.post("/api/v1/assistant/chat", headers=headers, json={
                "space_id": space["id"], "mode": mode, "message": "¿Qué tengo?",
            }))
        responses.append(await self.client.post("/api/v1/ai/analyze-stock", headers=headers, json={
            "wine_cellar_id": space["default_wine_cellar"]["id"],
        }))
        responses.append(await self.client.post("/api/v1/inventory/ai-autocomplete", params={"space_id": space["id"]},
                                                 headers=headers, json={"wine_name": "Reserva"}))
        responses.append(await self.client.get("/api/v1/inventory/export", params={"space_id": space["id"], "format": "pdf"}, headers=headers))
        return responses

    def assert_pro_required(self, response):
        self.assertEqual(response.status_code, 403, response.text[:300])
        self.assertEqual(response.json()["detail"]["code"], "PLAN_FEATURE_UNAVAILABLE")
        self.assertIn("PRO", response.json()["detail"]["message"])

    async def test_both_free_plans_deny_paid_features_then_immediately_allow_after_activation(self):
        for purpose in ("COLLECTOR", "BUSINESS"):
            space = await self.space(purpose)
            await self.create_inventory(space["default_wine_cellar"])
            self.assistant.reply.reset_mock()
            self.autocomplete.suggest.reset_mock()
            calls_before = self.gemini.calls
            for response in await self.paid_endpoints(space):
                self.assert_pro_required(response)
            self.assistant.reply.assert_not_awaited()
            self.autocomplete.suggest.assert_not_awaited()
            self.assertEqual(self.gemini.calls, calls_before)
            for suffix in ("export", "template"):
                response = await self.client.get(f"/api/v1/wine-cellars/{space['default_wine_cellar']['id']}/inventory/{suffix}", headers=self.headers())
                self.assertEqual(response.status_code, 200, response.text[:100])
            response = await self.client.get("/api/v1/inventory/export", params={"space_id": space["id"], "format": "xlsx"}, headers=self.headers())
            self.assertEqual(response.status_code, 200)
            await self.activate(space)
            for response in await self.paid_endpoints(space):
                self.assertEqual(response.status_code, 200, response.text[:300])
            self.assistant.reply.assert_awaited()
            self.autocomplete.suggest.assert_awaited_once()
            self.assertGreater(self.gemini.calls, calls_before)

    async def test_cancelled_cycle_remains_pro_until_expiry_then_all_entrypoints_revert(self):
        space = await self.space()
        subscription_id = await self.activate(space)
        response = await self.client.post(f"/api/v1/subscriptions/{subscription_id}/cancel", headers=self.headers())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["cancel_at_period_end"])
        for response in await self.paid_endpoints(space):
            self.assertEqual(response.status_code, 200, response.text[:300])
        async with self.sessions() as session:
            row = await session.get(ActiveSubscriptionORM, UUID(subscription_id))
            now = datetime.now(timezone.utc)
            row.started_at = now - timedelta(days=31)
            row.current_period_end = now - timedelta(seconds=1)
            await session.commit()
        # Do not call overview first: stale materialized PRO must not grant any benefits.
        for response in await self.paid_endpoints(space):
            self.assert_pro_required(response)
        context = (await self.client.get("/api/v1/user/context", headers=self.headers())).json()
        self.assertEqual(context["spaces"][0]["subscription_plan"], "FREE")
        self.assertEqual(context["spaces"][0]["quotas"]["cellars"]["limit"], 1)
        self.assertEqual(context["spaces"][0]["quotas"]["bottles"]["limit"], 50)
        self.assertEqual((await self.client.get(f"/api/v1/spaces/{space['id']}", headers=self.headers())).json()["subscription_plan"], "FREE")
        self.assertEqual((await self.client.get("/api/v1/spaces", headers=self.headers())).json()[0]["subscription_plan"], "FREE")

    async def test_raw_pro_and_future_period_are_not_valid_entitlements(self):
        space = await self.space()
        async with self.sessions() as session:
            await session.execute(update(SpaceORM).where(SpaceORM.id == UUID(space["id"])).values(subscription_plan="PRO"))
            await session.commit()
        for response in await self.paid_endpoints(space):
            self.assert_pro_required(response)
        response = await self.client.post("/api/v1/wine-cellars", headers=self.headers(), json={"space_id": space["id"], "name": "No raw PRO"})
        self.assertEqual(response.status_code, 403)
        subscription_id = await self.grant_pro(space)
        async with self.sessions() as session:
            row = await session.get(ActiveSubscriptionORM, subscription_id)
            now = datetime.now(timezone.utc)
            row.started_at = now + timedelta(days=1)
            row.current_period_end = now + timedelta(days=31)
            await session.commit()
        for response in await self.paid_endpoints(space):
            self.assert_pro_required(response)

    async def test_cellar_and_inventory_limits_cover_aliases_updates_and_expired_import(self):
        collector = await self.space()
        cellar_id = collector["default_wine_cellar"]["id"]
        for url, body in ((f"/api/v1/spaces/{collector['id']}/wine-cellars", {"name": "Second"}),
                          ("/api/v1/wine-cellars", {"space_id": collector["id"], "name": "Second"})):
            response = await self.client.post(url, headers=self.headers(), json=body)
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json()["detail"]["code"], "CELLAR_LIMIT_REACHED")
        response = await self.client.post("/api/v1/wine-items", headers=self.headers(), json={"wine_cellar_id": cellar_id, "name": "Collector", "quantity": 50})
        self.assertEqual(response.status_code, 201, response.text)
        item = response.json()
        item_url = f"/api/v1/wine-cellars/{cellar_id}/inventory/{item['id']}"
        response = await self.client.patch(item_url, headers=self.headers(), json={"quantity": 51})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"]["code"], "ITEM_LIMIT_REACHED")
        subscription_id = await self.activate(collector)
        self.assertEqual((await self.client.patch(item_url, headers=self.headers(), json={"quantity": 51})).status_code, 200)
        for name in ("Second", "Third"):
            response = await self.client.post("/api/v1/wine-cellars", headers=self.headers(), json={"space_id": collector["id"], "name": name})
            self.assertEqual(response.status_code, 201, response.text)
        response = await self.client.post("/api/v1/wine-cellars", headers=self.headers(), json={"space_id": collector["id"], "name": "Fourth"})
        self.assertEqual(response.status_code, 403)
        async with self.sessions() as session:
            row = await session.get(ActiveSubscriptionORM, UUID(subscription_id))
            now = datetime.now(timezone.utc)
            row.started_at, row.current_period_end = now - timedelta(days=31), now - timedelta(seconds=1)
            await session.commit()
        self.assertEqual((await self.client.patch(item_url, headers=self.headers(), json={"winery": "Metadata is still editable"})).status_code, 200)
        self.assertEqual((await self.client.patch(item_url, headers=self.headers(), json={"quantity": 52})).status_code, 403)
        self.assertEqual((await self.client.patch(item_url, headers=self.headers(), json={"quantity": 50})).status_code, 200)
        workbook = WineInventoryExcelService()._build_xlsx([
            ["id", "wine_name", "wine_type", "age_years", "quantity"], [item["id"], "Collector", "", "", 51],
        ], sheet_name="inventory")
        with patch("app.wine_cellar.interfaces.rest.controllers.wine_cellar_controller.AsyncSessionLocal", self.sessions):
            response = await self.client.post(f"/api/v1/wine-cellars/{cellar_id}/inventory/import", headers=self.headers(), files={"file": ("stock.xlsx", workbook)})
        self.assertEqual(response.status_code, 403, response.text)
        async with self.sessions() as session:
            self.assertEqual((await session.get(WineInventoryItemORM, UUID(item["id"]))).quantity, 50)
        business = await self.space("BUSINESS")
        async with self.sessions() as session:
            session.add_all([WineInventoryItemORM(wine_cellar_id=UUID(business["default_wine_cellar"]["id"]), wine_name=f"SKU {i}", quantity=0) for i in range(25)])
            await session.commit()
        url = f"/api/v1/wine-cellars/{business['default_wine_cellar']['id']}/inventory"
        self.assertEqual((await self.client.post(url, headers=self.headers(), json={"name": "SKU 26", "quantity": 0})).status_code, 403)
        await self.activate(business)
        self.assertEqual((await self.client.post(url, headers=self.headers(), json={"name": "SKU 26", "quantity": 999})).status_code, 201)

    async def test_legacy_excel_technical_limit_has_no_alternate_route_bypass(self):
        space = await self.space()
        await self.create_inventory(space["default_wine_cellar"])
        with patch("app.wine_cellar.applications.inventory_export_service.MAX_EXPORT_ITEMS", 0):
            urls = [f"/api/v1/wine-cellars/{space['default_wine_cellar']['id']}/inventory/export",
                    f"/api/v1/inventory/export?space_id={space['id']}&format=xlsx"]
            for url in urls:
                response = await self.client.get(url, headers=self.headers())
                self.assertEqual(response.status_code, 413, response.text)
