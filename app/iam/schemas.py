from pydantic import BaseModel, EmailStr, Field, validator
from datetime import datetime
from typing import Optional

# Request schemas
class UserCreate(BaseModel):
    username: str | None = Field(default=None, min_length=3, max_length=50)
    full_name: str = Field(default="", max_length=255)
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=72)
    
    @validator('username')
    def username_alphanumeric(cls, v):
        if v is None:
            return v
        if not v.isalnum():
            raise ValueError('Username must be alphanumeric')
        return v

class UserLogin(BaseModel):
    username: str
    password: str

class RefreshTokenRequest(BaseModel):
    refresh_token: str

# Response schemas
class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    full_name: str
    extra_spaces_allowance: int
    is_active: bool
    is_superuser: bool
    created_at: datetime
    last_login: Optional[datetime] = None
    
    class Config:
        from_attributes = True

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int

class TokenData(BaseModel):
    username: Optional[str] = None
    user_id: Optional[int] = None
