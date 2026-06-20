import json
from decimal import Decimal
from uuid import UUID
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_current_user_id, get_device_assignment_repository
from app.device.domain.models.value_objects import MetricThreshold, DeviceMetricThresholdConfiguration
from ..resources import DeviceThresholdResponse, UpdateDeviceThresholdRequest


router = APIRouter(prefix="/api/v1/devices/{device_id}/thresholds", tags=["Device Thresholds"])


def _build_threshold_response(assignment, metric: MetricThreshold) -> DeviceThresholdResponse | None:
    config_json = assignment.find_configuration_value(f"threshold.{metric.value}")
    if not config_json:
        return None
    try:
        data = json.loads(config_json)
        config = DeviceMetricThresholdConfiguration(
            metric=metric,
            value=Decimal(str(data["value"])),
            enabled=data.get("enabled", True),
        )
        return DeviceThresholdResponse.from_config(config, assignment.device.id)
    except Exception:
        return None


@router.get("")
async def list_thresholds(
    device_id: UUID,
    user_id: int = Depends(get_current_user_id),
    assignment_repo = Depends(get_device_assignment_repository),
) -> List[DeviceThresholdResponse]:
    assignment = await assignment_repo.find_by_device_id(device_id)
    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    if assignment.owner_user_id is None or assignment.owner_user_id.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Device does not belong to user")

    thresholds = []
    for metric in MetricThreshold:
        threshold = _build_threshold_response(assignment, metric)
        if threshold:
            thresholds.append(threshold)
    return thresholds


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_threshold(
    device_id: UUID,
    request: UpdateDeviceThresholdRequest,
    user_id: int = Depends(get_current_user_id),
    assignment_repo = Depends(get_device_assignment_repository),
) -> DeviceThresholdResponse:
    assignment = await assignment_repo.find_by_device_id(device_id)
    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    if assignment.owner_user_id is None or assignment.owner_user_id.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Device does not belong to user")

    config = DeviceMetricThresholdConfiguration(
        metric=request.metric,
        value=request.value,
        enabled=request.enabled,
    )
    assignment.put_configuration_value(
        f"threshold.{request.metric.value}",
        json.dumps({"value": str(config.value), "enabled": config.enabled}),
    )
    await assignment_repo.save(assignment)
    response = _build_threshold_response(assignment, request.metric)
    if response is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unable to create threshold")
    return response


@router.patch("/{metric}")
async def update_threshold(
    device_id: UUID,
    metric: MetricThreshold,
    request: UpdateDeviceThresholdRequest,
    user_id: int = Depends(get_current_user_id),
    assignment_repo = Depends(get_device_assignment_repository),
) -> DeviceThresholdResponse:
    if request.metric != metric:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Metric in body does not match path")

    assignment = await assignment_repo.find_by_device_id(device_id)
    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    if assignment.owner_user_id is None or assignment.owner_user_id.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Device does not belong to user")

    assignment.put_configuration_value(
        f"threshold.{metric.value}",
        json.dumps({"value": str(request.value), "enabled": request.enabled}),
    )
    await assignment_repo.save(assignment)
    response = _build_threshold_response(assignment, metric)
    if response is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unable to update threshold")
    return response


@router.delete("/{metric}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_threshold(
    device_id: UUID,
    metric: MetricThreshold,
    user_id: int = Depends(get_current_user_id),
    assignment_repo = Depends(get_device_assignment_repository),
):
    assignment = await assignment_repo.find_by_device_id(device_id)
    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    if assignment.owner_user_id is None or assignment.owner_user_id.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Device does not belong to user")

    assignment.remove_configuration_value(f"threshold.{metric.value}")
    await assignment_repo.save(assignment)
