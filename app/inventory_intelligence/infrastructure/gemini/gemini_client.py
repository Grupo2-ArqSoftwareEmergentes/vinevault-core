import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

import httpx
from anyio import CancelScope

if TYPE_CHECKING:
    from google.genai import Client, types

from app.core.config import settings
from app.inventory_intelligence.domain.services.gemini_service import (
    AnalysisUnavailableError, GeminiChunk, GeminiService,
)

logger = logging.getLogger(__name__)


class GeminiClientImpl(GeminiService):
    """Lazy, request-scoped async streaming with a bounded retry before any output."""

    def _create_client(self) -> "Client":
        if not settings.GEMINI_API_KEY:
            raise AnalysisUnavailableError("not_configured", "El análisis con IA no está configurado.")
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise AnalysisUnavailableError("not_configured", "El análisis con IA no está disponible.") from exc
        return genai.Client(
            api_key=settings.GEMINI_API_KEY,
            http_options=types.HttpOptions(
                timeout=int(settings.GEMINI_REQUEST_TIMEOUT_SECONDS * 1000),
                # SDK defaults to five attempts; retries are explicitly managed below.
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )

    def _generation_config(self) -> "types.GenerateContentConfig":
        from google.genai import types

        return types.GenerateContentConfig(
            max_output_tokens=max(1, min(500, settings.GEMINI_MAX_OUTPUT_TOKENS)),
            temperature=max(0.0, min(0.1, settings.GEMINI_TEMPERATURE)),
            thinking_config=types.ThinkingConfig(thinking_budget=0)
            if settings.GEMINI_MODEL.startswith("gemini-2.5-flash") else None,
        )

    @staticmethod
    def _failure(exc: Exception) -> AnalysisUnavailableError:
        code = getattr(exc, "code", None)
        if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
            return AnalysisUnavailableError("timeout", "El análisis tardó demasiado. Inténtalo más tarde.", 504)
        if code == 429:
            return AnalysisUnavailableError(
                "rate_limit", "La cuota de IA está temporalmente agotada. Inténtalo más tarde.", 429,
            )
        return AnalysisUnavailableError(
            "unavailable", "No se pudo completar el análisis con IA. Inténtalo más tarde.",
        )

    async def stream_analysis(self, prompt: str) -> AsyncGenerator[GeminiChunk, None]:
        emitted = False
        try:
            async with asyncio.timeout(settings.GEMINI_REQUEST_TIMEOUT_SECONDS):
                for attempt in range(2):
                    client = None
                    try:
                        client = self._create_client()
                        stream = await client.aio.models.generate_content_stream(
                            model=settings.GEMINI_MODEL,
                            contents=prompt,
                            config=self._generation_config(),
                        )
                        try:
                            async for response in stream:
                                # Never expose model thought blocks as inventory analysis.
                                parts = (
                                    response.candidates[0].content.parts
                                    if response.candidates and response.candidates[0].content else []
                                )
                                text = "".join(part.text or "" for part in parts or [] if not part.thought)
                                usage = response.usage_metadata
                                if text:
                                    emitted = True
                                yield GeminiChunk(
                                    text=text,
                                    tokens_used=usage.total_token_count if usage else None,
                                )
                        finally:
                            with CancelScope(shield=True):
                                await stream.aclose()
                        if not emitted:
                            raise AnalysisUnavailableError(
                                "empty_response", "La IA no generó un análisis. Inténtalo más tarde.",
                            )
                        return
                    except AnalysisUnavailableError:
                        raise
                    except Exception as exc:
                        code = getattr(exc, "code", None)
                        # Never replay a partially delivered answer, or retry auth/validation errors.
                        if not emitted and attempt == 0 and code in {429, 500, 502, 503, 504}:
                            logger.warning("Retrying Gemini once after upstream status %s", code)
                        else:
                            logger.warning("Gemini request failed (status %s)", code)
                            raise self._failure(exc) from exc
                    finally:
                        if client is not None:
                            # ASGI disconnect cancels the request scope; allow cleanup to finish.
                            with CancelScope(shield=True):
                                try:
                                    await client.aio.aclose()
                                finally:
                                    client.close()
                    await asyncio.sleep(0.5)
        except TimeoutError as exc:
            raise AnalysisUnavailableError(
                "timeout", "El análisis tardó demasiado. Inténtalo más tarde.", 504,
            ) from exc
