"""Validation and normalization rules for user account profile and credentials."""

SUPPORTED_LANGUAGES: tuple[str, ...] = ("es", "en")
DEFAULT_LANGUAGE: str = "es"

MIN_USERNAME_LENGTH = 3
MAX_USERNAME_LENGTH = 50
MAX_EMAIL_LENGTH = 100
MAX_FULL_NAME_LENGTH = 255
MIN_PASSWORD_LENGTH = 6
MAX_PASSWORD_BYTES = 72


def normalize_language(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in SUPPORTED_LANGUAGES:
        supported = ", ".join(SUPPORTED_LANGUAGES)
        raise ValueError(f"Unsupported language. Supported values: {supported}")
    return normalized


def normalize_username(value: str) -> str:
    normalized = value.strip()
    if not (MIN_USERNAME_LENGTH <= len(normalized) <= MAX_USERNAME_LENGTH):
        raise ValueError(f"Username must be between {MIN_USERNAME_LENGTH} and {MAX_USERNAME_LENGTH} characters")
    if not normalized.isalnum():
        raise ValueError("Username must be alphanumeric")
    return normalized


def normalize_email(value: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) > MAX_EMAIL_LENGTH:
        raise ValueError(f"Email must be at most {MAX_EMAIL_LENGTH} characters")
    return normalized


def normalize_full_name(value: str) -> str:
    normalized = value.strip()
    if len(normalized) > MAX_FULL_NAME_LENGTH:
        raise ValueError(f"Full name must be at most {MAX_FULL_NAME_LENGTH} characters")
    return normalized


def validate_password_policy(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters long")
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError(f"Password must not exceed {MAX_PASSWORD_BYTES} UTF-8 bytes")
    return password
