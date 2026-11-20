import unittest

from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import ValidationError
from sqlalchemy import inspect, text, update
from sqlalchemy.exc import IntegrityError

from app.core.security import create_access_token, get_password_hash, verify_password
from app.iam.models import User
from app.profile.domain.policy import (
    DEFAULT_LANGUAGE,
    SUPPORTED_LANGUAGES,
    normalize_email,
    normalize_language,
    normalize_username,
    validate_password_policy,
)
from app.profile.interfaces.rest.resources.profile_resources import (
    ChangePasswordRequest,
    UpdateProfileRequest,
)
from test_personal_context import PostgresAPITestCase
from test_space_tenancy import upgrade_database


BASE = "/api/v1/profile"


class ProfileValidationTests(unittest.TestCase):
    def test_language_normalization_and_strict_allowlist(self):
        self.assertEqual(SUPPORTED_LANGUAGES, ("es", "en"))
        self.assertEqual(DEFAULT_LANGUAGE, "es")
        self.assertEqual(normalize_language("es"), "es")
        self.assertEqual(normalize_language(" EN "), "en")
        self.assertEqual(normalize_language("Es"), "es")
        for invalid in ("", " ", "fr", "pt", "es-PE", "en-US", "english"):
            with self.subTest(language=invalid), self.assertRaises(ValueError):
                normalize_language(invalid)

    def test_username_email_and_password_policy(self):
        self.assertEqual(normalize_username("  Alice01  "), "Alice01")
        self.assertEqual(normalize_email("  User.Name@Example.COM "), "user.name@example.com")
        for bad_username in ("ab", "a" * 51, "alice_01", "alice 01", ""):
            with self.subTest(username=bad_username), self.assertRaises(ValueError):
                normalize_username(bad_username)
        with self.assertRaises(ValueError):
            normalize_email(("a" * 95) + "@ex.co")
        self.assertEqual(validate_password_policy("secret1"), "secret1")
        for bad_password in ("", "12345", "a" * 73, "á" * 37):
            with self.subTest(password_len=len(bad_password)), self.assertRaises(ValueError):
                validate_password_policy(bad_password)

    def test_request_dtos_reject_empty_null_and_privileged_fields(self):
        with self.assertRaises(ValidationError):
            UpdateProfileRequest()
        for field in ("username", "email", "full_name", "preferred_language"):
            with self.subTest(null_field=field), self.assertRaises(ValidationError):
                UpdateProfileRequest(**{field: None})
        for extra in (
            {"is_superuser": True},
            {"is_active": False},
            {"extra_spaces_allowance": 99},
            {"hashed_password": "fake"},
            {"subscription_plan": "PRO"},
        ):
            with self.subTest(extra=extra), self.assertRaises(ValidationError):
                UpdateProfileRequest(preferred_language="en", **extra)
        with self.assertRaises(ValidationError):
            ChangePasswordRequest(current_password="", new_password="validpassword")
        with self.assertRaises(ValidationError):
            ChangePasswordRequest(current_password="oldpassword", new_password="validpassword", is_superuser=True)


