try:
    from .gemini_client import GeminiClientImpl
except ModuleNotFoundError:  # pragma: no cover - dependencia opcional
    GeminiClientImpl = None
