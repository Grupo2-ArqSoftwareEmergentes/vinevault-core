# Planes y cuotas de recursos

## Reglas vigentes

Las cuotas se validan en el backend, además de los permisos de membresía/rol. No sustituyen los controles multi-tenant.

| Recurso | FREE | PRO | Cupo comprado |
|---|---|---|---|
| Espacios propios por cuenta | 2 de cortesía: un COLLECTOR y un BUSINESS | Los espacios PRO también cuentan para el máximo global | `User.extra_spaces_allowance` aumenta el total permitido |
| Cavas por espacio | 1 | 3 | `Space.extra_cellars_allowance` se suma a la base del plan |
| Botellas de un COLLECTOR | 50 en todo el espacio | Sin límite de producto | Sin ampliación de botellas mediante los campos anteriores |
| SKUs de un BUSINESS | 25 en todo el espacio | Sin límite de producto | Sin ampliación de SKUs mediante los campos anteriores |

Los dos controles de ampliación son enteros no negativos, con default `0`. Solo son datos de lectura en las APIs de usuario: no se pueden autoconceder enviándolos al registrar una cuenta o crear un espacio. Los planes/cupos ahora se solicitan o activan en modo simulado mediante `app/subscriptions`; no hay pasarela real ni cobros, y los cupos efectivos combinan el valor manual con add-ons vigentes. Contrato: [subscriptions.md](subscriptions.md).

### Espacios de cuenta

- Máximo total: **`2 + extra_spaces_allowance`**, contando los espacios donde el usuario es miembro OWNER, de cualquier propósito y plan. Las invitaciones con otros roles no consumen cupos personales.
- Sin cupos extra, no se puede crear un segundo FREE del mismo propósito aunque quede el otro cupo de cortesía disponible.
- Los cupos extra sí permiten repetir propósito y crear otro FREE. Cada FREE por encima del primero de su tipo consume un cupo extra; ambos tipos comparten esa bolsa de extras.
- Ejemplo con un extra: permite COLLECTOR + COLLECTOR + BUSINESS, pero no tres COLLECTOR FREE. El cupo de cortesía BUSINESS no se convierte automáticamente en otro COLLECTOR.
- Cambiar de organización o usar el onboarding no elude el límite. El antiguo tope de cinco espacios por organización se elimina.

### Cavas e inventario

- La Cava Principal automática **ya consume** el primer cupo. Un espacio FREE recién creado no puede añadir otra cava sin un extra.
- El inventario se agrega sobre **todas las cavas del espacio**, nunca solo sobre la seleccionada.
- Para Collector se suma `quantity`; las filas con cantidad cero no aportan botellas.
- Para Business **cada registro/id es un SKU**, incluso con stock cero, nombre repetido o el mismo vino repartido en otras cavas. No se agrupa por nombre/bodega/añada.
- Un Business FREE puede tener muchas botellas por SKU: su límite es de registros, no de botellas. Un Collector FREE no tiene límite de registros distinto del límite de botellas.
- Los límites se aplican a altas, cambios de cantidad e importaciones Excel. El archivo completo se confirma o se revierte según su balance final; no se rechaza por un exceso transitorio entre filas que el mismo archivo compensa.
- Stock exits/descorches reducen consumo y se mantienen transaccionales. Las actualizaciones solo de ficha no consumen recursos nuevos.

Los límites se calculan a partir del plan efectivo (`FREE`/`PRO`; una suscripción Pro vencida ya no cuenta) y salen de `app/subscriptions/domain/catalog.py`, junto con el precio y el plan de análisis IA. `subscription_status` se sigue informando; no se inventa una política adicional de downgrade automático por vencimiento. Las cotas técnicas de tipos de datos (por ejemplo INTEGER por registro) siguen vigentes aunque no exista cuota de producto. Catálogo, activación simulada y cancelación: [subscriptions.md](subscriptions.md).

## API y errores

Las rutas actuales permanecen disponibles. También existen estos POST directos, con la misma seguridad y validación:

```http
POST /api/v1/wine-cellars
Authorization: Bearer <access-token>

{"space_id":"<uuid>","name":"Segunda cava"}
```

```http
POST /api/v1/wine-items
Authorization: Bearer <access-token>

{"wine_cellar_id":"<uuid>","name":"Reserva","quantity":3}
```

El segundo POST usa el mismo DTO de inventario unificado. La actualización conserva la ruta `PUT/PATCH /api/v1/wine-cellars/{cellar_id}/inventory/{item_id}`.

Todos los límites devuelven **HTTP 403** con `detail` estructurado:

```json
{
  "detail": {
    "code":"ITEM_LIMIT_REACHED",
    "message":"El espacio alcanzó el límite de inventario de su plan.",
    "current":51,
    "limit":50
  }
}
```

Códigos estables:

- `SPACE_LIMIT_REACHED`: máximo global o cortesía del propósito solicitado agotada.
- `CELLAR_LIMIT_REACHED`: base del plan más extras agotada.
- `ITEM_LIMIT_REACHED`: se excede el límite de botellas o SKUs aplicable.

