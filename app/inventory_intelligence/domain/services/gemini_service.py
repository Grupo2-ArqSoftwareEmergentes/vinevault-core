from abc import ABC, abstractmethod
from pydantic import BaseModel
from typing import Optional


class GeminiResponse(BaseModel):
    content: str
    tokens_used: Optional[int] = None


class GeminiService(ABC):
    @abstractmethod
    async def generate_analysis(self, prompt: str) -> GeminiResponse:
        """
        Envía un prompt optimizado a Google Gemini y retorna la respuesta.
        """
        pass
