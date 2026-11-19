import asyncio
import logging

import httpx

from app.assistant.domain.models import AssistantMode, AssistantUnavailableError
from app.core.config import settings
from app.shared.infrastructure.deepseek_client import DeepSeekClient


logger = logging.getLogger(__name__)


class DeepSeekAssistantClient:
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None):
        self.transport = transport

    async def reply(self, messages: list[dict[str, str]], mode: AssistantMode) -> str:
        if not settings.DEEPSEEK_API_KEY:
            raise AssistantUnavailableError("not_configured", "El asistente no está configurado.", 503)
        try:
            async with asyncio.timeout(settings.DEEPSEEK_REQUEST_TIMEOUT_SECONDS):
                async with DeepSeekClient(transport=self.transport) as client:
                    data = await client.post_json("/chat/completions", {
                        "model": settings.DEEPSEEK_MODEL,
                        "messages": messages,
                        "temperature": 0.2 if mode == AssistantMode.CHAT else 0.4,
                        "max_tokens": 800,
                        "thinking": {"type": "disabled"},
                        "stream": False,
                    })
                choice = data["choices"][0]
                text = choice["message"].get("content")
                if choice.get("finish_reason") != "stop" or not isinstance(text, str) or not text.strip() or len(text) > 16000:
                    raise ValueError("Invalid or incomplete assistant response")
                return text.strip()
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise AssistantUnavailableError("timeout", "El asistente tardó demasiado. Inténtalo más tarde.", 504) from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            logger.warning("DeepSeek assistant rejected request (status %s)", status)
            if status in {402, 429}:
                raise AssistantUnavailableError("quota_exceeded", "La cuota del asistente está temporalmente agotada.", 429) from exc
            if status in {408, 504}:
                raise AssistantUnavailableError("timeout", "El asistente tardó demasiado. Inténtalo más tarde.", 504) from exc
            raise AssistantUnavailableError("unavailable", "El asistente no está disponible temporalmente.", 503) from exc
        except httpx.RequestError as exc:
            raise AssistantUnavailableError("unavailable", "No se pudo conectar con el asistente.", 503) from exc
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
            raise AssistantUnavailableError("invalid_response", "El asistente devolvió una respuesta no válida.", 502) from exc
