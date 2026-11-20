# Suscripciones, catálogo oficial, activación simulada y cancelación

## Fuente de verdad del catálogo

`app/subscriptions/domain/catalog.py` centraliza planes, add-ons, tarifas mensuales oficiales, límites de recursos, ciclo de facturación (30 días) y disponibilidad de análisis con IA. Las cuotas (`app/shared/quota_policy.py`), el contexto de usuario (`GET /api/v1/user/context`), las exportaciones y los guards de IA (`app/core/space_security.py`, `app/assistant/interfaces/rest/security.py`) consumen estas definiciones sin duplicar constantes.

### Planes por espacio (`plan_scope: SPACE`)

| Propósito | Nivel | Tarifa mensual oficial | Cavas base | Botellas | SKUs | Análisis IA |
|---|---|---|---|---|---|---|
| `COLLECTOR` | `FREE` | USD `0.00` / PEN `0.00` | 1 | 50 | Sin límite de producto (`null`) | Habilitado |
| `BUSINESS` | `FREE` | USD `0.00` / PEN `0.00` | 1 | Sin límite de producto (`null`) | 25 | Habilitado |
| `COLLECTOR` | `PRO` | PEN `29.99` | 3 | Sin límite de producto (`null`) | Sin límite de producto (`null`) | Habilitado |
| `BUSINESS` | `PRO` | PEN `79.99` | 3 | Sin límite de producto (`null`) | Sin límite de producto (`null`) | Habilitado |

Las tarifas son montos explícitos por moneda, no conversiones. Los upgrades `PRO` solo se activan en `PEN`; no se publica una tarifa USD no confirmada.

### Add-ons por cuenta (`scope: ACCOUNT`)

| Código | Unidad | Tarifas mensuales oficiales |
|---|---|---|
| `EXTRA_SPACE` | `SPACE_SLOT` | USD `5.00` / PEN `20.00` |

Cada cuenta conserva 2 espacios de cortesía (`COLLECTOR: 1`, `BUSINESS: 1`) más los cupos adicionales vigentes. Las cavas heredan el plan y cuotas del espacio: **no existe un plan Pro independiente por cava**.

## Modelo de suscripción activa

- Cada compra confirmada crea una fila en `active_subscriptions` con `status: ACTIVE`, `started_at`, `current_period_end = started_at + 30 días`, `cancel_at_period_end`, importe unitario y total mensual en `PEN`.
- `UPGRADE_PRO` pertenece al espacio; solo puede existir una suscripción `ACTIVE` por espacio (índice único parcial). Se materializa `spaces.subscription_plan = PRO` para compatibilidad.
- `EXTRA_SPACE` pertenece a la cuenta (`requester_user_id`). Los cupos efectivos = `users.extra_spaces_allowance` manual/legacy + suma de `quantity` de add-ons `ACTIVE` no vencidos. No se escriben cupos desde el cliente ni se muta la columna manual.
- Las cuotas y los permisos IA usan los **derechos efectivos**: una suscripción vencida deja de conceder Pro/espacios aunque la fila histórica o el campo materializado sigan existiendo. El cierre de ciclo se reconcilia de forma perezosa en `overview` y en los flujos de cuota.
- La cancelación **no revoca** el beneficio durante el ciclo pagado: mantiene `PRO`/cupos hasta `current_period_end`, marca `cancel_at_period_end: true` y excluye el concepto de `next_cycle_monthly_total`.

## Endpoints

Todos exigen `Authorization: Bearer <access-token>` válido (no refresh) y usuario activo; si no, `401`.

### `GET /api/v1/subscriptions/catalog`

Catálogo oficial: `version`, `billing_mode: "PREPARATORY"`, `plan_scope`, `courtesy_spaces`, `cycle_days: 30`, `simulated_payment_available: true`, `activation_currency: "PEN"`, planes y add-ons. Los `Decimal` se serializan como strings de dos decimales.

### `GET /api/v1/subscriptions/overview`

Parámetros opcionales `space_id` y `cellar_id` (este último exige `space_id`, si no `422 SPACE_REQUIRED`).

Devuelve:

- `account_quota`: cupos de cuenta efectivos, coherentes con `/api/v1/user/context`.
- `space` (si se indica): `subscription_plan` **efectivo**, plan, rol, `can_manage_subscription`, `can_analyze`, `active_subscription` y `quotas` reales.
- `cellar`: `inherits_space_plan: true` si se filtró por cava.
- `billing`: `currency: "PEN"`, `cycle_days`, `monthly_recurring_total` (todos los conceptos activos vigentes), `next_cycle_monthly_total` (excluye cancelados a fin de ciclo) y `active_subscriptions` visibles para el usuario (más la suscripción del espacio consultado).

Cualquier miembro `READ` puede consultar; un usuario ajeno recibe `403`, una cava de otro espacio `404`.

### Activación inmediata (modo simulado)

Los dos POST admiten `confirm_simulated_payment: true`. Con confirmación responden **`201 Created`**, crean la intención `FULFILLED` y la suscripción `ACTIVE`, aplican el beneficio de inmediato y devuelven `entitlements_applied: true`, `payment_mode: "SIMULATED"` y el objeto `subscription`.

```http
POST /api/v1/subscriptions/plan-change-requests
Authorization: Bearer <token>

{
  "space_id": "<uuid>",
  "cellar_id": "<uuid-opcional>",
  "target_plan": "PRO",
  "currency": "PEN",
  "idempotency_key": "<uuid>",
  "confirm_simulated_payment": true
}
```

