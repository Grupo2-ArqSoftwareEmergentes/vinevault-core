import logging
from google import genai
from google.genai import errors
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.core.config import settings
from app.inventory_intelligence.domain.services.gemini_service import GeminiService, GeminiResponse

logger = logging.getLogger(__name__)


class GeminiClientImpl(GeminiService):
    def __init__(self):
        # El SDK de google-genai requiere la API Key
        # Si no está definida, arrojará un error al inicializar
        api_key = settings.GEMINI_API_KEY
        if not api_key:
            logger.warning("GEMINI_API_KEY no está configurada en settings.")
        
        # Inicializar el cliente oficial de Google GenAI
        self._client = genai.Client(api_key=api_key)
        self._model = settings.GEMINI_MODEL or "gemini-1.5-flash"

    # Reintentar la llamada asíncrona ante excepciones del SDK con backoff exponencial
    # Reintenta hasta 3 veces con una espera inicial de 2 segundos, multiplicando la espera exponencialmente
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=10),
        retry=retry_if_exception_type((errors.APIError, Exception)),
        reraise=True,
    )
    async def _call_gemini_api(self, prompt: str) -> GeminiResponse:
        logger.info("Enviando petición a Google Gemini API usando el modelo: %s", self._model)
        
        # Utilizar client.aio para llamadas completamente asíncronas
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=prompt,
        )
        
        # Obtener respuesta e información de tokens si está disponible
        content = response.text or "No se pudo obtener una respuesta de la inteligencia artificial."
        
        tokens_used = None
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            tokens_used = response.usage_metadata.total_token_count

        return GeminiResponse(content=content, tokens_used=tokens_used)

    async def generate_analysis(self, prompt: str) -> GeminiResponse:
        if not settings.GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY no está configurada en la aplicación.")
        
        try:
            return await self._call_gemini_api(prompt)
        except errors.APIError as e:
            logger.error("Error específico de la API de Google Gemini: %s", str(e))
            raise e
        except Exception as e:
            logger.error("Error inesperado al invocar Google Gemini: %s", str(e))
            raise e
