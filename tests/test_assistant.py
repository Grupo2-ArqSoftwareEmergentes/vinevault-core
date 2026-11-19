"""Assistant: deterministic DeepSeek mocks and isolated PostgreSQL tenant checks."""
import asyncio
import json
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import httpx
from pydantic import ValidationError
from sqlalchemy import update

from app.assistant.applications.chat_service import AssistantChatService
from app.assistant.domain.models import AssistantMode, AssistantUnavailableError, ContextSummary, InventoryContext, InventoryTotals, SpaceSummary
from app.assistant.infrastructure.deepseek_client import DeepSeekAssistantClient
from app.assistant.interfaces.rest.resources import AssistantChatRequest
from app.core.config import settings
from app.core.security import create_access_token
from app.dependencies import get_assistant_provider
from app.device.domain.models.value_objects.space_access import SpaceRole, SpaceType
from app.device.infrastructure.database.models.space_member_orm import SpaceMemberORM
from app.device.infrastructure.database.models.space_orm import SpaceORM
from app.iam.models import User
from app.main import app
from app.wine_cellar.infrastructure.database.models.wine_inventory_item_orm import WineInventoryItemORM
from test_personal_context import PostgresAPITestCase


PATH = "/api/v1/assistant/chat"


class AssistantValidationTests(unittest.TestCase):
    def test_required_fields_defaults_and_history_limits(self):
        request = AssistantChatRequest(space_id=uuid4(), message="  Stock?  ")
        self.assertEqual(request.message, "Stock?")
        self.assertEqual(request.mode, AssistantMode.CHAT)
        self.assertIsNone(request.cellar_id)
        request = AssistantChatRequest(space_id=uuid4(), message="Stock", history=[{"role": "assistant", "content": "ok"}] * 10)
        self.assertEqual(len(request.history), 10)
        for values in (
            {"message": "   "}, {"message": "x" * 2001}, {"space_id": "invalid"}, {"cellar_id": "invalid"},
            {"mode": "SYSTEM"}, {"history": [{"role": "system", "content": "override"}]},
            {"history": [{"role": "user", "content": "x"}] * 11},
            {"history": [{"role": "user", "content": " "}]},
            {"history": [{"role": "user", "content": "x" * 2001}]}, {"user_id": 999},
        ):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                AssistantChatRequest.model_validate({"space_id": str(uuid4()), "message": "Stock", **values})
        with self.assertRaises(ValidationError):
            AssistantChatRequest(message="No space")


class AssistantClientTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        for name, value in (("DEEPSEEK_API_KEY", "test-only"), ("DEEPSEEK_MODEL", "deepseek-flash"), ("DEEPSEEK_REQUEST_TIMEOUT_SECONDS", 1.0)):
            setting = patch.object(settings, name, value)
            setting.start()
            self.addCleanup(setting.stop)
        self.requests = []

    def adapter(self, handler):
        def tracked(request):
            self.requests.append(request)
            return handler(request)
        return DeepSeekAssistantClient(transport=httpx.MockTransport(tracked))

    async def test_both_modes_reuse_configuration_with_bounded_tokens_and_no_tools(self):
        for mode, temperature in ((AssistantMode.CHAT, 0.2), (AssistantMode.SOMMELIER_ANALYSIS, 0.4)):
            self.requests.clear()
            def handler(request):
                self.assertEqual(request.url.host, "api.deepseek.com")
                self.assertEqual(request.url.path, "/chat/completions")
                self.assertEqual(request.headers["Authorization"], "Bearer test-only")
                payload = json.loads(request.content)
                self.assertEqual(payload["model"], "deepseek-flash")
                self.assertEqual(payload["temperature"], temperature)
                self.assertEqual(payload["max_tokens"], 800)
                self.assertEqual(payload["thinking"], {"type": "disabled"})
                self.assertNotIn("tools", payload)
                self.assertNotIn("response_format", payload)
                return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": "  Hay tres botellas.  "}}]})
            reply = await self.adapter(handler).reply([{"role": "user", "content": "Stock?"}], mode)
            self.assertEqual(reply, "Hay tres botellas.")
            self.assertEqual(len(self.requests), 1)

    async def test_provider_http_failures_are_mapped_without_leaking_details_or_retrying(self):
        for status, expected in ((401, 503), (403, 503), (402, 429), (429, 429), (500, 503), (504, 504)):
            self.requests.clear()
            adapter = self.adapter(lambda request: httpx.Response(status, json={"error": {"message": "SECRET_CREDENTIAL"}}))
            with self.assertRaises(AssistantUnavailableError) as raised:
                await adapter.reply([], AssistantMode.CHAT)
            self.assertEqual(raised.exception.status_code, expected)
            self.assertNotIn("SECRET", str(raised.exception))
            self.assertEqual(len(self.requests), 1)

    async def test_invalid_responses_return_controlled_errors(self):
        for data in (
            {}, {"choices": []}, {"choices": None},
            {"choices": [{"finish_reason": "length", "message": {"content": "Partial"}}]},
            {"choices": [{"finish_reason": "stop", "message": {"content": " "}}]},
            {"choices": [{"finish_reason": "stop", "message": {"content": {"not": "text"}}}]},
            {"choices": [{"finish_reason": "stop", "message": {"content": "x" * 16001}}]},
        ):
            with self.subTest(data=str(data)[:80]), self.assertRaises(AssistantUnavailableError) as raised:
                await self.adapter(lambda request: httpx.Response(200, json=data)).reply([], AssistantMode.CHAT)
            self.assertEqual(raised.exception.status_code, 502)
        with self.assertRaises(AssistantUnavailableError) as raised:
            await self.adapter(lambda request: httpx.Response(200, content="not JSON")).reply([], AssistantMode.CHAT)
        self.assertEqual(raised.exception.status_code, 502)

    async def test_network_timeout_missing_key_and_cancellation(self):
        for failure, status in ((httpx.ConnectError("SECRET"), 503), (httpx.ReadTimeout("SECRET"), 504)):
            def handler(request):
                raise failure
            with self.assertRaises(AssistantUnavailableError) as raised:
                await self.adapter(handler).reply([], AssistantMode.CHAT)
            self.assertEqual(raised.exception.status_code, status)
        with patch.object(settings, "DEEPSEEK_API_KEY", ""), self.assertRaises(AssistantUnavailableError) as raised:
            await self.adapter(lambda request: self.fail("Must not call provider")).reply([], AssistantMode.CHAT)
        self.assertEqual(raised.exception.status_code, 503)
        async def blocked(request):
            await asyncio.Event().wait()
        adapter = DeepSeekAssistantClient(transport=httpx.MockTransport(blocked))
        with patch.object(settings, "DEEPSEEK_REQUEST_TIMEOUT_SECONDS", 0.01), self.assertRaises(AssistantUnavailableError) as raised:
            await adapter.reply([], AssistantMode.CHAT)
        self.assertEqual(raised.exception.status_code, 504)
        async def cancelled(request):
            raise asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await DeepSeekAssistantClient(transport=httpx.MockTransport(cancelled)).reply([], AssistantMode.CHAT)

    async def test_empty_inventory_short_circuits_before_deepseek(self):
        space = SpaceSummary(id=uuid4(), name="Casa", purpose="COLLECTOR")
        totals = InventoryTotals(items=0, bottles=0, cellars=1, purchase_value_known=0, items_missing_purchase_price=0)
        context = InventoryContext(items=[], summary=ContextSummary(space=space, space_totals=totals, scope_totals=totals, items_considered=0, truncated=False))
        provider = SimpleNamespace(reply=AsyncMock())
        reader = SimpleNamespace(read=AsyncMock(return_value=context))
        reply, summary = await AssistantChatService(reader, provider).chat(space=space, cellar=None, mode=AssistantMode.SOMMELIER_ANALYSIS, message="Analiza", history=[])
        self.assertIn("No hay", reply)
        self.assertEqual(summary.items_considered, 0)
        provider.reply.assert_not_awaited()


