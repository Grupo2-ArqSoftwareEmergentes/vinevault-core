"""
Dependencias globales de la aplicación.
"""
from typing import Dict, Any
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from .core.database import get_db
from .core.security import decode_token

# Repositorios Device
from .device.infrastructure.database.repositories import (
    AlertIncidentRepository,
    DeviceRepository,
    DeviceAssignmentRepository,
    DeviceCommandRepository,
    EdgeDeviceRepository,
    OrganizationRepository,
    SpaceRepository
)
from .shared.infrastructure.database.repositories import IntegrationOutboxRepository
from .wine_cellar.infrastructure.database.repositories import WineCellarRepository
from .wine_cellar.infrastructure.database.repositories import WineInventoryRepository
from .telemetry.infrastructure.database.repositories import TelemetryRepository

# Servicios Device
from .device.applications.command_handlers import (
    AlertIncidentServiceImpl,
    DeviceCommandServiceImpl,
    DeviceControlCommandServiceImpl,
    DevicePresenceCommandServiceImpl,
    DeviceThresholdCommandServiceImpl,
    OrganizationCommandServiceImpl,
    SpaceCommandServiceImpl
)
from .telemetry.applications.command_handlers import TelemetryCommandServiceImpl
from .device.applications.query_handlers import (
    DeviceQueryServiceImpl,
    DeviceStatusQueryServiceImpl,
    DeviceThresholdQueryServiceImpl,
    DeviceCommandQueryServiceImpl
)
from .device.applications.acl import DeviceContextFacadeImpl, ThresholdContextFacadeImpl
from .device.domain.models import Device, EdgeDevice
from .device.interfaces.acl import DeviceContextFacade, ThresholdContextFacade


def get_device_repositories(db: AsyncSession) -> Dict[str, Any]:
    """Obtener repositorios del módulo Device"""
    return {
        "device": DeviceRepository(db),
        "assignment": DeviceAssignmentRepository(db),
        "device_command": DeviceCommandRepository(db),
        "organization": OrganizationRepository(db),
        "space": SpaceRepository(db),
    }


def get_device_repository(db: AsyncSession = Depends(get_db)) -> DeviceRepository:
    return DeviceRepository(db)


def get_device_assignment_repository(db: AsyncSession = Depends(get_db)) -> DeviceAssignmentRepository:
    return DeviceAssignmentRepository(db)


def get_edge_device_repository(db: AsyncSession = Depends(get_db)) -> EdgeDeviceRepository:
    return EdgeDeviceRepository(db)


def get_device_command_repository(db: AsyncSession = Depends(get_db)) -> DeviceCommandRepository:
    return DeviceCommandRepository(db)


def get_alert_incident_repository(db: AsyncSession = Depends(get_db)) -> AlertIncidentRepository:
    return AlertIncidentRepository(db)


def get_integration_outbox_repository(db: AsyncSession = Depends(get_db)) -> IntegrationOutboxRepository:
    return IntegrationOutboxRepository(db)


def get_organization_repository(db: AsyncSession = Depends(get_db)) -> OrganizationRepository:
    return OrganizationRepository(db)


def get_space_repository(db: AsyncSession = Depends(get_db)) -> SpaceRepository:
    return SpaceRepository(db)


def get_space_creation_service(db: AsyncSession = Depends(get_db)):
    from .device.applications.personal_space_service import PersonalSpaceService
    from .shared.infrastructure.database.space_creation_unit_of_work import SpaceCreationUnitOfWork

    return PersonalSpaceService(SpaceCreationUnitOfWork(db))


def get_space_deletion_service(db: AsyncSession = Depends(get_db)):
    from .device.applications.space_deletion_service import SpaceDeletionService
    from .shared.infrastructure.database.space_deletion_unit_of_work import SpaceDeletionUnitOfWork

    return SpaceDeletionService(SpaceDeletionUnitOfWork(db))


def get_wine_cellar_repository(db: AsyncSession = Depends(get_db)) -> WineCellarRepository:
    return WineCellarRepository(db)


def get_wine_inventory_repository(db: AsyncSession = Depends(get_db)) -> WineInventoryRepository:
    return WineInventoryRepository(db)


