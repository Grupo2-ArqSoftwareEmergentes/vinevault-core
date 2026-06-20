from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List
from uuid import UUID

from ..resources import (
    PairDeviceRequest, ClaimDeviceRequest, DeviceResponse,
    DevicePairingResource, UpdateDeviceNameRequest, DeviceStatusResponse,
    DeviceListResponse, CreateDeviceCommandRequest, DeviceCommandResponse
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
)


router = APIRouter(prefix="/api/v1/devices", tags=["Devices"])


@router.get("")
async def list_devices(
    space_id: UUID = Query(..., description="Space to filter devices by"),
    page: int = Query(0, ge=0),
    size: int = Query(20, ge=1),
    user_id: int = Depends(get_current_user_id),
    assignment_repo = Depends(get_device_assignment_repository),
    space_repo = Depends(get_space_repository),
) -> DeviceListResponse:
    space = await space_repo.find_by_id(space_id)
    if not space:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Space not found")
    if space.owner_user_id.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Space does not belong to user")

    assignments, total = await assignment_repo.find_by_space_id(space_id, page=page, size=size)
    items = [DeviceResponse.from_assignment(assignment) for assignment in assignments]
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
) -> DeviceResponse:
    """Claim a device into a user-owned space"""
    try:
        command = ClaimDeviceCommand(
            claim_token=request.claim_token,
            space_id=request.space_id,
            user_id=user_id
        )
        assignment = await service.handle_claim_device(command)
        return DeviceResponse.from_assignment(assignment)
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
) -> DeviceResponse:
    """Get device by ID"""
    assignment = await query_service.find_assignment_by_device_id(device_id)
    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    return DeviceResponse.from_assignment(assignment)


@router.get("/{device_id}/status")
async def get_device_status(
    device_id: UUID,
    user_id: int = Depends(get_current_user_id),
    query_service: DeviceQueryServiceImpl = Depends(get_device_query_service),
) -> DeviceStatusResponse:
    """Get current device status"""
    assignment = await query_service.find_assignment_by_device_id(device_id)
    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    
    if assignment.owner_user_id is None or assignment.owner_user_id.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Device does not belong to user")
    
    return DeviceStatusResponse(
        device_id=assignment.device.id,
        status=assignment.status,
        last_seen_at=assignment.last_seen_at
    )


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
    if assignment.owner_user_id is None or assignment.owner_user_id.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Device does not belong to user")

    commands = await command_repo.find_all_by_device_id(device_id)
    return [DeviceCommandResponse.from_domain(command) for command in commands]


@router.post("/{device_id}/commands", status_code=status.HTTP_201_CREATED)
async def create_device_command(
    device_id: UUID,
    request: CreateDeviceCommandRequest,
    user_id: int = Depends(get_current_user_id),
    assignment_repo = Depends(get_device_assignment_repository),
    command_repo = Depends(get_device_command_repository),
) -> DeviceCommandResponse:
    assignment = await assignment_repo.find_by_device_id(device_id)
    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    if assignment.owner_user_id is None or assignment.owner_user_id.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Device does not belong to user")

    command = DeviceCommand(
        device=assignment.device,
        type=request.type,
        payload=request.payload,
    )
    saved = await command_repo.save(command)
    return DeviceCommandResponse.from_domain(saved)
