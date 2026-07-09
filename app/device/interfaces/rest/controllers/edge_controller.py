from fastapi import APIRouter, Depends, HTTPException, Query, status
from typing import Dict
from uuid import UUID

from app.dependencies import (
    get_current_edge_device,
    get_device_assignment_repository,
    get_device_control_command_service,
    get_device_presence_command_service,
    get_device_repository,
)
from app.device.domain.commands import AcknowledgeDeviceCommand, UpdateDevicePresenceStatusCommand
from app.device.domain.models import EdgeDevice, DeviceAssignment
from app.device.domain.models.value_objects import HardwareId
from ..resources import (
    AcknowledgeDeviceCommandRequest,
    DeviceCommandResponse,
    DeviceStatusResponse,
    EdgeDeviceListResponse,
    EdgeDeviceResponse,
    UpdateDevicePresenceStatusRequest,
)


router = APIRouter(prefix="/api/v1/edges", tags=["Edge Inventory"])


@router.get("/devices", summary="List all devices for an authenticated edge")
async def list_edge_devices(
    page: int = Query(0, ge=0),
    size: int = Query(50, ge=1, le=500),
    _edge_device: EdgeDevice = Depends(get_current_edge_device),
    device_repo = Depends(get_device_repository),
    assignment_repo = Depends(get_device_assignment_repository),
) -> EdgeDeviceListResponse:
    devices, total = await device_repo.find_all(page=page, size=size)
    assignments = await assignment_repo.find_all_by_device_ids([device.id for device in devices])
    assignment_by_device_id: Dict[UUID, DeviceAssignment] = {assignment.device.id: assignment for assignment in assignments}

    items = [
        EdgeDeviceResponse.from_device_and_assignment(
            device=device,
            assignment=assignment_by_device_id.get(device.id),
        )
        for device in devices
    ]
    return EdgeDeviceListResponse(items=items, page=page, size=size, total=total)


@router.post("/devices/presence", summary="Report presence for an edge device")
async def report_device_presence(
    request: UpdateDevicePresenceStatusRequest,
    _edge_device: EdgeDevice = Depends(get_current_edge_device),
    service = Depends(get_device_presence_command_service),
) -> DeviceStatusResponse:
    try:
        command_data = {
            "device_id": request.device_id,
            "hardware_id": HardwareId(value=request.hardware_id) if request.hardware_id else None,
            "status": request.status,
        }
        if request.occurred_at is not None:
            command_data["occurred_at"] = request.occurred_at
        command = UpdateDevicePresenceStatusCommand(**command_data)
        assignment = await service.handle_update_device_presence_status(command)
        return DeviceStatusResponse(
            device_id=assignment.device.id,
            status=assignment.status,
            last_seen_at=assignment.last_seen_at,
        )
    except ValueError as exc:
        detail = str(exc)
        if detail == "Device assignment not found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


@router.post("/devices/commands/ack", summary="Acknowledge a command from the edge")
async def acknowledge_device_command(
    request: AcknowledgeDeviceCommandRequest,
    _edge_device: EdgeDevice = Depends(get_current_edge_device),
    service = Depends(get_device_control_command_service),
) -> DeviceCommandResponse:
    try:
        command_kwargs = {
            "device_id": request.device_id,
            "command_id": request.command_id,
            "status": request.status,
            "failure_reason": request.failure_reason,
        }
        if request.occurred_at is not None:
            command_kwargs["occurred_at"] = request.occurred_at
        command = AcknowledgeDeviceCommand(**command_kwargs)
        saved = await service.handle_acknowledge_device_command(command)
        return DeviceCommandResponse.from_domain(saved)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        detail = str(exc)
        if detail in {"Device assignment not found", "Device command not found"}:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