class ProfileAPITests(PostgresAPITestCase):
    async def set_user_password(self, user_id: int, raw_password: str) -> str:
        hashed = get_password_hash(raw_password)
        async with self.sessions() as session:
            await session.execute(update(User).where(User.id == user_id).values(hashed_password=hashed))
            await session.commit()
        return hashed

    async def test_get_profile_returns_safe_personal_fields_without_sensitive_or_space_data(self):
        response = await self.client.get(BASE, headers=self.headers())
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["id"], 1)
        self.assertEqual(body["username"], "testuser1")
        self.assertEqual(body["email"], "test1@example.com")
        self.assertEqual(body["full_name"], "User 1")
        self.assertEqual(body["preferred_language"], "es")
        self.assertTrue(body["is_active"])
        self.assertIn("created_at", body)
        for forbidden_key in (
            "hashed_password",
            "password_hash",
            "password",
            "is_superuser",
            "extra_spaces_allowance",
            "spaces",
            "subscription_plan",
        ):
            self.assertNotIn(forbidden_key, body)

    async def test_patch_profile_updates_username_email_full_name_and_language(self):
        await self.set_user_password(1, "InitialPass123")

        # Partial update: only language (normalized from uppercase/whitespace)
        lang_en = await self.client.patch(BASE, json={"preferred_language": " EN "}, headers=self.headers())
        self.assertEqual(lang_en.status_code, 200, lang_en.text)
        self.assertEqual(lang_en.json()["preferred_language"], "en")
        self.assertEqual(lang_en.json()["username"], "testuser1")
        self.assertEqual(lang_en.json()["email"], "test1@example.com")

        # Update back to es + username + normalized email + full_name
        updated = await self.client.patch(
            BASE,
            json={
                "username": "  Sommelier1  ",
                "email": "  Sommelier.One@Example.COM ",
                "full_name": "  Ana Sommelier  ",
                "preferred_language": "Es",
            },
            headers=self.headers(),
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        data = updated.json()
        self.assertEqual(data["username"], "Sommelier1")
        self.assertEqual(data["email"], "sommelier.one@example.com")
        self.assertEqual(data["full_name"], "Ana Sommelier")
        self.assertEqual(data["preferred_language"], "es")
        self.assertIsNotNone(data["updated_at"])

        # Re-saving own values (including case change on own username) succeeds without false conflict
        same_user = await self.client.patch(
            BASE,
            json={"username": "sommelier1", "email": "sommelier.one@example.com"},
            headers=self.headers(),
        )
        self.assertEqual(same_user.status_code, 200, same_user.text)
        self.assertEqual(same_user.json()["username"], "sommelier1")

        # IAM login works with both the updated username and the updated email
        for identifier in ("sommelier1", "sommelier.one@example.com"):
            login = await self.client.post("/api/v1/iam/login", data={"username": identifier, "password": "InitialPass123"})
            self.assertEqual(login.status_code, 200, login.text)

    async def test_patch_profile_rejects_invalid_languages_empty_payload_and_conflicts(self):
        for payload in (
            {},
            {"preferred_language": "fr"},
            {"preferred_language": "pt"},
            {"preferred_language": "es-PE"},
            {"preferred_language": ""},
            {"preferred_language": None},
            {"username": "ab"},
            {"username": "bad_name!"},
            {"email": "not-an-email"},
            {"is_superuser": True, "preferred_language": "en"},
            {"extra_spaces_allowance": 999, "preferred_language": "en"},
        ):
            with self.subTest(payload=payload):
                response = await self.client.patch(BASE, json=payload, headers=self.headers())
                self.assertEqual(response.status_code, 422, response.text)

        # Duplicate username (case-insensitive) -> 409 USERNAME_TAKEN
        dup_username = await self.client.patch(BASE, json={"username": "TESTUSER2"}, headers=self.headers())
        self.assertEqual(dup_username.status_code, 409, dup_username.text)
        self.assertEqual(dup_username.json()["detail"]["code"], "USERNAME_TAKEN")

        # Duplicate email (case-insensitive) -> 409 EMAIL_TAKEN
        dup_email = await self.client.patch(BASE, json={"email": "TEST2@EXAMPLE.COM"}, headers=self.headers())
        self.assertEqual(dup_email.status_code, 409, dup_email.text)
        self.assertEqual(dup_email.json()["detail"]["code"], "EMAIL_TAKEN")

        # Ensure rejected attempts never altered privileged or profile fields
        async with self.sessions() as session:
            user = await session.get(User, 1)
            self.assertEqual(user.username, "testuser1")
            self.assertEqual(user.email, "test1@example.com")
            self.assertEqual(user.preferred_language, "es")
            self.assertFalse(user.is_superuser)
            self.assertEqual(user.extra_spaces_allowance, self.extra_spaces_allowance)

    async def test_change_password_validates_current_password_and_updates_hash_safely(self):
        original_hash = await self.set_user_password(1, "OldSecret123")

        # Wrong current password -> 401 and hash unchanged
        wrong = await self.client.post(
            BASE + "/change-password",
            json={"current_password": "WrongPassword", "new_password": "NewSecret456"},
            headers=self.headers(),
        )
        self.assertEqual(wrong.status_code, 401, wrong.text)
        self.assertEqual(wrong.json()["detail"]["code"], "INVALID_CURRENT_PASSWORD")
        self.assertNotIn(original_hash, wrong.text)
        async with self.sessions() as session:
            self.assertEqual((await session.get(User, 1)).hashed_password, original_hash)

        # Same password -> 422 PASSWORD_UNCHANGED
        same = await self.client.post(
            BASE + "/change-password",
            json={"current_password": "OldSecret123", "new_password": "OldSecret123"},
            headers=self.headers(),
        )
        self.assertEqual(same.status_code, 422, same.text)
        self.assertEqual(same.json()["detail"]["code"], "PASSWORD_UNCHANGED")

        # Policy violation (<6 chars or >72 UTF-8 bytes) -> 422 without echoing raw password
        for bad_new in ("12345", "x" * 73, "á" * 37):
            invalid = await self.client.post(
                BASE + "/change-password",
                json={"current_password": "OldSecret123", "new_password": bad_new},
                headers=self.headers(),
            )
            self.assertEqual(invalid.status_code, 422, invalid.text)
            self.assertEqual(invalid.json()["detail"]["code"], "INVALID_PASSWORD_POLICY")
            self.assertNotIn(bad_new, invalid.text)

        # Valid password change -> 200
        changed = await self.client.post(
            BASE + "/change-password",
            json={"current_password": "OldSecret123", "new_password": "NewSecret456"},
            headers=self.headers(),
        )
        self.assertEqual(changed.status_code, 200, changed.text)
        body = changed.json()
        self.assertTrue(body["password_changed"])
        self.assertFalse(body["sessions_revoked"])
        self.assertIn("JWT", body["security_notice"])
        self.assertNotIn("NewSecret456", changed.text)

        async with self.sessions() as session:
            updated_hash = (await session.get(User, 1)).hashed_password
            self.assertNotEqual(updated_hash, original_hash)
            self.assertTrue(verify_password("NewSecret456", updated_hash))
            self.assertFalse(verify_password("OldSecret123", updated_hash))

        # Active access token still works (stateless JWT behavior preserved)
        profile_after = await self.client.get(BASE, headers=self.headers())
        self.assertEqual(profile_after.status_code, 200)

        # Old password fails login, new password succeeds
        old_login = await self.client.post("/api/v1/iam/login", data={"username": "testuser1", "password": "OldSecret123"})
        self.assertEqual(old_login.status_code, 401)
        new_login = await self.client.post("/api/v1/iam/login", data={"username": "testuser1", "password": "NewSecret456"})
        self.assertEqual(new_login.status_code, 200, new_login.text)

    async def test_authentication_and_active_user_required_on_all_endpoints(self):
        await self.set_user_password(1, "OldSecret123")
        refresh = create_access_token({"sub": "1", "type": "refresh"})
        for headers in ({}, {"Authorization": "Bearer invalid"}, {"Authorization": "Bearer " + refresh}):
            self.assertEqual((await self.client.get(BASE, headers=headers)).status_code, 401)
            self.assertEqual((await self.client.patch(BASE, json={"preferred_language": "en"}, headers=headers)).status_code, 401)
            self.assertEqual(
                (await self.client.post(BASE + "/change-password", json={"current_password": "OldSecret123", "new_password": "NewSecret456"}, headers=headers)).status_code,
                401,
            )

        async with self.sessions() as session:
            await session.execute(update(User).where(User.id == 1).values(is_active=False))
            await session.commit()

        self.assertEqual((await self.client.get(BASE, headers=self.headers())).status_code, 401)
        self.assertEqual((await self.client.patch(BASE, json={"preferred_language": "en"}, headers=self.headers())).status_code, 401)
        self.assertEqual(
            (await self.client.post(BASE + "/change-password", json={"current_password": "OldSecret123", "new_password": "NewSecret456"}, headers=self.headers())).status_code,
            401,
        )

    async def test_migration_adds_preferred_language_with_default_and_constraint(self):
        async with self.engine.begin() as connection:
            await connection.execute(text("ALTER TABLE users DROP COLUMN preferred_language"))
            await connection.run_sync(upgrade_database)
            await connection.run_sync(upgrade_database)
            columns = {col["name"] for col in await connection.run_sync(lambda sync: inspect(sync).get_columns("users"))}
            self.assertIn("preferred_language", columns)
            head = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
            self.assertEqual(await connection.scalar(text("SELECT version_num FROM alembic_version")), head)

        async with self.sessions() as session:
            user = await session.get(User, 1)
            self.assertEqual(user.preferred_language, "es")
            self.assertEqual(user.username, "testuser1")

        # DB check constraint blocks unsupported languages even outside the API
        async with self.engine.begin() as connection:
            with self.assertRaises(IntegrityError):
                await connection.execute(text("UPDATE users SET preferred_language = 'fr' WHERE id = 1"))