En inventario, `current` puede expresar el consumo propuesto que fue rechazado; no significa que se haya guardado. El error revierte la transacción. Consultar el contexto para obtener consumo confirmado. Un `403` por permisos sigue siendo distinto de estos códigos de cuota.

## Contexto para frontend

`GET /api/v1/user/context` mantiene `spaces` y `wine_cellars`, añade `account_quota` y amplía cada espacio:

```json
{
  "spaces":[{
    "id":"<uuid>",
    "name":"Colección",
    "space_type":"COLLECTOR",
    "subscription_plan":"FREE",
    "subscription_status":"ACTIVE",
    "role":"OWNER",
    "extra_cellars_allowance":0,
    "quotas":{
      "cellars":{"used":1,"limit":1,"remaining":0},
      "bottles":{"used":35,"limit":50,"remaining":15},
      "skus":{"used":8,"limit":null,"remaining":null}
    }
  }],
  "wine_cellars":[{"id":"<uuid-cava>","name":"Cava Principal","space_id":"<uuid>"}],
  "account_quota":{
    "extra_spaces_allowance":0,
    "current_spaces":1,
    "max_spaces":2,
    "remaining_spaces":1,
    "can_create_collector":false,
    "can_create_business":true
  }
}
```

- `limit: null` significa ilimitado, no cero. `remaining: null` acompaña a los recursos ilimitados.
- `remaining` se acota a cero si existen consumos antiguos superiores al nuevo máximo; `used` siempre muestra el valor real.
- Usar `can_create_collector/business` para el selector de propósito: tener `remaining_spaces > 0` no garantiza otro cupo del mismo tipo.
- Las cuotas por espacio incluyen sus recursos compartidos, no únicamente los creados por el usuario actual.
- Actualizar el contexto tras crear/borrar espacios o cavas, añadir/eliminar inventario y registrar movimientos. La respuesta puede quedar desactualizada por otro miembro; el backend vuelve a validar cada escritura.
- Resolver `detail.code` antes del manejo genérico de `403`. Un rechazo de cuota no debe borrar la sesión ni presentarse como ausencia de permisos.
- Mostrar opciones de ampliación/upgrade sin enviar planes o allowances manipulados en el formulario de alta; la futura integración de cobros debe confirmar esos derechos en el servidor.

Las consultas de contexto son agrupadas y tienen cantidad fija: no se hace una consulta de consumo por cada espacio.

## Atomicidad y datos existentes

La creación de espacios toma un bloqueo por cuenta antes de contar sus espacios. Las altas de cavas y escrituras/importaciones de inventario bloquean el espacio antes de contar y de bloquear sus ítems. Todos los cálculos y cambios se hacen antes del commit, usando orden **espacio → ítem** para evitar carreras y deadlocks entre escritores coordinados.

El repositorio de cuotas nunca confirma transacciones. No se permite añadir un escritor alternativo que haga commits antes de validar. La futura integración de planes/cupos debe coordinarse con los mismos bloqueos de usuario/espacio. Renombrar un espacio actualiza solo su nombre, sin sobrescribir un plan o cupo comprado concurrentemente.

La migración no borra recursos ni inventario antiguos. Si una cuenta ya supera su capacidad, no puede crear otro espacio sin liberar/comprar cupo. Si un espacio ya supera su inventario, puede leerse, editar su ficha y reducir consumo; no puede aumentarlo mientras siga sobre el límite. Las cavas existentes pueden editarse, pero no se crean más si el espacio ya está lleno. Esto permite corregir datos o cambiar de plan sin perder información.

## Migración y pruebas

La revisión `20261117_resource_quotas` añade ambos allowances con default cero y restricciones no negativas. El valor legacy de **plan** `BUSINESS` se normaliza a `PRO`; el **propósito** `BUSINESS` no cambia. No se modifican roles, cantidades, IDs ni campos de inventario.

Con respaldo, instancias de API detenidas y `.env` apuntando a la base correcta:

```powershell
.\venv\Scripts\python.exe -m alembic upgrade head
```

No se aplica automáticamente sobre la base habitual. El arranque exige el esquema actualizado. No ejecutar `stamp head` en lugar de la migración ni borrar datos para resolver un exceso de cuota. El downgrade destructivo está bloqueado para no perder derechos adquiridos.

La imagen Docker incluye `alembic.ini` y los scripts de migración para poder ejecutarlos en un paso de despliegue separado, antes de iniciar la API; no se ejecutan automáticamente desde el entrypoint.

Pruebas sobre esquemas PostgreSQL temporales:

```powershell
$env:TEST_DATABASE_URL='postgresql+asyncpg://postgres:postgres@localhost:5432/vinevault_core_db'
.\venv\Scripts\python.exe -B -m unittest discover -s tests -p test_resource_quotas.py -v
```

Las suites anteriores usan allowances explícitos en sus fixtures para probar funcionalidad no relacionada con cuotas; esta suite utiliza los valores reales de fábrica (`0`) y prueba límites, agregados, concurrencia, importación y migración.
