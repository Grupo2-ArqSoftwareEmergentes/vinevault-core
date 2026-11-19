"""Shared, bounded DeepSeek transport; callers own their total operation deadline."""
import json

import httpx
from anyio import CancelScope

from app.core.config import settings


class DeepSeekClient:
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None):
        self.transport = transport
        self.client = None

    async def __aenter__(self):
        if not settings.DEEPSEEK_API_KEY:
            raise RuntimeError("DeepSeek is not configured")
        self.client = httpx.AsyncClient(
            base_url="https://api.deepseek.com",
            headers={"Authorization": "Bearer " + settings.DEEPSEEK_API_KEY},
            timeout=settings.DEEPSEEK_REQUEST_TIMEOUT_SECONDS,
            transport=self.transport or httpx.AsyncHTTPTransport(retries=0),
            follow_redirects=False,
        )
        await self.client.__aenter__()
        return self

    async def __aexit__(self, *args):
        with CancelScope(shield=True):
            return await self.client.__aexit__(*args)

    async def post_json(self, path: str, payload: dict) -> dict:
        async with self.client.stream("POST", path, json=payload) as response:
            response.raise_for_status()
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > 524288:
                    raise ValueError("DeepSeek response exceeds size limit")
            data = json.loads(body)
            if not isinstance(data, dict):
                raise ValueError("Expected a JSON object from DeepSeek")
            return data
