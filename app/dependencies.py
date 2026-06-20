"""
Dependencias globales de la aplicación.
"""
from typing import Dict, Any
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from .core.database import get_db
from .core.security import decode_token
from .core.config import settings

# Repositorios Device
from .device.infrastructure.database.repositories import (
    DeviceRepository,
    DeviceAssignmentRepository,
    DeviceCommandRepository,
    OrganizationRepository,
    SpaceRepository
)

# Servicios Device
from .device.applications.command_handlers import (
    DeviceCommandServiceImpl,
    DeviceControlCommandServiceImpl,
    DevicePresenceCommandServiceImpl,
    DeviceThresholdCommandServiceImpl,
    OrganizationCommandServiceImpl,
    SpaceCommandServiceImpl
)
from .device.applications.query_handlers import (
    DeviceQueryServiceImpl,
    DeviceStatusQueryServiceImpl,
    DeviceThresholdQueryServiceImpl,
    DeviceCommandQueryServiceImpl
)
from .device.applications.acl import DeviceContextFacadeImpl, ThresholdContextFacadeImpl
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


def get_device_command_repository(db: AsyncSession = Depends(get_db)) -> DeviceCommandRepository:
    return DeviceCommandRepository(db)


def get_organization_repository(db: AsyncSession = Depends(get_db)) -> OrganizationRepository:
    return OrganizationRepository(db)


def get_space_repository(db: AsyncSession = Depends(get_db)) -> SpaceRepository:
    return SpaceRepository(db)


def get_device_command_service(
    db: AsyncSession = Depends(get_db),
) -> DeviceCommandServiceImpl:
    """Obtener servicio de comandos de Device"""
    repos = get_device_repositories(db)
    return DeviceCommandServiceImpl(
        device_repo=repos["device"],
        assignment_repo=repos["assignment"],
        space_repo=repos["space"],
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
    db: AsyncSession = Depends(get_db),
) -> DeviceControlCommandServiceImpl:
    """Obtener servicio de comandos de control de Device"""
    repos = get_device_repositories(db)
    return DeviceControlCommandServiceImpl(
        assignment_repo=repos["assignment"],
        device_command_repo=repos["device_command"],
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
