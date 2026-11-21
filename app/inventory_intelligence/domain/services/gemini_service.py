from abc import ABC, abstractmethod
from pydantic import BaseModel
from typing import Optional
from collections.abc import AsyncGenerator


class GeminiResponse(BaseModel):
    content: str
    tokens_used: Optional[int] = None


class AnalysisUnavailableError(Exception):
    def __init__(self, code: str, message: str, http_status: int = 503):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


class GeminiChunk(BaseModel):
    text: str = ""
    tokens_used: int | None = None


class GeminiService(ABC):
    @abstractmethod
    def stream_analysis(self, prompt: str) -> AsyncGenerator[GeminiChunk, None]:
        """Yield provider chunks without blocking the event loop."""
        raise NotImplementedError

    async def generate_analysis(self, prompt: str) -> GeminiResponse:
        content: list[str] = []
        tokens_used = None
        async for chunk in self.stream_analysis(prompt):
            content.append(chunk.text)
            if chunk.tokens_used is not None:
                tokens_used = chunk.tokens_used
        return GeminiResponse(content="".join(content), tokens_used=tokens_used)