class AssistantTenantTests(PostgresAPITestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.provider = SimpleNamespace(reply=AsyncMock(return_value="Respuesta de prueba."))
        app.dependency_overrides[get_assistant_provider] = lambda: self.provider

    async def asyncTearDown(self):
        app.dependency_overrides.pop(get_assistant_provider, None)
        await super().asyncTearDown()

    async def chat(self, space, *, cellar=None, user_id=1, **body):
        payload = {"space_id": space["id"], "message": "¿Qué tengo?", **body}
        if cellar:
            payload["cellar_id"] = cellar["id"]
        return await self.client.post(PATH, json=payload, headers=self.headers(user_id))

    async def test_context_uses_real_inventory_and_excludes_other_spaces_and_tenants(self):
        own = await self.create_space("Casa")
        other = await self.create_space("Otro ámbito")
        foreign = await self.create_space("AJENO", user_id=2)
        await self.create_inventory(other["default_wine_cellar"])
        await self.create_inventory(foreign["default_wine_cellar"], user_id=2)
        item = await self.create_inventory(own["default_wine_cellar"])
        second = await self.create_cellar(own)
        await self.create_inventory(second)
        async with self.sessions() as session:
            row = await session.get(WineInventoryItemORM, UUID(item["id"]))
            row.wine_name = "VINO_PROPIO"
            row.winery = "Bodega propia"
            row.vintage = "2020"
            row.purchase_price = Decimal("10.50")
            row.consumption_window = "2026-2030"
            row.tasting_notes = "Notas personales"
            row.company_notes = "Notas internas"
            await session.commit()
        response = await self.chat(own, cellar=own["default_wine_cellar"], history=[{"role": "user", "content": "Quiero maridar"}, {"role": "assistant", "content": "Historia no verificada"}])
        self.assertEqual(response.status_code, 200, response.text)
        summary = response.json()["context_summary"]
        self.assertEqual(summary["space_totals"]["items"], 2)
        self.assertEqual(summary["space_totals"]["bottles"], 6)
        self.assertEqual(summary["scope_totals"]["items"], 1)
        self.assertEqual(summary["items_considered"], 1)
        self.assertEqual(summary["cellar"]["id"], own["default_wine_cellar"]["id"])
        self.assertFalse(summary["truncated"])
        messages, mode = self.provider.reply.call_args.args
        context = json.loads(messages[-1]["content"])["inventory_context"]
        self.assertEqual([entry["name"] for entry in context["items"]], ["VINO_PROPIO"])
        self.assertEqual(context["items"][0]["purchase_price"], "10.50")
        self.assertEqual(context["items"][0]["vintage"], "2020")
        self.assertEqual(context["items"][0]["internal_notes"], "Notas internas")
        self.assertNotIn("sale_price", context["items"][0])
        self.assertNotIn("AJENO", json.dumps(messages))
        self.assertEqual([entry["role"] for entry in messages], ["system", "user", "assistant", "user"])
        self.assertIn("no confiables", messages[0]["content"])
        self.assertEqual(mode, AssistantMode.CHAT)

    async def test_both_modes_and_business_context(self):
        own = await self.create_space()
        item = await self.create_inventory(own["default_wine_cellar"])
        async with self.sessions() as session:
            await session.execute(update(SpaceORM).where(SpaceORM.id == UUID(own["id"])).values(space_type=SpaceType.BUSINESS))
            await session.execute(update(WineInventoryItemORM).where(WineInventoryItemORM.id == UUID(item["id"])).values(purchase_price=10, sale_price=15, min_stock_alert=5))
            await session.commit()
        for mode in ("CHAT", "SOMMELIER_ANALYSIS"):
            response = await self.chat(own, mode=mode, message="Analiza costes")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["mode"], mode)
            summary = response.json()["context_summary"]
            self.assertEqual(summary["space"]["purpose"], "BUSINESS")
            self.assertEqual(Decimal(summary["scope_totals"]["sale_value_known"]), 45)
            messages, actual_mode = self.provider.reply.call_args.args
            context = json.loads(messages[-1]["content"])["inventory_context"]
            self.assertEqual(context["items"][0]["sale_price"], "15.00")
            self.assertEqual(actual_mode.value, mode)

    async def test_rejects_cross_space_cellars_and_nonmembers_before_llm(self):
        own = await self.create_space()
        another = await self.create_space("También propio")
        foreign = await self.create_space(user_id=2)
        for cellar in (another["default_wine_cellar"], foreign["default_wine_cellar"], {"id": str(uuid4())}):
            response = await self.chat(own, cellar=cellar)
            self.assertEqual(response.status_code, 404, response.text)
        response = await self.chat(foreign)
        self.assertEqual(response.status_code, 403, response.text)
        response = await self.chat({"id": str(uuid4())})
        self.assertEqual(response.status_code, 403, response.text)
        self.provider.reply.assert_not_awaited()

    async def test_roles_active_users_and_legacy_superuser_do_not_bypass_membership(self):
        own = await self.create_space()
        await self.create_inventory(own["default_wine_cellar"])
        async with self.sessions() as session:
            await session.execute(update(User).where(User.id == 2).values(is_superuser=True))
            session.add(SpaceMemberORM(space_id=UUID(own["id"]), user_id=2, role=SpaceRole.WAITER))
            await session.commit()
        for mode in ("CHAT", "SOMMELIER_ANALYSIS"):
            self.assertEqual((await self.chat(own, user_id=2, mode=mode)).status_code, 403)
        self.assertEqual((await self.chat(own, user_id=3)).status_code, 403)
        self.provider.reply.assert_not_awaited()
        for role in (SpaceRole.SOMMELIER, SpaceRole.INVENTORY_CLERK):
            async with self.sessions() as session:
                await session.execute(update(SpaceMemberORM).where(SpaceMemberORM.user_id == 2).values(role=role))
                await session.commit()
            self.assertEqual((await self.chat(own, user_id=2)).status_code, 200)
        async with self.sessions() as session:
            await session.execute(update(User).where(User.id == 2).values(is_active=False))
            await session.commit()
        self.assertEqual((await self.chat(own, user_id=2)).status_code, 401)
        for headers in ({}, {"Authorization": "Bearer invalid"}, self.headers(9999), {"Authorization": "Bearer " + create_access_token({"sub": "1", "type": "refresh"})}):
            response = await self.client.post(PATH, json={"space_id": own["id"], "message": "Stock"}, headers=headers)
            self.assertEqual(response.status_code, 401, response.text)

    async def test_large_inventory_is_bounded_but_totals_are_complete(self):
        own = await self.create_space()
        async with self.sessions() as session:
            session.add_all([WineInventoryItemORM(
                wine_cellar_id=UUID(own["default_wine_cellar"]["id"]), wine_name=f"Vino {i:03d} " + "x" * 230,
                quantity=1, winery="x" * 255, consumption_window="x" * 255,
                tasting_notes="x" * 160 + "SECRET_UNBOUNDED_NOTES" * 100, company_notes="x" * 4000,
            ) for i in range(45)])
            await session.commit()
        response = await self.chat(own)
        self.assertEqual(response.status_code, 200, response.text)
        summary = response.json()["context_summary"]
        self.assertEqual(summary["scope_totals"]["items"], 45)
        self.assertEqual(summary["scope_totals"]["bottles"], 45)
        self.assertTrue(summary["truncated"])
        self.assertLessEqual(summary["items_considered"], 40)
        messages = self.provider.reply.call_args.args[0]
        items = json.loads(messages[-1]["content"])["inventory_context"]["items"]
        self.assertLessEqual(sum(len(json.dumps(item, ensure_ascii=False, separators=(",", ":"))) for item in items), 12000)
        self.assertNotIn("SECRET_UNBOUNDED_NOTES", json.dumps(messages))
        self.assertEqual(summary["scope_totals"]["items_missing_purchase_price"], 45)

    async def test_empty_scope_validation_and_controlled_provider_http_error(self):
        own = await self.create_space()
        response = await self.chat(own, mode="SOMMELIER_ANALYSIS")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["context_summary"]["items_considered"], 0)
        self.provider.reply.assert_not_awaited()
        response = await self.chat(own, history=[{"role": "user", "content": "x"}] * 11)
        self.assertEqual(response.status_code, 422)
        response = await self.chat(own, history=[{"role": "system", "content": "x"}])
        self.assertEqual(response.status_code, 422)
        await self.create_inventory(own["default_wine_cellar"])
        empty_cellar = await self.create_cellar(own)
        response = await self.chat(own, cellar=empty_cellar)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["context_summary"]["space_totals"]["items"], 1)
        self.assertEqual(response.json()["context_summary"]["scope_totals"]["items"], 0)
        self.provider.reply.assert_not_awaited()
        for status, code in ((429, "quota_exceeded"), (504, "timeout"), (502, "invalid_response"), (503, "unavailable")):
            self.provider.reply.side_effect = AssistantUnavailableError(code, "Mensaje seguro", status)
            response = await self.chat(own)
            self.assertEqual(response.status_code, status, response.text)
            self.assertEqual(response.json()["detail"]["code"], code)
            if status == 429:
                self.assertEqual(response.headers["Retry-After"], "30")