```http
POST /api/v1/subscriptions/extra-space-requests
Authorization: Bearer <token>

{
  "currency": "PEN",
  "quantity": 2,
  "idempotency_key": "<uuid>",
  "confirm_simulated_payment": true
}
```

- Upgrade: solo `OWNER` (`MANAGE`). Requiere espacio `FREE` efectivo; ya `PRO` devuelve `409 ALREADY_PRO`. `cellar_id` se valida contra el espacio (`404` si no pertenece) y la compra sigue siendo del espacio.
- Extra: cualquier usuario activo compra cupos para su propia cuenta; `quantity` entero 1–100. Total = `unit_amount × quantity`.
- La activación inmediata solo admite `PEN`. Un add-on `USD` puede registrarse con `confirm_simulated_payment: false` como intención pendiente, pero no activarse hasta que exista una regla de conversión/cobro confirmada (`422 SIMULATED_ACTIVATION_REQUIRES_PEN`).
- Idempotencia por `(requester_user_id, idempotency_key)`: repetir los mismos parámetros devuelve la misma intención y suscripción; parámetros distintos devuelven `409 IDEMPOTENCY_CONFLICT`.
- Bloqueos: cuenta → espacio; la activación concurrente del mismo espacio con claves distintas produce una sola suscripción (`201`) y el resto `409`.
- Con `confirm_simulated_payment: false` (valor por defecto) se conserva el flujo anterior: `202 PENDING_PAYMENT`, `entitlements_applied: false`, `payment_mode: "NONE"`, sin cambios de plan ni cupos. No se rompe ningún cliente existente.

### Cancelación a fin de ciclo

```http
POST /api/v1/subscriptions/{subscription_id}/cancel
Authorization: Bearer <token>
```

- `UPGRADE_PRO`: solo un `OWNER` del espacio puede cancelar. `EXTRA_SPACE`: solo el usuario que la contrató; un tercero recibe `404`.
- Marca `cancel_at_period_end: true` y `cancelled_at`; mantiene `status: ACTIVE`, plan/cupos y acceso hasta `access_until` (= `current_period_end`).
- La operación es idempotente mientras el ciclo siga vigente. Si ya venció, devuelve `409 SUBSCRIPTION_EXPIRED`.
- Tras el vencimiento, el concepto desaparece de `monthly_recurring_total`/`next_cycle_monthly_total`, la suscripción pasa a `EXPIRED` y las cuotas vuelven al plan FREE/ cupos restantes.
- No existe renovación automática real: el modelo deja preparado `auto_renews`, pero no hay scheduler ni pasarela. La reconciliación de vencimientos es perezosa al consultar/operar.

### `GET /api/v1/subscriptions/requests`

Paginado (`limit` 1–100, `offset` >= 0), solo solicitudes propias, orden descendente. Incluye intenciones pendientes y confirmadas.

## Errores, seguridad y límites

- Formato: `detail: {"code": "...", "message": "..."}`. Códigos: `INVALID_USER` (401), `FORBIDDEN` (403), `SPACE_NOT_FOUND`/`CELLAR_NOT_FOUND`/`SUBSCRIPTION_NOT_FOUND` (404), `ALREADY_PRO`/`UPGRADE_PENDING`/`IDEMPOTENCY_CONFLICT`/`SUBSCRIPTION_EXPIRED`/`INTENT_CANCELLED` (409), `SPACE_REQUIRED`/`CURRENCY_UNAVAILABLE`/`SIMULATED_ACTIVATION_REQUIRES_PEN` y validación Pydantic (422).
- El cliente no puede enviar importes, plan destino distinto de `PRO`, allowances ni flags de activación: la cotización sale del catálogo.
- La activación simulada es una decisión de producto explícita: no hay cobro real. No debe presentarse al usuario como un pago confirmado por una pasarela. El frontend debe mostrar «modo simulado» y no reintentar con otra clave si la operación pudo completarse.
- Los campos `subscription_plan`/`extra_spaces_allowance` devueltos en el contexto reflejan los derechos efectivos; no usar los valores crudos de la fila para conceder UI.

## Migración y pruebas

Cadena actual: `20261119_subscription_intents` → `20261120_user_preferred_language` → **`20261120_active_subscriptions`**. La última crea `active_subscriptions`, checks, índices y la unicidad de un Pro activo por espacio, sin tocar cuentas, espacios, inventario ni allowances. El downgrade destructivo está bloqueado.

```powershell
.\venv\Scripts\python.exe -m alembic upgrade head
```

```powershell
$env:TEST_DATABASE_URL='postgresql+asyncpg://postgres:postgres@localhost:5432/vinevault_core_db'
.\venv\Scripts\python.exe -B -m unittest discover -s tests -p test_subscriptions.py -v
.\venv\Scripts\python.exe -B -m unittest discover -s tests -p test_subscription_activation.py -v
```

`test_subscription_activation.py` cubre activación Pro inmediata (precios 29.99/79.99), ciclo de 30 días, MRR (109.98/149.98), cupos extra (20.00 por cupo), permisos, idempotencia, moneda, cancelación con acceso hasta fin de ciclo, expiración y modo pendiente. `test_subscriptions.py` conserva catálogo, aislamiento y compatibilidad con el flujo preparatorio. PostgreSQL temporal, sin pasarela ni cobros reales.
