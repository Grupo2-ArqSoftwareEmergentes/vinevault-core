from fastapi import APIRouter, Depends

from app.dependencies import get_profile_service
from app.profile.applications.profile_service import ProfileService
from ..resources.profile_resources import (
    ChangePasswordRequest,
    ChangePasswordResponse,
    ProfileResponse,
    UpdateProfileRequest,
)
from ..security import require_active_profile_user


router = APIRouter(prefix="/api/v1/profile", tags=["Profile"])


@router.get("", response_model=ProfileResponse)
async def get_profile(
    user_id: int = Depends(require_active_profile_user),
    service: ProfileService = Depends(get_profile_service),
):
    user = await service.get_profile(user_id)
    return ProfileResponse.model_validate(user)


@router.patch("", response_model=ProfileResponse)
async def update_profile(
    payload: UpdateProfileRequest,
    user_id: int = Depends(require_active_profile_user),
    service: ProfileService = Depends(get_profile_service),
):
    user = await service.update_profile(
        user_id,
        fields_set=set(payload.model_fields_set),
        username=payload.username,
        email=payload.email,
        full_name=payload.full_name,
        preferred_language=payload.preferred_language,
    )
    return ProfileResponse.model_validate(user)


@router.post("/change-password", response_model=ChangePasswordResponse)
async def change_password(
    payload: ChangePasswordRequest,
    user_id: int = Depends(require_active_profile_user),
    service: ProfileService = Depends(get_profile_service),
):
    return await service.change_password(
        user_id,
        current_password=payload.current_password.get_secret_value(),
        new_password=payload.new_password.get_secret_value(),
    )
