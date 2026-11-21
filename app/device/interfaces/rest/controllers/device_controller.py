from fastapi import APIRouter, Depends, HTTPException, Request, status, Query
from typing import List
from uuid import UUID

from ..resources import (
    PairDeviceRequest, ClaimDeviceRequest, DeviceResponse,
    DevicePairingResource, UpdateDeviceNameRequest, DeviceStatusResponse,
    DeviceListResponse, CreateDeviceCommandRequest, DeviceCommandResponse,
)
from app.device.domain.commands import (
    PairDeviceCommand, ClaimDeviceCommand, ResetDeviceAssignmentCommand,
    UpdateDeviceNameCommand
)
from app.device.domain.models import DeviceCommand
from app.device.applications.command_handlers import DeviceCommandServiceImpl, IllegalStateError
from app.device.applications.query_handlers import DeviceQueryServiceImpl
from app.dependencies import (
    get_device_command_service,
    get_device_query_service,
    get_current_user_id,
    get_device_assignment_repository,
    get_space_repository,
    get_device_command_repository,
    get_telemetry_repository,
    get_device_cellar_acl,
)
from app.telemetry.interfaces.rest.resources import TelemetryRecordResponse
from app.wine_cellar.interfaces.acl import CellarDeviceLinkError


router = APIRouter(prefix="/api/v1/devices", tags=["Devices"])


@router.get("")
async def list_devices(
    space_id: UUID = Query(..., description="Space to filter devices by"),
    page: int = Query(0, ge=0),
    size: int = Query(20, ge=1),
    user_id: int = Depends(get_current_user_id),
    assignment_repo = Depends(get_device_assignment_repository),
    space_repo = Depends(get_space_repository),
    telemetry_repo = Depends(get_telemetry_repository),
    cellar_acl = Depends(get_device_cellar_acl),
) -> DeviceListResponse:
    space = await space_repo.find_by_id(space_id)
    if not space:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Space not found")

    assignments, total = await assignment_repo.find_by_space_id(space_id, page=page, size=size)
    activity = await telemetry_repo.latest_activity([assignment.id for assignment in assignments])
    links = await cellar_acl.links_for_devices([assignment.device.id for assignment in assignments], space_id)
    items = [DeviceResponse.from_assignment(assignment, activity.get(assignment.id), cellar=links.get(assignment.device.id)) for assignment in assignments]
    return DeviceListResponse(items=items, page=page, size=size, total=total)


