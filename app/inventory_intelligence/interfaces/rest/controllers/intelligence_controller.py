from fastapi import APIRouter, Depends, HTTPException, status
from uuid import UUID

from app.dependencies import (
    get_current_user_id,
    get_wine_cellar_repository,
    get_space_repository,
)
from app.inventory_intelligence.domain.models.analysis_type import AnalysisType
from app.inventory_intelligence.domain.models.analysis_request import AnalysisRequest
from app.inventory_intelligence.interfaces.rest.resources import (
    AnalyzeStockRequest,
    RecommendPurchasesRequest,
    MonthlyReportRequest,
    ChatRequest,
    AnalysisResponse,
)
# Nota: get_analysis_application_service se registrará en app/dependencies.py
from app.dependencies import get_analysis_application_service
from app.inventory_intelligence.applications.analysis_application_service import AnalysisApplicationService

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


@router.post("/analyze-stock", response_model=AnalysisResponse)
async def analyze_stock(
    request: AnalyzeStockRequest,
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
        analysis_type=AnalysisType.STOCK_ANALYSIS,
        wine_cellar_id=request.wine_cellar_id,
        user_id=user_id,
    )

    # Ejecutar
    result = await app_service.execute_analysis(domain_request)
    return AnalysisResponse.from_domain(result)


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
    result = await app_service.execute_analysis(domain_request)
    return AnalysisResponse.from_domain(result)


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
    result = await app_service.execute_analysis(domain_request)
    return AnalysisResponse.from_domain(result)


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
    result = await app_service.execute_analysis(domain_request)
    return AnalysisResponse.from_domain(result)
