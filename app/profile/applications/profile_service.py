from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_password_hash, verify_password
from app.iam.models import User
from app.profile.domain.errors import ProfileError
from app.profile.domain.policy import validate_password_policy
from app.profile.infrastructure.database.profile_repository import ProfileRepository


def _safe_verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return verify_password(plain_password, hashed_password)
    except ValueError:
        return False


class ProfileService:
    """Application service for authenticated user profile and credentials."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repository = ProfileRepository(session)

    async def get_profile(self, user_id: int) -> User:
        user = await self.repository.get_by_id(user_id)
        if user is None or not user.is_active:
            raise ProfileError("INVALID_USER", "Invalid or inactive user", 401)
        return user

    async def update_profile(
        self,
        user_id: int,
        *,
        fields_set: set[str],
        username: str | None = None,
        email: str | None = None,
        full_name: str | None = None,
        preferred_language: str | None = None,
    ) -> User:
        if not fields_set:
            raise ProfileError("EMPTY_UPDATE", "At least one profile field must be provided", 422)
        try:
            user = await self.repository.lock_by_id(user_id)
            if user is None or not user.is_active:
                raise ProfileError("INVALID_USER", "Invalid or inactive user", 401)

            if "username" in fields_set:
                assert username is not None
                if await self.repository.username_taken(username, exclude_user_id=user_id):
                    raise ProfileError("USERNAME_TAKEN", "Username is already in use", 409)
                user.username = username

            if "email" in fields_set:
                assert email is not None
                if await self.repository.email_taken(email, exclude_user_id=user_id):
                    raise ProfileError("EMAIL_TAKEN", "Email is already in use", 409)
                user.email = email

            if "full_name" in fields_set:
                assert full_name is not None
                user.full_name = full_name

            if "preferred_language" in fields_set:
                assert preferred_language is not None
                user.preferred_language = preferred_language

            user.updated_at = datetime.now(timezone.utc)
            await self.session.commit()
            await self.session.refresh(user)
            return user
        except IntegrityError as exc:
            await self.session.rollback()
            raise ProfileError("PROFILE_CONFLICT", "Username or email is already in use", 409) from exc
        except Exception:
            await self.session.rollback()
            raise

    async def change_password(
        self,
        user_id: int,
        *,
        current_password: str,
        new_password: str,
    ) -> dict:
        try:
            validate_password_policy(new_password)
        except ValueError as exc:
            raise ProfileError("INVALID_PASSWORD_POLICY", str(exc), 422) from exc
        try:
            user = await self.repository.lock_by_id(user_id)
            if user is None or not user.is_active:
                raise ProfileError("INVALID_USER", "Invalid or inactive user", 401)

            if not _safe_verify_password(current_password, user.hashed_password):
                raise ProfileError("INVALID_CURRENT_PASSWORD", "Current password is incorrect", 401)

            if new_password == current_password:
                raise ProfileError("PASSWORD_UNCHANGED", "New password must be different from the current password", 422)

            user.hashed_password = get_password_hash(new_password)
            user.updated_at = datetime.now(timezone.utc)
            await self.session.commit()
            return {
                "message": "Password updated successfully",
                "password_changed": True,
                "sessions_revoked": False,
                "security_notice": (
                    "Existing stateless JWT tokens remain valid until expiration; "
                    "sign in again on other devices if you suspect unauthorized access."
                ),
            }
        except Exception:
            await self.session.rollback()
            raise
