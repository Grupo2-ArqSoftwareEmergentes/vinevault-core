from collections.abc import AsyncGenerator

from app.inventory_intelligence.domain.models import AnalysisRequest, AnalysisResult
from app.inventory_intelligence.domain.models.analysis_type import AnalysisType
from app.inventory_intelligence.domain.services.gemini_service import GeminiService, GeminiChunk
from app.inventory_intelligence.interfaces.acl import InventoryDataFacade
from app.inventory_intelligence.applications.prompt_builder import PromptBuilder

EMPTY_MESSAGE = "No hay vinos en esta cava para analizar."


class AnalysisCellarNotFoundError(ValueError):
    pass


class AnalysisApplicationService:
    def __init__(self, gemini_service: GeminiService, inventory_data_facade: InventoryDataFacade):
        self._gemini_service = gemini_service
        self._inventory_data_facade = inventory_data_facade

    async def prepare_analysis(self, request: AnalysisRequest) -> str | AnalysisResult:
        cellar_data = await self._inventory_data_facade.get_cellar_data_for_intelligence(
            request.wine_cellar_id,
            include_device=request.analysis_type in {
                AnalysisType.MONTHLY_REPORT, AnalysisType.SENSOR_ANALYSIS, AnalysisType.CHAT,
            },
        )
        if cellar_data is None:
            raise AnalysisCellarNotFoundError("Wine cellar not found")
        if cellar_data.item_count == 0:
            return AnalysisResult(
                analysis_type=request.analysis_type,
                wine_cellar_id=request.wine_cellar_id,
                status="empty", message=EMPTY_MESSAGE, content=EMPTY_MESSAGE, tokens_used=0,
            )
        return PromptBuilder.build_prompt(request.analysis_type, cellar_data, request.user_query)

    def stream_prepared_analysis(self, prompt: str) -> AsyncGenerator[GeminiChunk, None]:
        return self._gemini_service.stream_analysis(prompt)

    async def execute_analysis(self, request: AnalysisRequest) -> AnalysisResult:
        prepared = await self.prepare_analysis(request)
        if isinstance(prepared, AnalysisResult):
            return prepared
        response = await self._gemini_service.generate_analysis(prepared)
        return AnalysisResult(
            analysis_type=request.analysis_type, content=response.content,
            wine_cellar_id=request.wine_cellar_id, tokens_used=response.tokens_used,
        )
