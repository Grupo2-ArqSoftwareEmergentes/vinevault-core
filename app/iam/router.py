from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from typing import List
from . import schemas, crud, auth, dependencies
from ..core.config import settings
from ..core.database import get_db

router = APIRouter(prefix="/api/v1/iam", tags=["IAM - Authentication"])

@router.post(
    "/register",
    response_model=schemas.UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar nuevo usuario"
)
def register(
    user: schemas.UserCreate,
    db: Session = Depends(get_db)
):
    # Verificar si el usuario ya existe
    if crud.get_user_by_username(db, user.username):
        raise HTTPException(status_code=400, detail="Username already registered")
    
    if crud.get_user_by_email(db, user.email):
        raise HTTPException(status_code=400, detail="Email already registered")
    
    return crud.create_user(db=db, user=user)

@router.post(
    "/login",
    response_model=schemas.TokenResponse,
    summary="Iniciar sesión"
)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    user = auth.authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Actualizar último login
    crud.update_last_login(db, user.id)
    
    # Generar tokens
    return auth.create_tokens(user)

@router.post(
    "/refresh",
    response_model=schemas.TokenResponse,
    summary="Renovar token de acceso"
)
def refresh_token(
    refresh_request: schemas.RefreshTokenRequest,
    db: Session = Depends(get_db)
):
    payload = auth.security.decode_token(refresh_request.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )
    
    user_id = payload.get("user_id")
    user = crud.get_user_by_id(db, user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive"
        )
    
    return auth.create_tokens(user)

@router.get(
    "/me",
    response_model=schemas.UserResponse,
    summary="Obtener perfil del usuario actual"
)
def get_me(
    current_user = Depends(dependencies.get_current_active_user)
):
    return current_user

@router.get(
    "/users",
    response_model=List[schemas.UserResponse],
    summary="Listar todos los usuarios (admin)"
)
def get_users(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user = Depends(dependencies.get_current_superuser)
):
    return crud.get_users(db, skip=skip, limit=limit)

@router.get(
    "/health",
    summary="Health check del modulo IAM"
)
def health_check():
    return {
        "status": "healthy",
        "service": settings.SERVICE_NAME,
        "module": "iam",
        "version": settings.SERVICE_VERSION,
    }
