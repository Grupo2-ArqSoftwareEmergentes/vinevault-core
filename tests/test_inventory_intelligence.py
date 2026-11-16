"""Deterministic AI checks: no credentials, Google calls or PostgreSQL needed."""
import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import httpx

from app.core.config import settings
from app.core.security import create_access_token
from app.dependencies import get_gemini_client, get_inventory_data_facade, get_space_repository, get_wine_cellar_repository
from app.inventory_intelligence.applications.acl import InventoryDataFacadeImpl
from app.inventory_intelligence.applications.analysis_application_service import AnalysisApplicationService, EMPTY_MESSAGE
from app.inventory_intelligence.applications.prompt_builder import PromptBuilder
from app.inventory_intelligence.domain.models import AnalysisRequest, AnalysisResult
from app.inventory_intelligence.domain.models.analysis_type import AnalysisType
from app.inventory_intelligence.domain.services.gemini_service import AnalysisUnavailableError, GeminiChunk, GeminiService
from app.inventory_intelligence.infrastructure.gemini.gemini_client import GeminiClientImpl
from app.inventory_intelligence.interfaces.acl import WineCellarIntelligenceData
from app.inventory_intelligence.interfaces.rest.controllers.intelligence_controller import _analysis_events
from app.main import app
from app.wine_cellar.domain.models.inventory_snapshot import InventorySnapshot, InventoryItemSummary, InventoryCategorySummary


class StubGemini(GeminiService):
    def __init__(self):
        self.calls = 0
        self.failure = None
        self.closed = False

    async def stream_analysis(self, prompt):
        self.calls += 1
        try:
            if self.failure:
                raise self.failure
            yield GeminiChunk(text="Primero ")
            yield GeminiChunk(text="segundo", tokens_used=42)
        finally:
            self.closed = True


class InventoryAnalysisTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cellar_id = uuid4()
        self.space_id = uuid4()
        self.data = WineCellarIntelligenceData(
            id=self.cellar_id, name="Cava", space_name="Casa", item_count=1,
            total_quantity=3, min_age_years=2, max_age_years=2,
            inventory=[InventoryItemSummary(wine_name="Reserva", wine_type="Tinto", age_years=2, quantity=3)],
        )
        self.facade = SimpleNamespace(get_cellar_data_for_intelligence=AsyncMock(return_value=self.data))
        self.gemini = StubGemini()
        self.service = AnalysisApplicationService(self.gemini, self.facade)
        self.request = AnalysisRequest(
            wine_cellar_id=self.cellar_id, user_id=1, analysis_type=AnalysisType.STOCK_ANALYSIS,
        )

    async def test_empty_inventory_never_builds_prompt_or_initializes_google(self):
        self.data.item_count = 0
        service = AnalysisApplicationService(get_gemini_client(), self.facade)
        with patch.object(PromptBuilder, "build_prompt") as prompt, patch.object(GeminiClientImpl, "_create_client") as client:
            result = await service.execute_analysis(self.request)
        self.assertEqual(result.status, "empty")
        self.assertEqual(result.content, EMPTY_MESSAGE)
        self.assertEqual(result.tokens_used, 0)
        prompt.assert_not_called()
        client.assert_not_called()

    async def test_json_compatibility_collects_the_same_async_stream(self):
        result = await self.service.execute_analysis(self.request)
        self.assertEqual(result.content, "Primero segundo")
        self.assertEqual(result.tokens_used, 42)
        self.assertEqual(self.gemini.calls, 1)
        self.assertTrue(self.gemini.closed)

    async def test_sse_yields_first_delta_before_generating_the_rest(self):
        events = _analysis_events(self.service, "prompt", self.request)
        first = await anext(events)
        self.assertIn("event: delta", first)
        self.assertIn("Primero ", first)
        self.assertFalse(self.gemini.closed)
        remaining = [event async for event in events]
        self.assertIn("event: done", remaining[-1])
        payload = json.loads(remaining[-1].split("data: ", 1)[1])
        self.assertEqual(payload["result"]["content"], "Primero segundo")
        self.assertTrue(self.gemini.closed)

    async def test_disconnect_closes_provider_generator(self):
        events = _analysis_events(self.service, "prompt", self.request)
        await anext(events)
        await events.aclose()
        self.assertTrue(self.gemini.closed)

    async def test_stream_errors_are_terminal_and_friendly(self):
        self.gemini.failure = AnalysisUnavailableError("rate_limit", "Cuota agotada", 429)
        events = [event async for event in _analysis_events(self.service, "prompt", self.request)]
        self.assertEqual(len(events), 1)
        self.assertIn("event: error", events[0])
        self.assertIn("rate_limit", events[0])
        self.assertNotIn("event: done", events[0])

    async def test_large_prompt_uses_bounded_summary_without_metadata(self):
        self.data.description = "SECRET_DESCRIPTION" * 10000
        self.data.item_count = 100000
        self.data.inventory = []
        self.data.categories = [InventoryCategorySummary(wine_type="Tinto", items=100000, quantity=500000)]
        self.data.total_quantity = 500000
        prompt = PromptBuilder.build_prompt(AnalysisType.STOCK_ANALYSIS, self.data)
        self.assertNotIn("SECRET_DESCRIPTION", prompt)
        self.assertIn('"bottles":500000', prompt)
        self.assertIn('"categories"', prompt)
        self.assertNotIn('"wines"', prompt)
        self.assertLess(len(prompt), 2000)

    async def test_acl_skips_sensor_queries_for_empty_and_stock(self):
        cellar_repo = SimpleNamespace(find_by_id=AsyncMock(return_value=SimpleNamespace(
            id=self.cellar_id, name="Cava", device_id=uuid4(),
        )))
        inventory_repo = SimpleNamespace(get_analysis_snapshot=AsyncMock(return_value=InventorySnapshot()))
        devices = SimpleNamespace(get_assignment=AsyncMock())
        facade = InventoryDataFacadeImpl(cellar_repo, inventory_repo, devices)
        await facade.get_cellar_data_for_intelligence(self.cellar_id, include_device=True)
        inventory_repo.get_analysis_snapshot.return_value = InventorySnapshot(item_count=1)
        await facade.get_cellar_data_for_intelligence(self.cellar_id)
        devices.get_assignment.assert_not_called()

    async def test_http_json_sse_empty_and_ownership_contracts(self):
        cellar_repo = SimpleNamespace(find_by_id=AsyncMock(return_value=SimpleNamespace(space_id=self.space_id)))
        space_repo = SimpleNamespace(find_by_id=AsyncMock(return_value=SimpleNamespace(
            owner_user_id=SimpleNamespace(user_id=1),
        )))
        overrides = {
            get_inventory_data_facade: lambda: self.facade,
            get_gemini_client: lambda: self.gemini,
            get_wine_cellar_repository: lambda: cellar_repo,
            get_space_repository: lambda: space_repo,
        }
        previous = app.dependency_overrides.copy()
        app.dependency_overrides.update(overrides)
        headers = {"Authorization": f"Bearer {create_access_token({'sub': '1'})}"}
        path = "/api/v1/ai/analyze-stock"
        body = {"wine_cellar_id": str(self.cellar_id)}
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(path, json=body, headers=headers)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["content"], "Primero segundo")
                for query, accept in (("?stream=true", "application/json"), ("", "text/event-stream")):
                    response = await client.post(path + query, json=body, headers={**headers, "Accept": accept})
                    self.assertIn("text/event-stream", response.headers["content-type"])
                    self.assertIn("event: delta", response.text)
                    self.assertIn("event: done", response.text)
                self.gemini.failure = AnalysisUnavailableError("rate_limit", "Cuota agotada", 429)
                response = await client.post(path, json=body, headers=headers)
                self.assertEqual(response.status_code, 429)
                self.assertEqual(response.headers["retry-after"], "30")
                response = await client.post(path + "?stream=true", json=body, headers=headers)
                self.assertEqual(response.status_code, 200)
                self.assertIn("event: error", response.text)
                self.assertNotIn("event: done", response.text)
                self.gemini.failure = None
                self.data.item_count = 0
                calls = self.gemini.calls
                response = await client.post(path + "?stream=true", json=body, headers=headers)
                self.assertEqual(response.json()["status"], "empty")
                self.assertEqual(response.json()["message"], EMPTY_MESSAGE)
                self.assertEqual(self.gemini.calls, calls)
                space_repo.find_by_id.return_value.owner_user_id.user_id = 2
                self.facade.get_cellar_data_for_intelligence.reset_mock()
                response = await client.post(path, json=body, headers=headers)
                self.assertEqual(response.status_code, 403)
                self.facade.get_cellar_data_for_intelligence.assert_not_called()
                response = await client.post(path, json=body)
                self.assertIn(response.status_code, (401, 403))
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(previous)

    async def test_http_rate_limit_does_not_expose_upstream_details(self):
        self.gemini.failure = AnalysisUnavailableError("rate_limit", "Cuota agotada", 429)
        from app.inventory_intelligence.interfaces.rest.controllers.intelligence_controller import _json_analysis
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as caught:
            await _json_analysis(self.service, self.request)
        self.assertEqual(caught.exception.status_code, 429)
        self.assertEqual(caught.exception.headers["Retry-After"], "30")


