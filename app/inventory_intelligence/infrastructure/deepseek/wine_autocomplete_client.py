import asyncio
import json
import re
from urllib.parse import urlsplit
from datetime import date, datetime, timezone

import httpx

from app.core.config import settings
from app.inventory_intelligence.applications.wine_autocomplete_prompts import EXTRACTION_INSTRUCTION, SYSTEM_INSTRUCTION, WINDOW_ESTIMATION_INSTRUCTION
from app.inventory_intelligence.domain.models.wine_autocomplete import WineAutocompleteGeneration
from app.shared.infrastructure.deepseek_client import DeepSeekClient


class DeepSeekWineAutocompleteClient:
    """One Search API call + one JSON extraction; never silently use model memory."""

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None):
        self.transport = transport

    @staticmethod
    def _web_evidence(data: dict) -> list[dict]:
        evidence, seen = [], set()
        results = data.get("results")
        if not isinstance(results, list):
            return []
        for item in results[:5]:
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            if not isinstance(url, str) or len(url) > 2048 or url in seen:
                continue
            parsed = urlsplit(url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                continue
            text = next((item.get(key) for key in ("content", "summary", "snippet") if isinstance(item.get(key), str) and item[key].strip()), None)
            if text is None:
                continue
            title = item.get("title")
            evidence.append({
                "url": url, "title": title[:300] if isinstance(title, str) else parsed.hostname,
                "text": text[:2000],
            })
            seen.add(url)
        return evidence

    async def generate(self, wine_name: str, *, registration_date: date | None = None) -> str:
        if not settings.DEEPSEEK_API_KEY:
            raise RuntimeError("DeepSeek is not configured")
        # The Search API accepts at most 128 Unicode characters: never truncate identity.
        registration_date = registration_date or datetime.now(timezone.utc).date()
        query = wine_name.strip() + " vino ficha tecnica bodega cepa crianza alcohol añada"
        if len(query) > 128:
            query = wine_name.strip()
        if len(query) > 128:
            return ""
        async with asyncio.timeout(settings.DEEPSEEK_REQUEST_TIMEOUT_SECONDS):
            async with DeepSeekClient(transport=self.transport) as client:
                search = await client.post_json("/v1/tools/search", {
                    "query": query, "count": 5, "need_content": True,
                })
                evidence = self._web_evidence(search)
                if not evidence:
                    return ""
                example = WineAutocompleteGeneration().model_dump(mode="json")
                response = await client.post_json("/chat/completions", {
                    "model": settings.DEEPSEEK_MODEL,
                    "messages": [
                        {"role": "system", "content": SYSTEM_INSTRUCTION + " " + EXTRACTION_INSTRUCTION + " " + WINDOW_ESTIMATION_INSTRUCTION
                         + " Usa exactamente estas claves JSON: " + json.dumps(example, separators=(",", ":"))},
                        {"role": "user", "content": json.dumps({"wine_name": wine_name, "registration_date": registration_date.isoformat(), "web_evidence": evidence}, ensure_ascii=False, separators=(",", ":"))},
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.1,
                    "max_tokens": 500,
                    "thinking": {"type": "disabled"},
                    "stream": False,
                })
                choice = response["choices"][0]
                if choice.get("finish_reason") != "stop":
                    return ""
                raw = choice["message"].get("content") or ""
                if not isinstance(raw, str) or len(raw) > 8192:
                    return ""
                raw = raw.strip()
                fenced = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", raw, re.IGNORECASE)
                if fenced:
                    raw = fenced.group(1)
                suggestion = WineAutocompleteGeneration.model_validate_json(raw)
                result = suggestion.model_dump(mode="json")
                # Only search-result URLs; ignore model-provided citations and extra fields.
                result["sources"] = [{"url": item["url"], "title": item["title"]} for item in evidence]
                result["registration_date"] = registration_date.isoformat()
                return json.dumps(result, ensure_ascii=False)