def get_telemetry_repository(db: AsyncSession = Depends(get_db)) -> TelemetryRepository:
    return TelemetryRepository(db)


def get_device_command_service(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> DeviceCommandServiceImpl:
    """Obtener servicio de comandos de Device"""
    repos = get_device_repositories(db)
    device_event_publisher = None
    if request is not None:
        device_event_publisher = getattr(request.app.state, "device_event_publisher", None)
    return DeviceCommandServiceImpl(
        device_repo=repos["device"],
        assignment_repo=repos["assignment"],
        space_repo=repos["space"],
        device_command_repo=repos["device_command"],
        device_event_publisher=device_event_publisher,
    )


def get_device_query_service(
    db: AsyncSession = Depends(get_db),
) -> DeviceQueryServiceImpl:
    """Obtener servicio de queries de Device"""
    repos = get_device_repositories(db)
    return DeviceQueryServiceImpl(
        device_repo=repos["device"],
        assignment_repo=repos["assignment"],
        organization_repo=repos["organization"],
        space_repo=repos["space"],
    )


def get_device_control_command_service(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> DeviceControlCommandServiceImpl:
    """Obtener servicio de comandos de control de Device"""
    repos = get_device_repositories(db)
    device_event_publisher = None
    if request is not None:
        device_event_publisher = getattr(request.app.state, "device_event_publisher", None)
    return DeviceControlCommandServiceImpl(
        assignment_repo=repos["assignment"],
        device_command_repo=repos["device_command"],
        device_event_publisher=device_event_publisher,
    )


def get_device_presence_command_service(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> DevicePresenceCommandServiceImpl:
    """Obtener servicio de presencia de Device."""
    repos = get_device_repositories(db)
    device_event_publisher = None
    if request is not None:
        device_event_publisher = getattr(request.app.state, "device_event_publisher", None)
    return DevicePresenceCommandServiceImpl(
        device_repo=repos["device"],
        assignment_repo=repos["assignment"],
        device_event_publisher=device_event_publisher,
    )


def get_device_threshold_command_service(
    db: AsyncSession = Depends(get_db),
) -> DeviceThresholdCommandServiceImpl:
    """Obtener servicio de comandos de thresholds"""
    repos = get_device_repositories(db)
    return DeviceThresholdCommandServiceImpl(
        assignment_repo=repos["assignment"],
    )


def get_device_threshold_query_service(
    db: AsyncSession = Depends(get_db),
) -> DeviceThresholdQueryServiceImpl:
    """Obtener servicio de queries de thresholds"""
    repos = get_device_repositories(db)
    return DeviceThresholdQueryServiceImpl(
        assignment_repo=repos["assignment"],
    )


def get_organization_command_service(
    db: AsyncSession = Depends(get_db),
) -> OrganizationCommandServiceImpl:
    """Obtener servicio de comandos de Organization"""
    repos = get_device_repositories(db)
    return OrganizationCommandServiceImpl(
        organization_repo=repos["organization"],
        space_repo=repos["space"],
        assignment_repo=repos["assignment"],
    )


def get_space_command_service(
    db: AsyncSession = Depends(get_db),
) -> SpaceCommandServiceImpl:
    """Obtener servicio de comandos de Space"""
    repos = get_device_repositories(db)
    return SpaceCommandServiceImpl(
        space_repo=repos["space"],
        organization_repo=repos["organization"],
        assignment_repo=repos["assignment"],
    )


def get_telemetry_command_service(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TelemetryCommandServiceImpl:
    repos = get_device_repositories(db)
    telemetry_repo = get_telemetry_repository(db)
    alert_incident_repo = get_alert_incident_repository(db)
    outbox_repo = get_integration_outbox_repository(db)
    device_event_publisher = None
    alert_incident_service = None
    if request is not None:
        device_event_publisher = getattr(request.app.state, "device_event_publisher", None)
        alert_incident_service = getattr(request.app.state, "alert_incident_service", None)
    if alert_incident_service is None:
        alert_incident_service = AlertIncidentServiceImpl(
            assignment_repo=repos["assignment"],
            alert_incident_repo=alert_incident_repo,
            outbox_repo=outbox_repo,
        )
    return TelemetryCommandServiceImpl(
        device_repo=repos["device"],
        assignment_repo=repos["assignment"],
        telemetry_repo=telemetry_repo,
        device_event_publisher=device_event_publisher,
        alert_incident_service=alert_incident_service,
    )


def get_alert_incident_service(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AlertIncidentServiceImpl:
    repos = get_device_repositories(db)
    alert_incident_repo = get_alert_incident_repository(db)
    outbox_repo = get_integration_outbox_repository(db)
    return AlertIncidentServiceImpl(
        assignment_repo=repos["assignment"],
        alert_incident_repo=alert_incident_repo,
        outbox_repo=outbox_repo,
    )


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer()),
) -> int:
    """
    Extraer el ID del usuario del token JWT.
    """
    try:
        token = credentials.credentials
        payload = decode_token(token)
        user_id = payload.get("sub") or payload.get("user_id")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing subject",
            )
        return int(user_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid user ID format: {str(e)}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid authentication credentials: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_current_user_id_optional(
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer(auto_error=False)),
) -> int | None:
    """
    Extraer el ID del usuario del token JWT (opcional).
    """
    if credentials is None:
        return None
    
    try:
        token = credentials.credentials
        payload = decode_token(token)
        user_id = payload.get("sub") or payload.get("user_id")
        if user_id is not None:
            return int(user_id)
    except Exception:
        pass
    return None


async def get_current_edge_device(
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer(auto_error=False)),
    edge_device_repo: EdgeDeviceRepository = Depends(get_edge_device_repository),
) -> EdgeDevice:
    """
    Authenticate an edge caller using its own API key.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing edge credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    edge_device = await edge_device_repo.find_by_api_key(credentials.credentials)
    if edge_device is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid edge credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not edge_device.active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Edge device is disabled",
        )
    return edge_device


def get_device_context_facade(
    device_query_service: DeviceQueryServiceImpl = Depends(get_device_query_service),
) -> DeviceContextFacade:
    """Obtener facade de contexto de Device"""
    return DeviceContextFacadeImpl(device_query_service)


def get_threshold_context_facade(
    threshold_query_service: DeviceThresholdQueryServiceImpl = Depends(get_device_threshold_query_service),
    db: AsyncSession = Depends(get_db),
) -> ThresholdContextFacade:
    """Obtener facade de contexto de Threshold"""
    return ThresholdContextFacadeImpl(
        threshold_query_service=threshold_query_service,
        assignment_repo=get_device_repositories(db)["assignment"],
    )


# -------------------------------------------------------------
# DEPENDENCIAS DEL MÓDULO INVENTORY INTELLIGENCE (AI)
# -------------------------------------------------------------
from .inventory_intelligence.domain.services.gemini_service import GeminiService
from .inventory_intelligence.interfaces.acl import InventoryDataFacade
from .inventory_intelligence.applications.acl import InventoryDataFacadeImpl
from .inventory_intelligence.applications.analysis_application_service import AnalysisApplicationService

from .inventory_intelligence.infrastructure.gemini.gemini_client import GeminiClientImpl


def get_gemini_client() -> GeminiService:
    """The adapter initializes Google's SDK only for a nonempty inventory."""
    return GeminiClientImpl()


def get_inventory_data_facade(
    db: AsyncSession = Depends(get_db),
    device_query_service: DeviceQueryServiceImpl = Depends(get_device_query_service),
) -> InventoryDataFacade:
    """Obtener facade del Anti-Corruption Layer (ACL) para recolectar datos"""
    return InventoryDataFacadeImpl(
        wine_cellar_repo=get_wine_cellar_repository(db),
        wine_inventory_repo=get_wine_inventory_repository(db),
        device_context_facade=get_device_context_facade(device_query_service),
    )


def get_analysis_application_service(
    gemini_service: GeminiService = Depends(get_gemini_client),
    inventory_data_facade: InventoryDataFacade = Depends(get_inventory_data_facade),
) -> AnalysisApplicationService:
    """Obtener el caso de uso/servicio de aplicación orquestador de análisis de IA"""
    return AnalysisApplicationService(
        gemini_service=gemini_service,
        inventory_data_facade=inventory_data_facade,
    )
