from datetime import timedelta
from typing import Optional
from . import models, schemas, crud
from ..core import security, config

async def authenticate_user(db, username: str, password: str) -> Optional[models.User]:
    user = await crud.get_user_by_username(db, username)
    if not user:
        return None
    if not security.verify_password(password, user.hashed_password):
        return None
    if not user.is_active:
        return None
    return user

def create_tokens(user: models.User) -> schemas.TokenResponse:
    # Access token (corto plazo)
    access_token_data = {"sub": str(user.id), "username": user.username, "user_id": user.id}
    access_token = security.create_access_token(access_token_data)
    
    # Refresh token (largo plazo)
    refresh_token_data = {"sub": str(user.id), "username": user.username, "user_id": user.id, "type": "refresh"}
    refresh_expires = timedelta(days=config.settings.REFRESH_TOKEN_EXPIRE_DAYS)
    refresh_token = security.create_access_token(refresh_token_data, refresh_expires)
    
    return schemas.TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=config.settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )
