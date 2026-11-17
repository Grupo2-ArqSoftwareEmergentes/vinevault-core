# Identidad y pertenencia por espacio

## Modelo

- `users` contiene identidad/credenciales y metadatos de autenticación, sin propósito comercial ni plan global. Se añade `full_name`. `password_hash` es un alias ORM de la columna existente `hashed_password`: no se rehashean ni se exponen contraseñas.
- Se conservan `username`, `is_active`, timestamps y el flag administrativo IAM `is_superuser` por compatibilidad con login y `/iam/me`. Ese flag **no da acceso a espacios** y no sustituye membresías.
- `spaces` añade `space_type` (`COLLECTOR`, `BUSINESS`), `subscription_plan` (`FREE`, `PRO`) y `subscription_status` (`ACTIVE`, `EXPIRED`). El plan pertenece al espacio, nunca a la identidad. El valor legacy de plan BUSINESS se migra a PRO; no cambia el propósito BUSINESS.
- La cuenta incorpora un control de cupos `extra_spaces_allowance` y el espacio `extra_cellars_allowance`, ambos cero por defecto. No son un tipo de cuenta ni un plan global. Fórmulas y límites: [resource-quotas.md](resource-quotas.md).
- `space_members` relaciona usuarios y espacios mediante PK compuesta `(space_id, user_id)`, FKs reales e índice por usuario. El rol es `OWNER`, `SOMMELIER`, `WAITER` o `INVENTORY_CLERK` y se consulta en base de datos, no en el JWT. Borrar un espacio elimina sus membresías.
- `organization_id` y `owner_user_id` siguen en los DTOs/esquema para no romper clientes ni contratos Edge. La organización es transparente para navegación personal y `owner_user_id` queda como dato legacy: **no autoriza acceso**.

Un usuario puede ser OWNER de un Collector FREE y WAITER de un Business PRO sin compartir planes ni permisos entre ambos.

## Registro rápido y onboarding

El registro existente admite ahora identidad sin username explícito:

```http
POST /api/v1/iam/register
Content-Type: application/json

{"email":"persona@example.com","password":"una-clave-segura","full_name":"Persona Ejemplo"}
```

Si no se envía `username`, el backend genera uno compatible. El login conserva el formato de formulario OAuth (`username`, `password`); el campo `username` admite el correo o el username anterior. El registro crea solo la identidad, no espacios automáticamente.

Después del login:

```http
POST /api/v1/user/onboarding
Authorization: Bearer <access-token>
Content-Type: application/json

{"name":"Mi colección","space_type":"COLLECTOR"}
```

`space_type` es obligatorio en onboarding y admite mayúsculas/minúsculas (`Collector`, `Business`). En `POST /api/v1/spaces` y la ruta anidada por organización es opcional, con `COLLECTOR` como valor compatible para clientes antiguos.

El caso de uso guarda en una única transacción:

1. Organización transparente, si todavía no existe.
2. Espacio con el propósito elegido, plan `FREE` y estado `ACTIVE`.
3. Membresía del usuario como `OWNER`.
4. Una `Cava Principal`, sin dispositivo vinculado.

Si cualquier inserción falla, se revierte todo. El cliente no puede elegir un plan pagado o autoasignarse otro rol mediante el POST. La respuesta `201` conserva el espacio y `default_wine_cellar`, y añade tipo, plan, estado y `role: OWNER`. El onboarding es una creación, no una operación idempotente: no repetir el POST automáticamente; usar `POST /spaces` para crear espacios adicionales.

## Contexto global

`GET /api/v1/user/context`, `/spaces` y `/wine-cellars` incluyen espacios/cavas compartidos, no solo los creados por el usuario. El formato conserva las dos listas y amplía cada espacio:

```json
{
  "spaces": [{
    "id":"<uuid>",
    "name":"Restaurante",
    "space_type":"BUSINESS",
    "subscription_plan":"PRO",
    "subscription_status":"ACTIVE",
    "role":"SOMMELIER"
  }],
  "wine_cellars":[{"id":"<uuid-cava>","name":"Cava Principal","space_id":"<uuid>"}]
}
```

El frontend debe tomar tipo/plan/rol del espacio seleccionado, no de `/iam/me` ni del JWT. Ocultar acciones según rol mejora UX, pero el backend vuelve a autorizar cada petición. El contexto incluye consumos/límites agrupados, sin N+1 por espacio; ver [resource-quotas.md](resource-quotas.md) para `account_quota` y `spaces[].quotas`.

## Política inicial de roles

| Operación | OWNER | SOMMELIER | INVENTORY_CLERK | WAITER |
|---|---|---|---|---|
| Leer espacio, cavas, inventario, dispositivos y alertas | Sí | Sí | Sí | Sí |
| Crear/editar/eliminar cavas, vincular sensores y configurar dispositivos | Sí | Sí | No | No |
| Crear/editar/eliminar/importar inventario | Sí | Sí | Sí | No |
| Analizar con IA | Sí | Sí | Sí | No |
| Renombrar o eliminar el espacio | Sí | No | No | No |

`MANAGE` es el permiso base OWNER-only para futuras operaciones críticas de miembros y facturación. Este cambio no introduce endpoints de invitación, transferencia de propiedad o actualización de pagos; la tabla/repositorio y la política quedan preparados para esos casos de uso. No se debe exponer un cambio de membresía sin autorización OWNER ni permitir perder al último OWNER.

El guard se aplica a todos los routers de usuario de espacios, cavas, dispositivos, alertas y análisis IA. Resuelve también el espacio desde IDs de cava/dispositivo o desde el cuerpo de claim/IA. La lectura de un dispositivo individual ya no es pública. Token refresh usado como access token, identidad inactiva/inexistente: `401`; usuario ajeno o rol insuficiente: `403`; recurso ausente: `404`.

La ingesta autenticada del Edge no cambia: usa su API key y sus rutas separadas. El pairing físico sin tenant mantiene su comportamiento previo; reclamar el dispositivo sí exige permisos del espacio de destino. Un dispositivo ya asignado no se mueve implícitamente a otro espacio.

El estado EXPIRED se informa sin un downgrade automático adicional. Las cuotas se calculan con el plan guardado y ahora sustituyen el antiguo límite de cinco espacios por organización: [resource-quotas.md](resource-quotas.md).

## Migración y despliegue

**Respaldar la base y detener las instancias del backend antes de migrar.** La migración no se ejecuta automáticamente al arrancar ni se ha aplicado sobre la base habitual durante el desarrollo.

Desde la raíz de `vinevault-core`, con `.env` apuntando a la base correcta:

```powershell
.\venv\Scripts\python.exe -m alembic upgrade head
.\venv\Scripts\python.exe run.py
```

Alembic usa las mismas reglas de URL/TLS de `app/core/database.py`; un `DATABASE_URL` no vacío prevalece sobre los componentes. No ejecutar el comando contra una base real sin revisar ese destino.

La revisión `20261116_space_memberships`:

- Inicializa una base vacía o amplía el esquema anterior.
- Añade `full_name` y los campos de espacio con defaults `COLLECTOR/FREE/ACTIVE`.
- Conserva IDs, credenciales, cavas, inventarios y relaciones anteriores.
- Convierte propietarios existentes en miembros `OWNER`, sin duplicarlos.
- Aborta si un `owner_user_id` legacy no corresponde a un usuario real. Corregir explícitamente esos huérfanos con el responsable de los datos; no se crean identidades ficticias ni se reasignan silenciosamente espacios.
- Deshabilita el downgrade destructivo, porque eliminar membresías descartaría colaboradores. Para revertir, restaurar un respaldo verificado con la versión anterior del servicio.

El arranque detecta esquemas antiguos y exige la migración antes de ejecutar seeds. No usar `create_all` para actualizar columnas ni hacer `alembic stamp head` como sustituto del backfill. No se ejecutó una limpieza ni un reseteo de datos.

## Pruebas

```powershell
$env:TEST_DATABASE_URL='postgresql+asyncpg://postgres:postgres@localhost:5432/vinevault_core_db'
.\venv\Scripts\python.exe -B -m unittest discover -s tests -p test_space_tenancy.py -v
```

Estas pruebas usan esquemas PostgreSQL temporales, no las tablas existentes ni el lifespan/seeds. Cubren migración legacy y fresh, huérfanos, FKs/PK, rollback, registro/login, membresías revocadas, roles distintos por espacio y permisos sobre cavas/inventario/dispositivos. La suite completa sigue disponible con `-m unittest discover -s tests -v`.
