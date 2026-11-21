from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator, model_validator

from app.profile.domain.policy import (
    normalize_email,
    normalize_full_name,
    normalize_language,
    normalize_username,
)


class ProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    full_name: str
    preferred_language: Literal["es", "en"]
    is_active: bool
    created_at: datetime
    updated_at: datetime | None = None
    last_login: datetime | None = None


class UpdateProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str | None = None
    email: EmailStr | None = None
    full_name: str | None = None
    preferred_language: str | None = None

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_username(value)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: EmailStr | None) -> str | None:
        if value is None:
            return None
        return normalize_email(str(value))

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_full_name(value)

    @field_validator("preferred_language")
    @classmethod
    def validate_language(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_language(value)

    @model_validator(mode="after")
    def validate_non_empty_and_non_null_fields(self):
        if not self.model_fields_set:
            raise ValueError("At least one profile field must be provided")
        for field_name in self.model_fields_set:
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: SecretStr = Field(..., min_length=1, max_length=128)
    new_password: SecretStr = Field(..., min_length=1, max_length=128)


class ChangePasswordResponse(BaseModel):
    message: str
    password_changed: Literal[True] = True
    sessions_revoked: Literal[False] = False
    security_notice: str
