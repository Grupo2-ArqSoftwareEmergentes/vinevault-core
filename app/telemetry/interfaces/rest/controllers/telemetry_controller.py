from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_current_edge_device, get_telemetry_command_service
from app.device.domain.models import EdgeDevice
from app.telemetry.applications.command_handlers import TelemetryCommandServiceImpl
from app.telemetry.domain.commands import RecordDeviceTelemetryCommand
from ..resources import RecordDeviceTelemetryRequest, TelemetryRecordResponse


router = APIRouter(prefix="/api/v1/edges", tags=["Telemetry"])


@router.post("/devices/telemetry", status_code=status.HTTP_201_CREATED)
async def record_device_telemetry(
    request: RecordDeviceTelemetryRequest,
    edge_device: EdgeDevice = Depends(get_current_edge_device),
    service: TelemetryCommandServiceImpl = Depends(get_telemetry_command_service),
) -> TelemetryRecordResponse:
    try:
        command = RecordDeviceTelemetryCommand(
            device_id=request.device_id,
            hardware_id=request.hardware_id,
            payload=request.payload,
            occurred_at=request.occurred_at,
            source=request.source,
        )
        record = await service.handle_record_device_telemetry(command)
        return TelemetryRecordResponse.from_domain(record)
    except ValueError as e:
        detail = str(e)
        if detail == "Device not found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