@router.post("/pair", status_code=status.HTTP_201_CREATED)
async def pair_device(
    request: PairDeviceRequest,
    service: DeviceCommandServiceImpl = Depends(get_device_command_service),
) -> DevicePairingResource:
    """Pair a physical device"""
    try:
        command = PairDeviceCommand(hardware_id=request.hardware_id)
        assignment = await service.handle_pair_device(command)
        
        return DevicePairingResource(
            device_id=assignment.device.id,
            claim_token=assignment.claim_token.value if assignment.claim_token else None
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except IllegalStateError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.post("/claim")
async def claim_device(
    request: ClaimDeviceRequest,
    user_id: int = Depends(get_current_user_id),
    service: DeviceCommandServiceImpl = Depends(get_device_command_service),
    cellar_acl = Depends(get_device_cellar_acl),
) -> DeviceResponse:
    """Claim a device into a user-owned space"""
    try:
        command = ClaimDeviceCommand(
            claim_token=request.claim_token,
            space_id=request.space_id,
            user_id=user_id,
            cellar_id=request.cellar_id,
        )
        assignment = await service.handle_claim_device(command)
        links = await cellar_acl.links_for_devices([assignment.device.id], assignment.space_id)
        return DeviceResponse.from_assignment(assignment, cellar=links.get(assignment.device.id))
    except CellarDeviceLinkError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except IllegalStateError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.get("/{device_id}")
async def get_device(
    device_id: UUID,
    query_service: DeviceQueryServiceImpl = Depends(get_device_query_service),
    telemetry_repo = Depends(get_telemetry_repository),
    cellar_acl = Depends(get_device_cellar_acl),
) -> DeviceResponse:
    """Get device by ID"""
    assignment = await query_service.find_assignment_by_device_id(device_id)
    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    activity = await telemetry_repo.latest_activity([assignment.id])
    links = await cellar_acl.links_for_devices([assignment.device.id], assignment.space_id)
    return DeviceResponse.from_assignment(assignment, activity.get(assignment.id), cellar=links.get(assignment.device.id))


@router.get("/{device_id}/status")
async def get_device_status(
    device_id: UUID,
    user_id: int = Depends(get_current_user_id),
    query_service: DeviceQueryServiceImpl = Depends(get_device_query_service),
    telemetry_repo = Depends(get_telemetry_repository),
) -> DeviceStatusResponse:
    """Get current device status"""
    assignment = await query_service.find_assignment_by_device_id(device_id)
    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    
    
    activity = await telemetry_repo.latest_activity([assignment.id])
    return DeviceStatusResponse.from_assignment(assignment, activity.get(assignment.id))


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device(
    device_id: UUID,
    user_id: int = Depends(get_current_user_id),
    service: DeviceCommandServiceImpl = Depends(get_device_command_service),
):
    """Reset a device assignment for reconfiguration"""
    try:
        command = ResetDeviceAssignmentCommand(device_id=device_id, user_id=user_id)
        await service.handle_reset_device_assignment(command)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.patch("/{device_id}")
@router.patch("/{device_id}/name")
async def update_device_name(
    device_id: UUID,
    request: UpdateDeviceNameRequest,
    user_id: int = Depends(get_current_user_id),
    service: DeviceCommandServiceImpl = Depends(get_device_command_service),
):
    """Update device display name"""
    try:
        command = UpdateDeviceNameCommand(device_id=device_id, name=request.name, user_id=user_id)
        await service.handle_update_device_name(command)
        return {"status": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.get("/{device_id}/commands/latest")
async def get_latest_device_command(
    device_id: UUID,
    user_id: int = Depends(get_current_user_id),
    assignment_repo = Depends(get_device_assignment_repository),
    command_repo = Depends(get_device_command_repository),
) -> DeviceCommandResponse:
    assignment = await assignment_repo.find_by_device_id(device_id)
    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")

    commands = await command_repo.find_all_by_device_id(device_id)
    if not commands:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device command not found")
    return DeviceCommandResponse.from_domain(commands[0])


@router.get("/{device_id}/commands/{command_id}")
async def get_device_command(
    device_id: UUID,
    command_id: UUID,
    user_id: int = Depends(get_current_user_id),
    assignment_repo = Depends(get_device_assignment_repository),
    command_repo = Depends(get_device_command_repository),
) -> DeviceCommandResponse:
    assignment = await assignment_repo.find_by_device_id(device_id)
    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")

    command = await command_repo.find_by_id(command_id)
    if not command or command.device.id != device_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device command not found")
    return DeviceCommandResponse.from_domain(command)


@router.get("/{device_id}/commands")
async def list_device_commands(
    device_id: UUID,
    user_id: int = Depends(get_current_user_id),
    assignment_repo = Depends(get_device_assignment_repository),
    command_repo = Depends(get_device_command_repository),
) -> List[DeviceCommandResponse]:
    assignment = await assignment_repo.find_by_device_id(device_id)
    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")

    commands = await command_repo.find_all_by_device_id(device_id)
    return [DeviceCommandResponse.from_domain(command) for command in commands]


@router.get("/{device_id}/telemetry")
async def list_device_telemetry(
    device_id: UUID,
    limit: int = Query(50, ge=1, le=500),
    user_id: int = Depends(get_current_user_id),
    assignment_repo = Depends(get_device_assignment_repository),
    telemetry_repo = Depends(get_telemetry_repository),
) -> List[TelemetryRecordResponse]:
    assignment = await assignment_repo.find_by_device_id(device_id)
    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")

    telemetry_records = await telemetry_repo.find_all_by_device_id(device_id)
    return [TelemetryRecordResponse.from_domain(record) for record in telemetry_records[:limit]]


@router.post("/{device_id}/commands", status_code=status.HTTP_201_CREATED)
async def create_device_command(
    device_id: UUID,
    request: CreateDeviceCommandRequest,
    http_request: Request,
    user_id: int = Depends(get_current_user_id),
    assignment_repo = Depends(get_device_assignment_repository),
    command_repo = Depends(get_device_command_repository),
) -> DeviceCommandResponse:
    assignment = await assignment_repo.find_by_device_id(device_id, for_update=True)
    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")

    command = DeviceCommand(
        device=assignment.device,
        type=request.type,
        payload=request.payload,
    )
    assignment.request_power(request.type.value)
    if request.type.value in ('STANDBY', 'WAKE'):
        await assignment_repo.save(assignment, auto_commit=False)
    saved = await command_repo.save(command)
    device_event_publisher = getattr(http_request.app.state, "device_event_publisher", None)
    if device_event_publisher is not None:
        await device_event_publisher.publish_device_command_pending(saved)
    return DeviceCommandResponse.from_domain(saved)
