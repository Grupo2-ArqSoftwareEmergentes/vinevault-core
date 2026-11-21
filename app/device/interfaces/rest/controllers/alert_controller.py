from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.dependencies import (
    get_alert_incident_repository,
    get_current_user_id,
    get_device_assignment_repository,
    get_device_cellar_acl,
)
from app.device.infrastructure.database.repositories import AlertIncidentRepository, DeviceAssignmentRepository
from ..resources import AlertIncidentResponse


router = APIRouter(prefix="/api/v1", tags=["Device Alerts"])


@router.get("/alerts", summary="List alert incidents for every device in a space")
async def list_space_alerts(
    request: Request,
    space_id: UUID = Query(...),
    active_only: bool = Query(False),
    user_id: int = Depends(get_current_user_id),
    alert_repo: AlertIncidentRepository = Depends(get_alert_incident_repository),
    cellar_acl = Depends(get_device_cellar_acl),
) -> List[AlertIncidentResponse]:
    incidents = await alert_repo.find_by_space_id(space_id, active_only=active_only)
    links = await cellar_acl.links_for_devices(list({incident.device.id for incident in incidents}), space_id)
    language = "es" if request.headers.get("accept-language", "en").lower().startswith("es") else "en"
    return [AlertIncidentResponse.from_domain(incident, cellar=links.get(incident.device.id), language=language) for incident in incidents]


@router.get("/devices/{device_id}/alerts", summary="List alert incidents for a device")
async def list_device_alerts(
    request: Request,
    device_id: UUID,
    active_only: bool = Query(False),
    user_id: int = Depends(get_current_user_id),
    assignment_repo: DeviceAssignmentRepository = Depends(get_device_assignment_repository),
    alert_repo: AlertIncidentRepository = Depends(get_alert_incident_repository),
    cellar_acl = Depends(get_device_cellar_acl),
) -> List[AlertIncidentResponse]:
    assignment = await assignment_repo.find_by_device_id(device_id)
    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")

    alerts = await (
        alert_repo.find_active_by_device_id(device_id)
        if active_only
        else alert_repo.find_all_by_device_id(device_id)
    )
    links = await cellar_acl.links_for_devices([device_id], assignment.space_id)
    language = "es" if request.headers.get("accept-language", "en").lower().startswith("es") else "en"
    return [AlertIncidentResponse.from_domain(alert, cellar=links.get(device_id), language=language) for alert in alerts
            if alert.space_id == assignment.space_id and alert.assignment_id == assignment.id]
