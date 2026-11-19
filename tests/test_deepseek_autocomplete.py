import asyncio
import json
import unittest
from datetime import date, datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

import httpx

from app.core.config import settings
from app.dependencies import get_wine_autocomplete_service
from app.core.space_security import authorize_inventory_autocomplete
from app.main import app
from app.inventory_intelligence.domain.models.wine_autocomplete import WineAutocompleteGeneration, WineAutocompleteResult
from pydantic import ValidationError
from app.inventory_intelligence.applications.wine_autocomplete_service import WineAutocompleteService
from app.inventory_intelligence.infrastructure.deepseek.wine_autocomplete_client import DeepSeekWineAutocompleteClient
from app.inventory_intelligence.infrastructure.gemini.wine_autocomplete_client import GeminiWineAutocompleteClient


class DeepSeekAutocompleteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        for key, value in (("DEEPSEEK_API_KEY", "test-only"), ("DEEPSEEK_MODEL", "deepseek-flash"), ("DEEPSEEK_REQUEST_TIMEOUT_SECONDS", 1.0)):
            setting = patch.object(settings, key, value)
            setting.start()
            self.addCleanup(setting.stop)
        self.calls = []

    def provider(self, handler):
        def tracked(request):
            self.calls.append(request)
            return handler(request)
        return DeepSeekWineAutocompleteClient(transport=httpx.MockTransport(tracked))

    def search_result(self):
        return {"results": [{"title": "Bodega", "url": "https://example.com/ficha", "content": "Tabernero Borgona, Peru, 750 ml, alcohol 11%"}]}

    def completion(self, text='{"winery":"Tabernero","country":"Peru","alcohol":11}'):
        return {"choices": [{"finish_reason": "stop", "message": {"content": text}}]}

    async def test_search_then_json_extraction_and_real_source_metadata(self):
        def handler(request):
            self.assertEqual(request.headers["Authorization"], "Bearer test-only")
            self.assertEqual(request.url.host, "api.deepseek.com")
            if request.url.path == "/v1/tools/search":
                payload = json.loads(request.content)
                self.assertEqual(payload["count"], 5)
                self.assertIs(payload["need_content"], True)
                self.assertIn("Tabernero Borgona", payload["query"])
                return httpx.Response(200, json=self.search_result())
            payload = json.loads(request.content)
            self.assertEqual(payload["model"], "deepseek-flash")
            self.assertEqual(payload["temperature"], 0.1)
            self.assertEqual(payload["max_tokens"], 500)
            self.assertEqual(payload["thinking"], {"type": "disabled"})
            self.assertEqual(payload["response_format"], {"type": "json_object"})
            self.assertIn("web_evidence", json.loads(payload["messages"][1]["content"]))
            return httpx.Response(200, json=self.completion('```json\n{"winery":"Tabernero","tasting_notes":"NO","sources":[{"url":"https://invented.example"}]}\n```'))
        result = await WineAutocompleteService(self.provider(handler)).suggest("Tabernero Borgona")
        data = result.model_dump(mode="json", exclude_unset=True)
        self.assertEqual(result.winery, "Tabernero")
        self.assertNotIn("tasting_notes", data)
        self.assertNotIn("invented.example", json.dumps(data))
        self.assertEqual(data["sources"], [{"title": "Bodega", "url": "https://example.com/ficha"}])
        self.assertNotIn("search_suggestions_html", data)
        self.assertEqual(len(self.calls), 2)

    async def test_empty_or_unsafe_search_results_skip_generation(self):
        for data in ({"results": []}, {}, {"results": [{"url": "javascript:alert(1)", "content": "NO"}]}, {"results": [{"url": "https://user:password@example.com", "content": "NO"}]}):
            self.calls.clear()
            result = await WineAutocompleteService(self.provider(lambda request: httpx.Response(200, json=data))).suggest("Vino")
            self.assertEqual(result.model_dump(exclude_unset=True), {})
            self.assertEqual(len(self.calls), 1)

    async def test_provider_errors_do_not_retry_or_fall_back(self):
        for status in (401, 402, 429, 503):
            self.calls.clear()
            result = await WineAutocompleteService(self.provider(lambda request: httpx.Response(status, json={"error": {"message": "failure"}}))).suggest("Vino")
            self.assertEqual(result.model_dump(exclude_unset=True), {})
            self.assertEqual(len(self.calls), 1)

    async def test_invalid_or_truncated_extraction_returns_empty(self):
        for text, reason in (("invalid", "stop"), ('{"winery":"Bodega"}', "length"), ("{}", "content_filter")):
            self.calls.clear()
            def handler(request):
                if request.url.path == "/v1/tools/search":
                    return httpx.Response(200, json=self.search_result())
                completion = self.completion(text)
                completion["choices"][0]["finish_reason"] = reason
                return httpx.Response(200, json=completion)
            result = await WineAutocompleteService(self.provider(handler)).suggest("Vino")
            self.assertEqual(result.model_dump(exclude_unset=True), {})
            self.assertEqual(len(self.calls), 2)

    async def test_missing_key_and_oversized_name_send_no_requests(self):
        provider = self.provider(lambda request: self.fail("Unexpected remote call"))
        with patch.object(settings, "DEEPSEEK_API_KEY", ""):
            result = await WineAutocompleteService(provider).suggest("Vino")
        self.assertEqual(result.model_dump(exclude_unset=True), {})
        result = await WineAutocompleteService(provider).suggest("x" * 129)
        self.assertEqual(result.model_dump(exclude_unset=True), {})
        self.assertEqual(self.calls, [])

    async def test_response_body_is_bounded(self):
        result = await WineAutocompleteService(self.provider(lambda request: httpx.Response(200, content=b"x" * 524289))).suggest("Vino")
        self.assertEqual(result.model_dump(exclude_unset=True), {})
        self.assertEqual(len(self.calls), 1)

    async def test_redirects_are_not_followed(self):
        result = await WineAutocompleteService(self.provider(lambda request: httpx.Response(307, headers={"Location": "https://other.example"}))).suggest("Vino")
        self.assertEqual(result.model_dump(exclude_unset=True), {})
        self.assertEqual(len(self.calls), 1)

    async def test_shared_deadline_cancels_slow_extraction(self):
        async def handler(request):
            self.calls.append(request)
            if request.url.path == "/v1/tools/search":
                return httpx.Response(200, json=self.search_result())
            await asyncio.Event().wait()
        provider = DeepSeekWineAutocompleteClient(transport=httpx.MockTransport(handler))
        with patch.object(settings, "DEEPSEEK_REQUEST_TIMEOUT_SECONDS", 0.01):
            result = await WineAutocompleteService(provider).suggest("Vino")
        self.assertEqual(result.model_dump(exclude_unset=True), {})
        self.assertEqual(len(self.calls), 2)

    def test_evidence_is_bounded_and_deduplicated(self):
        row = {"url": "https://example.com/ficha", "title": "x" * 1000, "content": "x" * 100000}
        evidence = DeepSeekWineAutocompleteClient._web_evidence({"results": [row] * 100})
        self.assertEqual(len(evidence), 1)
        self.assertEqual(len(evidence[0]["text"]), 2000)
        self.assertEqual(len(evidence[0]["title"]), 300)

    def test_composition_selects_explicit_provider_without_fallback(self):
        with patch.object(settings, "WINE_AUTOCOMPLETE_PROVIDER", "deepseek"):
            self.assertIsInstance(get_wine_autocomplete_service().provider, DeepSeekWineAutocompleteClient)
        with patch.object(settings, "WINE_AUTOCOMPLETE_PROVIDER", "gemini"):
            self.assertIsInstance(get_wine_autocomplete_service().provider, GeminiWineAutocompleteClient)

    async def test_registration_date_and_complete_fields_are_sent_to_extractor(self):
        def handler(request):
            if request.url.path == "/v1/tools/search":
                self.assertIn("ficha tecnica", json.loads(request.content)["query"])
                return httpx.Response(200, json=self.search_result())
            payload = json.loads(request.content)
            contents = json.loads(payload["messages"][1]["content"])
            self.assertEqual(contents["registration_date"], "2026-01-10")
            self.assertIn("ventana", payload["messages"][0]["content"].lower())
            self.assertIn("cosecha real", payload["messages"][0]["content"])
            text = json.dumps({
                "winery": "Tabernero", "vintage": None, "drinking_window_start": 2026,
                "drinking_window_end": 2027, "estimated_fields": ["drinking_window_start", "drinking_window_end"],
                "estimation_basis": "Orientativa desde registro; asume botella sin abrir y bien conservada, sin cosecha confirmada.",
            })
            return httpx.Response(200, json=self.completion(text))
        result = await WineAutocompleteService(self.provider(handler)).suggest("Tabernero Borgona", registration_date=date(2026, 1, 10))
        self.assertEqual(result.registration_date, date(2026, 1, 10))
        self.assertEqual(result.drinking_window_end, 2027)
        self.assertEqual(result.estimated_fields, ["drinking_window_start", "drinking_window_end"])
        self.assertIsNone(result.vintage)

    def test_estimates_require_explicit_metadata_and_cannot_mark_vintage_as_estimated(self):
        for values in (
            {"estimated_fields": ["vintage"], "vintage": "2026", "estimation_basis": "guess"},
            {"estimated_fields": ["drinking_window_end"], "drinking_window_end": 2027},
            {"estimated_fields": ["drinking_window_end"], "estimation_basis": "guess"},
            {"estimated_fields": ["drinking_window_end", "drinking_window_end"], "drinking_window_end": 2027, "estimation_basis": "guess"},
            {"drinking_window_start": 2028, "drinking_window_end": 2027},
        ):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                WineAutocompleteGeneration.model_validate(values)
        result = WineAutocompleteGeneration(drinking_window_start=2026, drinking_window_end=2030)
        self.assertEqual(result.estimated_fields, [])

    async def test_http_accepts_optional_registration_date_and_rejects_invalid_dates(self):
        service = SimpleNamespace(suggest=AsyncMock(return_value=WineAutocompleteResult()))
        previous = app.dependency_overrides.copy()
        app.dependency_overrides.update({
            authorize_inventory_autocomplete: lambda: None,
            get_wine_autocomplete_service: lambda: service,
        })
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post("/api/v1/inventory/ai-autocomplete", json={"wine_name": "Vino", "registration_date": "2026-01-10"})
                self.assertEqual(response.status_code, 200, response.text)
                service.suggest.assert_awaited_once_with("Vino", registration_date=date(2026, 1, 10))
                for invalid in ("invalid", "2026-02-30", "1899-12-31", (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()):
                    response = await client.post("/api/v1/inventory/ai-autocomplete", json={"wine_name": "Vino", "registration_date": invalid})
                    self.assertEqual(response.status_code, 422, response.text)
                service.suggest.assert_awaited_once()
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(previous)
