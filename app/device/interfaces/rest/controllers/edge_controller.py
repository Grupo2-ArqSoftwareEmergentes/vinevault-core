from fastapi import APIRouter, Depends, Query
from typing import Dict
from uuid import UUID

from app.dependencies import (
    get_current_edge_device,
    get_device_assignment_repository,
    get_device_repository,
)
from app.device.domain.models import EdgeDevice, DeviceAssignment
from ..resources import EdgeDeviceListResponse, EdgeDeviceResponse


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
