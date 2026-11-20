# Suscripciones, catálogo oficial y solicitudes preparatorias

## Fuente de verdad del catálogo

`app/subscriptions/domain/catalog.py` centraliza planes, add-ons, tarifas mensuales oficiales, límites de recursos y disponibilidad de análisis con IA. Las cuotas (`app/shared/quota_policy.py`), el contexto de usuario (`GET /api/v1/user/context`) y los guards de IA (`app/core/space_security.py`, `app/assistant/interfaces/rest/security.py`) consumen estas definiciones sin duplicar constantes.

### Planes por espacio (`plan_scope: SPACE`)

| Propósito | Nivel | Tarifa mensual oficial | Cavas base | Botellas | SKUs | Análisis IA |
|---|---|---|---|---|---|---|
| `COLLECTOR` | `FREE` | USD `0.00` / PEN `0.00` | 1 | 50 | Sin límite de producto (`null`) | Habilitado |
| `BUSINESS` | `FREE` | USD `0.00` / PEN `0.00` | 1 | Sin límite de producto (`null`) | 25 | Habilitado |
| `COLLECTOR` | `PRO` | PEN `29.99` | 3 | Sin límite de producto (`null`) | Sin límite de producto (`null`) | Habilitado |
| `BUSINESS` | `PRO` | PEN `79.99` | 3 | Sin límite de producto (`null`) | Sin límite de producto (`null`) | Habilitado |

Las tarifas son montos explícitos por moneda, no conversiones de tipo de cambio. Los upgrades `PRO` solo admiten `PEN` hasta que exista una tarifa oficial en otra moneda; solicitar `USD` para upgrade devuelve `422` (`CURRENCY_UNAVAILABLE`).

### Add-ons por cuenta (`scope: ACCOUNT`)

| Código | Unidad | Tarifas mensuales oficiales |
|---|---|---|
| `EXTRA_SPACE` | `SPACE_SLOT` | USD `5.00` / PEN `20.00` |

Cada cuenta conserva 2 espacios de cortesía (`COLLECTOR: 1`, `BUSINESS: 1`) más `extra_spaces_allowance`. Las cavas heredan el plan y cuotas del espacio al que pertenecen.

## Endpoints

Todos los endpoints bajo `/api/v1/subscriptions` requieren `Authorization: Bearer <access-token>` válido (no refresh token) y usuario activo (`is_active = true`). En caso contrario devuelven `401`.

### `GET /api/v1/subscriptions/catalog`

Devuelve el catálogo oficial (`version`, `billing_mode: "PREPARATORY"`, `plan_scope`, `courtesy_spaces`, `plans`, `addons`). Los montos `Decimal` se serializan como strings con dos decimales.

### `GET /api/v1/subscriptions/overview`

Parámetros opcionales: `space_id`, `cellar_id` (`space_id` es obligatorio si se envía `cellar_id`, de lo contrario `422 SPACE_REQUIRED`).

- Devuelve `billing_mode`, `account_quota` (coherente con `GET /api/v1/user/context`) y, cuando se indica `space_id`, el estado del espacio (`purpose`, `subscription_plan`, `subscription_status`, `role`, `plan`, `extra_cellars_allowance`, `can_manage_subscription`, `can_analyze`, `quotas`) y el resumen opcional de `cellar` (`inherits_space_plan: true`).
- Autorización por espacio: requiere membresía con permiso `READ` (`403 FORBIDDEN` para usuarios ajenos o sin membresía). Si `cellar_id` no pertenece a `space_id`, devuelve `404 CELLAR_NOT_FOUND`.

### `POST /api/v1/subscriptions/plan-change-requests` (`202 Accepted`)

Registra una intención preparatoria de upgrade de espacio `FREE` a `PRO` (`kind: "UPGRADE_PRO"`, `status: "PENDING_PAYMENT"`, `entitlement_scope: "SPACE"`, `entitlements_applied: false`).

```json
{
  "space_id": "<uuid>",
  "cellar_id": null,
  "target_plan": "PRO",
  "currency": "PEN",
  "idempotency_key": "<uuid>"
}
```

- Requiere membresía `OWNER` (`SpacePermission.MANAGE`) sobre `space_id`. Roles distintos, usuarios ajenos o `is_superuser` sin membresía `OWNER` reciben `403 FORBIDDEN`.
- Bloquea `users` y luego `spaces` (respetando el orden global cuenta → espacio → ítem) antes de validar estado e insertar.
- Rechaza espacios ya `PRO` (`409 ALREADY_PRO`), upgrades duplicados pendientes sobre el mismo espacio (`409 UPGRADE_PENDING`), moneda no disponible (`422 CURRENCY_UNAVAILABLE`), campos extra o `target_plan != "PRO"` (`422`).
- Idempotente por `(requester_user_id, idempotency_key)`: repetir la misma clave con los mismos parámetros devuelve el registro existente (`202`); reutilizar la clave con parámetros distintos devuelve `409 IDEMPOTENCY_CONFLICT`.

### `POST /api/v1/subscriptions/extra-space-requests` (`202 Accepted`)

Registra una intención preparatoria de cupo adicional de espacio a nivel cuenta (`kind: "EXTRA_SPACE"`, `status: "PENDING_PAYMENT"`, `entitlement_scope: "ACCOUNT"`, `entitlements_applied: false`).

```json
{
  "currency": "USD",
  "quantity": 1,
  "idempotency_key": "<uuid>"
}
```

- `currency`: `USD` (`5.00`) o `PEN` (`20.00`).
- `quantity`: entero estricto entre `1` y `100` (booleans, floats y strings se rechazan con `422`).
- Idempotente por `(requester_user_id, idempotency_key)`.

### `GET /api/v1/subscriptions/requests`

Lista paginada (`limit` 1–100, `offset` >= 0) de las solicitudes propias del usuario autenticado, ordenadas por fecha de creación descendente. Nunca expone solicitudes de otras cuentas.

## Modo preparatorio y garantías

Mientras la pasarela de pago no esté conectada (`billing_mode: "PREPARATORY"`):

- Ningún endpoint de `subscriptions` modifica `spaces.subscription_plan`, `spaces.subscription_status`, `spaces.extra_cellars_allowance` ni `users.extra_spaces_allowance`.
- Los límites vigentes de espacios, cavas, botellas y SKUs siguen aplicándose exactamente sobre los derechos confirmados en base de datos.
- Errores de negocio usan `detail: {"code": "...", "message": "..."}`.

## Migración y pruebas

La revisión `20261119_subscription_intents` crea la tabla `subscription_intents` con restricciones de integridad, unicidad por `(requester_user_id, idempotency_key)` e índice único parcial para upgrades `PENDING_PAYMENT` por espacio. El downgrade destructivo está bloqueado.

```powershell
.\venv\Scripts\python.exe -m alembic upgrade head
```

Pruebas unitarias y de integración (PostgreSQL temporal):

```powershell
$env:TEST_DATABASE_URL='postgresql+asyncpg://postgres:postgres@localhost:5432/vinevault_core_db'
.\venv\Scripts\python.exe -B -m unittest discover -s tests -p test_subscriptions.py -v
```
