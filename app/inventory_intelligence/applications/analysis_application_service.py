from typing import Optional
from fastapi import HTTPException, status
from uuid import UUID

from app.inventory_intelligence.domain.models import AnalysisRequest, AnalysisResult
from app.inventory_intelligence.domain.services.gemini_service import GeminiService
from app.inventory_intelligence.interfaces.acl import InventoryDataFacade
from app.inventory_intelligence.applications.prompt_builder import PromptBuilder


class AnalysisApplicationService:
    def __init__(
        self,
        gemini_service: GeminiService,
        inventory_data_facade: InventoryDataFacade,
    ):
        self._gemini_service = gemini_service
        self._inventory_data_facade = inventory_data_facade

    async def execute_analysis(self, request: AnalysisRequest) -> AnalysisResult:
        # 1. Obtener los datos mínimos de la bodega mediante el ACL
        cellar_data = await self._inventory_data_facade.get_cellar_data_for_intelligence(
            request.wine_cellar_id
        )
        if not cellar_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Wine cellar not found",
            )

        # 2. Generar el prompt optimizado para tokens
        prompt = PromptBuilder.build_prompt(
            analysis_type=request.analysis_type,
            cellar_data=cellar_data,
            user_query=request.user_query,
        )

        # 3. Invocar al servicio Gemini
        try:
            gemini_response = await self._gemini_service.generate_analysis(prompt)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Error communicating with Google Gemini API: {str(e)}",
            )

        # 4. Construir y retornar el resultado de dominio
        return AnalysisResult(
            analysis_type=request.analysis_type,
            content=gemini_response.content,
            wine_cellar_id=request.wine_cellar_id,
            tokens_used=gemini_response.tokens_used,
        )
