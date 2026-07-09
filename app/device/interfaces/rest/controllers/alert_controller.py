from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import (
    get_alert_incident_repository,
    get_current_user_id,
    get_device_assignment_repository,
)
from app.device.infrastructure.database.repositories import AlertIncidentRepository, DeviceAssignmentRepository
from ..resources import AlertIncidentResponse


router = APIRouter(prefix="/api/v1/devices", tags=["Device Alerts"])


@router.get("/{device_id}/alerts", summary="List alert incidents for a device")
async def list_device_alerts(
    device_id: UUID,
    active_only: bool = Query(False),
    user_id: int = Depends(get_current_user_id),
    assignment_repo: DeviceAssignmentRepository = Depends(get_device_assignment_repository),
    alert_repo: AlertIncidentRepository = Depends(get_alert_incident_repository),
) -> List[AlertIncidentResponse]:
    assignment = await assignment_repo.find_by_device_id(device_id)
    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    if assignment.owner_user_id is None or assignment.owner_user_id.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Device does not belong to user")

    alerts = await (
        alert_repo.find_active_by_device_id(device_id)
        if active_only
        else alert_repo.find_all_by_device_id(device_id)
    )
    return [AlertIncidentResponse.from_domain(alert) for alert in alerts]
