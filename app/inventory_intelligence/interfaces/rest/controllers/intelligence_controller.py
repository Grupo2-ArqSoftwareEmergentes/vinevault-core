import logging
from collections.abc import AsyncIterator
from contextlib import aclosing

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from uuid import UUID

from app.dependencies import (
    get_current_user_id,
    get_wine_cellar_repository,
    get_space_repository,
)
from app.inventory_intelligence.domain.models.analysis_type import AnalysisType
from app.inventory_intelligence.domain.models.analysis_request import AnalysisRequest
from app.inventory_intelligence.domain.models.analysis_result import AnalysisResult
from app.inventory_intelligence.domain.services.gemini_service import AnalysisUnavailableError
from app.inventory_intelligence.interfaces.rest.resources.response_models import AnalysisStreamEvent
from app.inventory_intelligence.interfaces.rest.resources import (
    AnalyzeStockRequest,
    RecommendPurchasesRequest,
    MonthlyReportRequest,
    ChatRequest,
    AnalysisResponse,
)
# Nota: get_analysis_application_service se registrará en app/dependencies.py
from app.dependencies import get_analysis_application_service
from app.inventory_intelligence.applications.analysis_application_service import (
    AnalysisApplicationService, AnalysisCellarNotFoundError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ai", tags=["Inventory Intelligence (AI)"])


async def _verify_cellar_ownership_and_get(
    wine_cellar_id: UUID,
    user_id: int,
    wine_cellar_repo,
    space_repo,
):
    """
    Verifica que la bodega de vino exista y pertenezca al usuario autenticado.
    Esta lógica es un puerto directo de la seguridad implementada en wine_cellar_controller.
    """
    wine_cellar = await wine_cellar_repo.find_by_id(wine_cellar_id)
    if not wine_cellar:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Wine cellar not found",
        )

    space = await space_repo.find_by_id(wine_cellar.space_id)
    if not space:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Space associated with wine cellar not found",
        )

    if space.owner_user_id.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Wine cellar does not belong to user",
        )

    return wine_cellar


async def _json_analysis(service: AnalysisApplicationService, request: AnalysisRequest) -> AnalysisResponse:
    try:
        return AnalysisResponse.from_domain(await service.execute_analysis(request))
    except AnalysisCellarNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Wine cellar not found") from exc
    except AnalysisUnavailableError as exc:
        raise HTTPException(
            status_code=exc.http_status, detail=exc.message,
            headers={"Retry-After": "30"} if exc.http_status == 429 else None,
        ) from exc


def _encode_event(event: AnalysisStreamEvent) -> str:
    return f"event: {event.type}\ndata: {event.model_dump_json(exclude_none=True)}\n\n"


async def _analysis_events(
    service: AnalysisApplicationService, prompt: str, request: AnalysisRequest,
) -> AsyncIterator[str]:
    content: list[str] = []
    tokens_used = None
    try:
        async with aclosing(service.stream_prepared_analysis(prompt)) as chunks:
            async for chunk in chunks:
                if chunk.tokens_used is not None:
                    tokens_used = chunk.tokens_used
                if chunk.text:
                    content.append(chunk.text)
                    yield _encode_event(AnalysisStreamEvent(type="delta", text=chunk.text))
        result = AnalysisResult(
            analysis_type=request.analysis_type, wine_cellar_id=request.wine_cellar_id,
            content="".join(content), tokens_used=tokens_used,
        )
        yield _encode_event(AnalysisStreamEvent(type="done", result=AnalysisResponse.from_domain(result)))
    except AnalysisUnavailableError as exc:
        yield _encode_event(AnalysisStreamEvent(type="error", code=exc.code, message=exc.message))
    except Exception:
        # HTTP headers may already be sent: report a terminal SSE error, never raw SDK details.
        logger.warning("Inventory analysis stream failed")
        yield _encode_event(AnalysisStreamEvent(
            type="error", code="unavailable", message="No se pudo completar el análisis con IA.",
        ))


