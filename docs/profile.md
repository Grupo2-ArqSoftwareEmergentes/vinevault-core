# Perfil y preferencias de cuenta (`profile`)

## Alcance y separación de responsabilidades

El módulo `app/profile` gestiona exclusivamente datos personales, credenciales y preferencias de idioma de la cuenta autenticada (`users`). No mezcla ni expone roles de espacio, planes (`FREE`/`PRO`), cuotas de recursos ni flags administrativos (`is_superuser`).

Todos los endpoints bajo `/api/v1/profile` exigen `Authorization: Bearer <access-token>` válido (los refresh tokens se rechazan) y usuario activo (`is_active = true`). En caso contrario devuelven `401`.

## Endpoints

### `GET /api/v1/profile`

Devuelve el perfil no sensible del usuario autenticado:

```json
{
  "id": 1,
  "username": "sommelier1",
  "email": "sommelier@example.com",
  "full_name": "Ana Sommelier",
  "preferred_language": "es",
  "is_active": true,
  "created_at": "2026-11-19T22:00:00Z",
  "updated_at": null,
  "last_login": null
}
```

Nunca devuelve `hashed_password`, `password_hash`, `is_superuser` ni `extra_spaces_allowance`.

### `PATCH /api/v1/profile`

Actualización parcial de `username`, `email`, `full_name` y `preferred_language`. Los campos omitidos conservan su valor actual; los campos enviados explícitamente como `null`, payloads vacíos o campos no permitidos (`extra="forbid"`) se rechazan con `422`.

- `username`: recortado, alfanumérico, 3–50 caracteres. Unicidad validada sin distinguir mayúsculas/minúsculas (`409 USERNAME_TAKEN`).
- `email`: validado como correo, recortado y normalizado a minúsculas, máximo 100 caracteres. Unicidad validada sin distinguir mayúsculas/minúsculas (`409 EMAIL_TAKEN`).
- `full_name`: recortado, máximo 255 caracteres.
- `preferred_language`: normalizado (`strip().lower()`) y restringido a `es` o `en` (`422` para cualquier otro idioma).

### `POST /api/v1/profile/change-password`

Cambio explícito de contraseña para el usuario autenticado:

```json
{
  "current_password": "OldPassword123",
  "new_password": "NewPassword456"
}
```

- Valida `current_password` contra el hash bcrypt almacenado; si no coincide devuelve `401` (`INVALID_CURRENT_PASSWORD`) sin exponer hashes ni trazas.
- Rechaza `new_password == current_password` (`422 PASSWORD_UNCHANGED`) y aplica la política de longitud (`>= 6` caracteres y `<= 72` bytes UTF-8).
- Guarda el nuevo hash bcrypt y mantiene intacta la sesión JWT stateless activa (los tokens emitidos autentican por `user_id` y expiran según su TTL), devolviendo `sessions_revoked: false` junto con `security_notice`.

## Errores estructurados

Los errores de dominio usan `{"detail": {"code": "...", "message": "..."}}`:

| HTTP | `detail.code` | Motivo |
|---|---|---|
| `401` | `INVALID_USER` | Token inválido/refresh o cuenta inactiva |
| `401` | `INVALID_CURRENT_PASSWORD` | Contraseña actual incorrecta |
| `409` | `USERNAME_TAKEN` | Nombre de usuario en uso por otra cuenta |
| `409` | `EMAIL_TAKEN` | Correo electrónico en uso por otra cuenta |
| `409` | `PROFILE_CONFLICT` | Conflicto concurrente de unicidad |
| `422` | `EMPTY_UPDATE` / `INVALID_PASSWORD_POLICY` / `PASSWORD_UNCHANGED` / validación Pydantic | Idioma no soportado, payload vacío, campos extra o política de contraseña |

## Migración y pruebas

La revisión `20261120_user_preferred_language` añade `users.preferred_language` (`VARCHAR(5) NOT NULL DEFAULT 'es'`) y el check constraint `user_preferred_language_valid` (`IN ('es', 'en')`).

```powershell
.\venv\Scripts\python.exe -m alembic upgrade head
```

Pruebas:

```powershell
$env:TEST_DATABASE_URL='postgresql+asyncpg://postgres:postgres@localhost:5432/vinevault_core_db'
.\venv\Scripts\python.exe -B -m unittest discover -s tests -p test_profile.py -v
```