class FakeAPIError(Exception):
    def __init__(self, code):
        super().__init__("SECRET_UPSTREAM_DETAILS")
        self.code = code


def sdk_response(text="hola", tokens=5):
    return SimpleNamespace(
        candidates=[SimpleNamespace(content=SimpleNamespace(parts=[SimpleNamespace(text=text, thought=False)]))],
        usage_metadata=SimpleNamespace(total_token_count=tokens),
    )


async def sdk_chunks(*chunks):
    for chunk in chunks:
        if isinstance(chunk, Exception):
            raise chunk
        yield chunk


def sdk_client(stream=None, failure=None):
    models = SimpleNamespace(generate_content_stream=AsyncMock(return_value=stream, side_effect=failure))
    return SimpleNamespace(aio=SimpleNamespace(models=models, aclose=AsyncMock()), close=Mock())


class GeminiAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_stream_closes_sdk_and_does_not_retry(self):
        adapter = GeminiClientImpl()
        fake = sdk_client(sdk_chunks(sdk_response(), sdk_response("rest")))
        with patch.object(adapter, "_create_client", return_value=fake) as create:
            stream = adapter.stream_analysis("prompt")
            self.assertEqual((await anext(stream)).text, "hola")
            await stream.aclose()
        create.assert_called_once()
        fake.aio.aclose.assert_awaited_once()
        fake.close.assert_called_once()

    async def test_empty_or_blocked_model_response_is_a_safe_failure(self):
        fake = sdk_client(sdk_chunks(sdk_response(text="")))
        adapter = GeminiClientImpl()
        with patch.object(adapter, "_create_client", return_value=fake):
            with self.assertRaises(AnalysisUnavailableError) as caught:
                await adapter.generate_analysis("prompt")
        self.assertEqual(caught.exception.code, "empty_response")

    async def test_thought_parts_are_not_forwarded_to_frontend(self):
        response = sdk_response()
        response.candidates[0].content.parts.insert(0, SimpleNamespace(text="PRIVATE_THOUGHT", thought=True))
        adapter = GeminiClientImpl()
        with patch.object(adapter, "_create_client", return_value=sdk_client(sdk_chunks(response))):
            self.assertEqual((await adapter.generate_analysis("prompt")).content, "hola")

    async def test_sdk_internal_retries_are_disabled(self):
        with patch.object(settings, "GEMINI_API_KEY", "test-not-a-real-key"), patch("google.genai.Client") as client:
            GeminiClientImpl()._create_client()
        options = client.call_args.kwargs["http_options"]
        self.assertEqual(options.retry_options.attempts, 1)
        self.assertGreater(options.timeout, 0)

    async def test_limits_are_passed_to_sdk_and_client_is_closed(self):
        fake = sdk_client(sdk_chunks(sdk_response()))
        adapter = GeminiClientImpl()
        with patch.object(adapter, "_create_client", return_value=fake), patch.object(settings, "GEMINI_MAX_OUTPUT_TOKENS", 2048):
            result = await adapter.generate_analysis("prompt")
        self.assertEqual(result.content, "hola")
        config = fake.aio.models.generate_content_stream.call_args.kwargs["config"]
        self.assertEqual(config.max_output_tokens, 500)
        self.assertLessEqual(config.temperature, 0.1)
        fake.aio.aclose.assert_awaited_once()
        fake.close.assert_called_once()

    async def test_429_retries_only_once_and_returns_safe_error(self):
        clients = [sdk_client(failure=FakeAPIError(429)), sdk_client(failure=FakeAPIError(429))]
        adapter = GeminiClientImpl()
        with patch.object(adapter, "_create_client", side_effect=clients) as create, patch(
            "app.inventory_intelligence.infrastructure.gemini.gemini_client.asyncio.sleep", new_callable=AsyncMock,
        ) as sleep:
            with self.assertRaises(AnalysisUnavailableError) as caught:
                await adapter.generate_analysis("prompt")
        self.assertEqual(create.call_count, 2)
        sleep.assert_awaited_once_with(0.5)
        self.assertEqual(caught.exception.code, "rate_limit")
        self.assertNotIn("SECRET", caught.exception.message)
        for client in clients:
            client.aio.aclose.assert_awaited_once()

    async def test_transient_retry_can_succeed(self):
        clients = [sdk_client(failure=FakeAPIError(503)), sdk_client(sdk_chunks(sdk_response()))]
        adapter = GeminiClientImpl()
        with patch.object(adapter, "_create_client", side_effect=clients), patch(
            "app.inventory_intelligence.infrastructure.gemini.gemini_client.asyncio.sleep", new_callable=AsyncMock,
        ):
            self.assertEqual((await adapter.generate_analysis("prompt")).content, "hola")

    async def test_no_retry_after_output_or_auth_error(self):
        for stream, failure in ((sdk_chunks(sdk_response(), FakeAPIError(429)), None), (None, FakeAPIError(403))):
            adapter = GeminiClientImpl()
            fake = sdk_client(stream, failure)
            with patch.object(adapter, "_create_client", return_value=fake) as create:
                with self.assertRaises(AnalysisUnavailableError):
                    await adapter.generate_analysis("prompt")
            create.assert_called_once()

    async def test_deadline_stops_hung_provider_and_closes_client(self):
        async def hung_stream():
            await asyncio.Event().wait()
            yield sdk_response()

        adapter = GeminiClientImpl()
        fake = sdk_client(hung_stream())
        with patch.object(adapter, "_create_client", return_value=fake), patch.object(settings, "GEMINI_REQUEST_TIMEOUT_SECONDS", 0.01):
            with self.assertRaises(AnalysisUnavailableError) as caught:
                await adapter.generate_analysis("prompt")
        self.assertEqual(caught.exception.code, "timeout")
        fake.aio.aclose.assert_awaited_once()

    async def test_missing_key_never_creates_sdk_client(self):
        with patch.object(settings, "GEMINI_API_KEY", ""):
            with self.assertRaises(AnalysisUnavailableError) as caught:
                await GeminiClientImpl().generate_analysis("prompt")
        self.assertEqual(caught.exception.code, "not_configured")


if __name__ == "__main__":
    unittest.main()