@router.post("/analyze-stock", response_model=AnalysisResponse, responses={
    200: {"content": {"text/event-stream": {"schema": {"type": "string"}}}},
})
async def analyze_stock(
    request: AnalyzeStockRequest,
    http_request: Request,
    stream: bool = False,
    user_id: int = Depends(get_current_user_id),
    wine_cellar_repo = Depends(get_wine_cellar_repository),
    space_repo = Depends(get_space_repository),
    app_service: AnalysisApplicationService = Depends(get_analysis_application_service),
):
    # Validar propiedad
    await _verify_cellar_ownership_and_get(
        request.wine_cellar_id, user_id, wine_cellar_repo, space_repo
    )

    # Crear request de dominio
    domain_request = AnalysisRequest(
        analysis_type=AnalysisType.STOCK_ANALYSIS,
        wine_cellar_id=request.wine_cellar_id,
        user_id=user_id,
    )

    if not stream and "text/event-stream" not in http_request.headers.get("accept", "").lower():
        return await _json_analysis(app_service, domain_request)
    try:
        prepared = await app_service.prepare_analysis(domain_request)
    except AnalysisCellarNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Wine cellar not found") from exc
    if isinstance(prepared, AnalysisResult):
        # Empty-cellar early exit is always JSON, even when streaming was requested.
        return AnalysisResponse.from_domain(prepared)
    return StreamingResponse(
        _analysis_events(app_service, prepared, domain_request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@router.post("/recommend-purchases", response_model=AnalysisResponse)
async def recommend_purchases(
    request: RecommendPurchasesRequest,
    user_id: int = Depends(get_current_user_id),
    wine_cellar_repo = Depends(get_wine_cellar_repository),
    space_repo = Depends(get_space_repository),
    app_service: AnalysisApplicationService = Depends(get_analysis_application_service),
) -> AnalysisResponse:
    # Validar propiedad
    await _verify_cellar_ownership_and_get(
        request.wine_cellar_id, user_id, wine_cellar_repo, space_repo
    )

    # Crear request de dominio
    domain_request = AnalysisRequest(
        analysis_type=AnalysisType.PURCHASE_RECOMMENDATION,
        wine_cellar_id=request.wine_cellar_id,
        user_id=user_id,
    )

    # Ejecutar
    return await _json_analysis(app_service, domain_request)


@router.post("/monthly-report", response_model=AnalysisResponse)
async def monthly_report(
    request: MonthlyReportRequest,
    user_id: int = Depends(get_current_user_id),
    wine_cellar_repo = Depends(get_wine_cellar_repository),
    space_repo = Depends(get_space_repository),
    app_service: AnalysisApplicationService = Depends(get_analysis_application_service),
) -> AnalysisResponse:
    # Validar propiedad
    await _verify_cellar_ownership_and_get(
        request.wine_cellar_id, user_id, wine_cellar_repo, space_repo
    )

    # Crear request de dominio
    domain_request = AnalysisRequest(
        analysis_type=AnalysisType.MONTHLY_REPORT,
        wine_cellar_id=request.wine_cellar_id,
        user_id=user_id,
    )

    # Ejecutar
    return await _json_analysis(app_service, domain_request)


@router.post("/chat", response_model=AnalysisResponse)
async def chat(
    request: ChatRequest,
    user_id: int = Depends(get_current_user_id),
    wine_cellar_repo = Depends(get_wine_cellar_repository),
    space_repo = Depends(get_space_repository),
    app_service: AnalysisApplicationService = Depends(get_analysis_application_service),
) -> AnalysisResponse:
    # Validar propiedad
    await _verify_cellar_ownership_and_get(
        request.wine_cellar_id, user_id, wine_cellar_repo, space_repo
    )

    # Crear request de dominio
    domain_request = AnalysisRequest(
        analysis_type=AnalysisType.CHAT,
        wine_cellar_id=request.wine_cellar_id,
        user_query=request.user_query,
        user_id=user_id,
    )

    # Ejecutar
    return await _json_analysis(app_service, domain_request)
