# Integracion Edge <-> Core en Vinevault

Este documento resume el contrato real que hoy expone `vinevault-core` para trabajar con un edge device y con el resto del dominio del core.

La base original venia de otro proyecto similar, pero aqui se ajusta a lo que realmente existe en este repo.

## 1. Panorama general

Inventario de fábrica: el arranque Core normaliza los 50 seriales `SN-0001`..`SN-0050` a `VINE-A001`..`VINE-A050`, incluyendo `Sensor 0006`/`Sensor 0007`. Conserva IDs internos, claves válidas y asignaciones. Emite actualizaciones en `vinevault.provisioning.devices.changed` sin cambiar el esquema; Edge actualiza el hardware ID de la misma fila mediante upsert por `device_id`. Actualizar también los IDs configurados en firmware/simuladores. Si se perdió el evento por indisponibilidad del broker, solicitar resincronización completa mediante `vinevault.provisioning.devices.sync.requested`. No equivale a una prueba de entrega real Core/Kafka/Edge.

`vinevault-core` hoy maneja cinco bloques principales:

1. Identidad y autenticacion de usuarios via IAM.
2. Gestion de devices, pairing, claim y estado.
3. Gestion de organizaciones, spaces y thresholds.
4. Un dominio adicional de `wine cellar` que cuelga de `spaces` y `devices`.
5. Ingesta de telemetry desde edge para observaciones de devices.

## 2. Rutas REST que existen hoy

### Contexto personal y navegación directa

Cuotas: el límite legacy de cinco espacios por organización queda reemplazado por cupos de cuenta, propósito y plan. El contexto agrega `account_quota` y `spaces[].quotas`; altas/actualizaciones/importaciones usan `403` con códigos `SPACE_LIMIT_REACHED`, `CELLAR_LIMIT_REACHED` o `ITEM_LIMIT_REACHED`. Las rutas anidadas y los nuevos POST directos `/api/v1/wine-cellars` y `/api/v1/wine-items` comparten los mismos controles. Esto no cambia los contratos Edge/Kafka. Contrato y migración: [docs/resource-quotas.md](docs/resource-quotas.md).

Inventario unificado: los ítems de las mismas rutas `/wine-cellars/{id}/inventory` admiten nombre canónico `name` (alias `wine_name`) y ficha opcional compartida Collector/Business. `POST /wine-cellars/{id}/inventory/{item_id}/movements` registra salidas con motivo y stock atómico; no cambia rutas ni payloads Edge/Kafka. Contrato y migración: [docs/wine-inventory.md](docs/wine-inventory.md).

Actualización multi-tenant: el acceso de usuarios a espacios, cavas, dispositivos y análisis se valida por `space_members`, no por los campos legacy de propietario. `POST /api/v1/user/onboarding` recibe `name` y `space_type` (`COLLECTOR`/`BUSINESS`) y crea espacio FREE/ACTIVE, membresía OWNER y Cava Principal en una transacción. `GET /api/v1/user/context` incluye espacios compartidos y añade `space_type`, `subscription_plan`, `subscription_status` y `role` a cada espacio. Los contratos de ingesta Edge y los payloads Kafka no cambian. Detalles y migración obligatoria para bases existentes: [docs/space-tenancy.md](docs/space-tenancy.md). Las referencias anteriores a "usuario dueño" en rutas de lectura deben interpretarse ahora como "miembro autorizado del espacio"; las escrituras aplican la política de roles documentada.

- `POST /api/v1/spaces` con `{"name":"Casa"}` permite crear espacios sin seleccionar organización. Reutiliza la organización más antigua del usuario (desempate por ID) o crea `Organización Personal` si no existe, en la misma transacción que el espacio. Conserva el límite de cinco espacios por organización y las rutas anidadas existentes.
- `GET /api/v1/user/context` devuelve `{"spaces":[{"id":"...","name":"..."}],"wine_cellars":[{"id":"...","name":"...","space_id":"..."}]}` para el selector global. Es de solo lectura, no inicializa datos y usa dos consultas filtradas por el usuario autenticado.
- `GET /api/v1/wine-cellars` lista las cavas del usuario. Acepta `spaceId` o `space_id` para filtrar por un espacio propio; valores simultáneos distintos producen `422`, un espacio inexistente `404` y uno ajeno `403`.
- La creación de cavas sigue disponible en `POST /api/v1/spaces/{space_id}/wine-cellars`, sin validación adicional de organización.
- Ambas rutas de creación de espacios (directa y anidada por organización) crean una `Cava Principal` con descripción `Cava inicial creada automáticamente` y `device_id=null`. Organización nueva, espacio y cava se confirman en una única transacción. La respuesta de creación conserva los campos de `SpaceResponse` y agrega `default_wine_cellar` con la representación completa `WineCellarResponse`; el frontend puede autoseleccionar su ID sin otra llamada. El contexto global refleja la nueva cava sin cambios en su formato. No se modifican espacios anteriores ni se crea una cava por consultar el contexto.
- Estas rutas usan JWT de usuario, no API key del edge. No cambian los contratos Kafka ni las foreign keys.
- `DELETE /api/v1/spaces/{space_id}` valida el propietario y elimina inventarios, cavas y espacio en una única transacción; responde `204` incluso si el espacio tenía cavas. La organización se conserva. Mantiene `409` (`Space has devices`) si existen dispositivos asignados. La confirmación destructiva corresponde al frontend y debe advertir sobre la pérdida de cavas e inventario; no requiere peticiones DELETE separadas por cava.

### IAM

- `GET /api/v1/iam/health`
  - Health check del modulo IAM.
  - Referencia:
    - [app/iam/router.py](D:/vinevault/vinevault-core/app/iam/router.py)

- `POST /api/v1/iam/register`
- `POST /api/v1/iam/login`
- `POST /api/v1/iam/refresh`
- `GET /api/v1/iam/me`
- `GET /api/v1/iam/users`
  - Flujo de autenticacion y usuarios.
  - Referencia:
    - [app/iam/router.py](D:/vinevault/vinevault-core/app/iam/router.py)

### Devices

#### Asociación opcional de cava al reclamar hardware

`POST /api/v1/devices/claim` acepta `cellar_id: UUID | null` opcional junto a `claim_token` y `space_id`. Omitido/null conserva el contrato anterior: solo asignación al espacio. Con cava, valida pertenencia al mismo espacio y disponibilidad; una cava ocupada o de otro espacio produce 409, inexistente 404, sin consumir el token ni asignar parcialmente el sensor. Un fallo de persistencia revierte ambas escrituras. El bloqueo sigue espacio → cava → asignación para serializar reclamaciones competidoras.

Respuesta de claim, GET listado y GET detalle agregan `cellar_id` y `cellar_name` anulables. La asociación se lee desde `wine_cellars.device_id`, no se duplica en device assignments; renombrar/desvincular una cava se refleja en el siguiente GET. El listado resuelve asociaciones en lote y filtra por el espacio autorizado. `name` sigue siendo el nombre actual del sensor, sin usar `factory_name` como nombre visible. El endpoint de link existente sigue disponible y utiliza el mismo bloqueo para no sustituir una vinculación concurrente. No requiere migración ni cambios en topics/provisioning de Edge.

#### Conectividad por actividad UTC

Listado, detalle y `/devices/{id}/status` agregan `is_online` y devuelven `last_seen_at` con zona UTC (`Z`). Una actividad válida (telemetría o heartbeat) de hasta **5 minutos** cuenta como conexión, con independencia del RSSI, SSID o `wifi_status`. Los estados ONLINE/OFFLINE de respuesta se evalúan al leer, por lo que una asignación ONLINE almacenada también caduca sin un job de fondo. STANDBY, MAINTENANCE y DECOMMISSIONED bloquean conectividad. ERROR conserva su estado operativo; `is_online` es independiente del diagnóstico del hardware.

La ingesta REST `/api/v1/edges/devices/telemetry` y el consumidor Kafka usan el mismo servicio: guardan lectura y última actividad juntos, bloqueando la asignación para no perder una orden de apagado concurrente. Fechas naive son UTC, offsets se convierten a UTC y actividad futura se limita al reloj Core. Eventos atrasados no hacen retroceder `last_seen_at`. Lecturas legacy sin `last_seen_at` se consideran mediante una consulta agregada por asignación, sin N+1 ni mezclar una asignación anterior del sensor.

Un POST de comando STANDBY guarda la intención explícita en `configuration["control.power_state"]` y su fecha en `control.power_changed_at`, en la misma transacción que el comando. Lecturas/heartbeats posteriores no reactivan ese sensor. WAKE levanta el bloqueo, pero solo actividad posterior a WAKE confirma conexión; enviar el comando no demuestra que haya despertado. La intención persiste incluso si falla la entrega; el usuario puede corregirla con una nueva orden WAKE. No se añade migración ni se modifica el formato Kafka. Edge REST sigue autenticado con su Bearer API key.

- `GET /api/v1/devices?space_id={spaceId}&page={page}&size={size}`
  - Lista devices de un `space` perteneciente al usuario autenticado.
  - Requiere `Authorization: Bearer <jwt>`.
  - Referencia:
    - [app/device/interfaces/rest/controllers/device_controller.py](D:/vinevault/vinevault-core/app/device/interfaces/rest/controllers/device_controller.py)

- `POST /api/v1/devices/pair`
  - Inicia el pairing fisico usando `hardware_id`.
  - Devuelve `device_id` y `claim_token`.
  - Referencias:
    - [app/device/interfaces/rest/controllers/device_controller.py](D:/vinevault/vinevault-core/app/device/interfaces/rest/controllers/device_controller.py)
    - [app/device/interfaces/rest/resources/request_models.py](D:/vinevault/vinevault-core/app/device/interfaces/rest/resources/request_models.py)

- `POST /api/v1/devices/claim`
  - Reclama un device para un `space_id` usando `claim_token`.
  - Requiere usuario autenticado.
  - Referencias:
    - [app/device/interfaces/rest/controllers/device_controller.py](D:/vinevault/vinevault-core/app/device/interfaces/rest/controllers/device_controller.py)
    - [app/device/interfaces/rest/resources/request_models.py](D:/vinevault/vinevault-core/app/device/interfaces/rest/resources/request_models.py)

- `GET /api/v1/devices/{device_id}`
  - Devuelve el device y su assignment.
  - Referencia:
    - [app/device/interfaces/rest/controllers/device_controller.py](D:/vinevault/vinevault-core/app/device/interfaces/rest/controllers/device_controller.py)

- `GET /api/v1/devices/{device_id}/status`
  - Estado actual del device para el usuario dueno.
  - Referencia:
    - [app/device/interfaces/rest/controllers/device_controller.py](D:/vinevault/vinevault-core/app/device/interfaces/rest/controllers/device_controller.py)

- `DELETE /api/v1/devices/{device_id}`
  - Resetea el assignment y devuelve el device a su nombre factory.
  - Referencia:
    - [app/device/interfaces/rest/controllers/device_controller.py](D:/vinevault/vinevault-core/app/device/interfaces/rest/controllers/device_controller.py)

- `PATCH /api/v1/devices/{device_id}/name`
  - Renombra el device.
  - Referencia:
    - [app/device/interfaces/rest/controllers/device_controller.py](D:/vinevault/vinevault-core/app/device/interfaces/rest/controllers/device_controller.py)

- `PATCH /api/v1/devices/{device_id}`
  - Alias de la ruta de rename.
  - Referencia:
    - [app/device/interfaces/rest/controllers/device_controller.py](D:/vinevault/vinevault-core/app/device/interfaces/rest/controllers/device_controller.py)

- `GET /api/v1/devices/{device_id}/commands`
- `POST /api/v1/devices/{device_id}/commands`
  - Consulta y creacion de comandos del device.
  - Referencia:
    - [app/device/interfaces/rest/controllers/device_controller.py](D:/vinevault/vinevault-core/app/device/interfaces/rest/controllers/device_controller.py)

- `GET /api/v1/devices/{device_id}/commands/{command_id}`
- `GET /api/v1/devices/{device_id}/commands/latest`
  - Consulta de un comando puntual y del ultimo comando del device.
  - Referencia:
    - [app/device/interfaces/rest/controllers/device_controller.py](D:/vinevault/vinevault-core/app/device/interfaces/rest/controllers/device_controller.py)

- `GET /api/v1/devices/{device_id}/telemetry`
  - Devuelve las lecturas de telemetry registradas para el device del usuario autenticado.
  - Referencia:
    - [app/device/interfaces/rest/controllers/device_controller.py](D:/vinevault/vinevault-core/app/device/interfaces/rest/controllers/device_controller.py)

### Thresholds

- `GET /api/v1/devices/{device_id}/thresholds`
- `POST /api/v1/devices/{device_id}/thresholds`
- `PUT /api/v1/devices/{device_id}/thresholds`
- `PATCH /api/v1/devices/{device_id}/thresholds/{metric}`
- `DELETE /api/v1/devices/{device_id}/thresholds/{metric}`
  - CRUD de thresholds del device.
  - Los metrics soportados hoy son:
    - `temperature_min`
    - `temperature_max`
    - `humidity_min`
    - `humidity_max`
  - Referencias:
    - [app/device/interfaces/rest/controllers/threshold_controller.py](D:/vinevault/vinevault-core/app/device/interfaces/rest/controllers/threshold_controller.py)
    - [app/device/domain/models/value_objects/metric_threshold.py](D:/vinevault/vinevault-core/app/device/domain/models/value_objects/metric_threshold.py)

### Organizations

- `GET /api/v1/organizations`
- `GET /api/v1/organizations/{organization_id}`
- `POST /api/v1/organizations`
- `PATCH /api/v1/organizations/{organization_id}/name`
- `DELETE /api/v1/organizations/{organization_id}`
  - Gestion de organizaciones del usuario autenticado.
  - Referencia:
    - [app/device/interfaces/rest/controllers/organization_controller.py](D:/vinevault/vinevault-core/app/device/interfaces/rest/controllers/organization_controller.py)

### Spaces

- `GET /api/v1/organizations/{organization_id}/spaces`
- `GET /api/v1/spaces`
- `GET /api/v1/spaces/{space_id}`
- `POST /api/v1/organizations/{organization_id}/spaces`
- `PATCH /api/v1/spaces/{space_id}/name`
- `DELETE /api/v1/spaces/{space_id}`
  - Gestion de spaces dentro de una organizacion.
  - Referencia:
    - [app/device/interfaces/rest/controllers/space_controller.py](D:/vinevault/vinevault-core/app/device/interfaces/rest/controllers/space_controller.py)

### Edge inventory

- `GET /api/v1/edges/devices`
  - Lista el inventario completo que ve un edge autenticado.
  - Requiere autenticacion por API key del edge.
  - Referencias:
    - [app/device/interfaces/rest/controllers/edge_controller.py](D:/vinevault/vinevault-core/app/device/interfaces/rest/controllers/edge_controller.py)
    - [app/dependencies.py](D:/vinevault/vinevault-core/app/dependencies.py)

- `POST /api/v1/edges/devices/presence`
  - Reporta presencia y estado de un device desde el edge autenticado.
  - Acepta `device_id` o `hardware_id`, junto con `status` y `occurred_at` opcional.
  - Referencias:
    - [app/device/interfaces/rest/controllers/edge_controller.py](D:/vinevault/vinevault-core/app/device/interfaces/rest/controllers/edge_controller.py)
    - [app/device/applications/command_handlers/device_presence_command_handler.py](D:/vinevault/vinevault-core/app/device/applications/command_handlers/device_presence_command_handler.py)

- `POST /api/v1/edges/devices/commands/ack`
  - Reporta ACK, ejecucion o fallo de un comando enviado al device.
  - Acepta `device_id`, `command_id`, `status`, `failure_reason` y `occurred_at` opcional.
  - Referencias:
    - [app/device/interfaces/rest/controllers/edge_controller.py](D:/vinevault/vinevault-core/app/device/interfaces/rest/controllers/edge_controller.py)
    - [app/device/applications/command_handlers/__init__.py](D:/vinevault/vinevault-core/app/device/applications/command_handlers/__init__.py)

### Telemetry

- `POST /api/v1/edges/devices/telemetry`
  - Registra un paquete de telemetry enviado por el edge autenticado.
  - Acepta `device_id` o `hardware_id`, un `payload` no vacio, `source` opcional y `occurred_at` opcional.
  - Persiste la observacion y publica un evento Kafka para consumo posterior.
  - Referencias:
    - [app/telemetry/interfaces/rest/controllers/telemetry_controller.py](D:/vinevault/vinevault-core/app/telemetry/interfaces/rest/controllers/telemetry_controller.py)
    - [app/telemetry/applications/command_handlers/telemetry_command_handler.py](D:/vinevault/vinevault-core/app/telemetry/applications/command_handlers/telemetry_command_handler.py)
    - [app/device/infrastructure/kafka/device_event_publisher.py](D:/vinevault/vinevault-core/app/device/infrastructure/kafka/device_event_publisher.py)

### Wine cellar

- `GET /api/v1/spaces/{space_id}/wine-cellars`
- `POST /api/v1/spaces/{space_id}/wine-cellars`
- `PUT /api/v1/wine-cellars/{wine_cellar_id}`
- `DELETE /api/v1/wine-cellars/{wine_cellar_id}`
- `POST /api/v1/wine-cellars/{wine_cellar_id}/devices`
- `DELETE /api/v1/wine-cellars/{wine_cellar_id}/devices/{device_id}`
- `GET /api/v1/wine-cellars/{wine_cellar_id}/inventory`
- `POST /api/v1/wine-cellars/{wine_cellar_id}/inventory`
- `PUT /api/v1/wine-cellars/{wine_cellar_id}/inventory/{inventory_item_id}`
- `DELETE /api/v1/wine-cellars/{wine_cellar_id}/inventory/{inventory_item_id}`
  - Dominio adicional ya integrado en el core.
  - Referencia:
    - [app/wine_cellar/interfaces/rest/controllers/wine_cellar_controller.py](D:/vinevault/vinevault-core/app/wine_cellar/interfaces/rest/controllers/wine_cellar_controller.py)

## 3. Autenticacion y headers

### Usuarios

- `Authorization: Bearer <jwt>`
  - Se usa para rutas de usuario autenticado.
  - El `sub` o `user_id` del JWT se toma como ID numerico del usuario.
  - Referencia:
    - [app/dependencies.py](D:/vinevault/vinevault-core/app/dependencies.py)

### Edge

- `Authorization: Bearer <edge_api_key>`
  - Asi se autentica el edge hoy.
  - No se usa `X-Edge-Token` ni `X-API-Key` en el flujo implementado.
  - El api key se valida contra `EdgeDevice`.
  - Referencias:
    - [app/dependencies.py](D:/vinevault/vinevault-core/app/dependencies.py)
    - [app/main.py](D:/vinevault/vinevault-core/app/main.py)

### CORS

- El core permite todos los headers y metodos desde los origenes definidos en `CORS_ORIGINS`.
  - Referencia:
    - [app/core/config.py](D:/vinevault/vinevault-core/app/core/config.py)

## 4. Topics Kafka que existen hoy

En este repo el flujo Kafka visible hoy es mucho mas chico que en el proyecto original.

- `vinevault.provisioning.devices.changed`
  - Publicado por el core.
  - Se emite cuando un device cambia en provisioning:
    - seed inicial
    - pairing
    - claim
    - reset
    - rename
  - Payload base:
    - `device_id`
    - `hardware_id`
    - `api_key`
    - `status`
  - Referencias:
    - [app/device/infrastructure/kafka/device_event_publisher.py](D:/vinevault/vinevault-core/app/device/infrastructure/kafka/device_event_publisher.py)
    - [app/device/applications/command_handlers/device_command_handler.py](D:/vinevault/vinevault-core/app/device/applications/command_handlers/device_command_handler.py)
    - [app/main.py](D:/vinevault/vinevault-core/app/main.py)

- `vinevault.device.commands.acknowledged`
  - Publicado por el core.
  - Se emite cuando el edge confirma `SENT`, `EXECUTED` o `FAILED` de un comando.
  - Payload base:
    - `device_id`
    - `hardware_id`
    - `command_id`
    - `status`
    - `failure_reason`
    - `acknowledged_at`
  - Referencias:
    - [app/device/infrastructure/kafka/device_event_publisher.py](D:/vinevault/vinevault-core/app/device/infrastructure/kafka/device_event_publisher.py)
    - [app/device/applications/command_handlers/__init__.py](D:/vinevault/vinevault-core/app/device/applications/command_handlers/__init__.py)

- `vinevault.device.commands.pending`
  - Publicado por el core.
  - Se emite cuando un usuario crea un comando para un device.
  - Payload base:
    - `command_id`
    - `device_id`
    - `hardware_id`
    - `command_type`
    - `payload`
    - `issued_at`
  - Referencias:
    - [app/device/infrastructure/kafka/device_event_publisher.py](D:/vinevault/vinevault-core/app/device/infrastructure/kafka/device_event_publisher.py)
    - [app/device/interfaces/rest/controllers/device_controller.py](D:/vinevault/vinevault-core/app/device/interfaces/rest/controllers/device_controller.py)

- `vinevault.device.presence.changed`
  - Publicado por el core.
  - Se emite cuando el edge reporta el estado de presencia de un device.
  - Payload base:
    - `device_id`
    - `hardware_id`
    - `status`
    - `occurred_at`
  - Referencias:
    - [app/device/infrastructure/kafka/device_event_publisher.py](D:/vinevault/vinevault-core/app/device/infrastructure/kafka/device_event_publisher.py)
    - [app/device/applications/command_handlers/device_presence_command_handler.py](D:/vinevault/vinevault-core/app/device/applications/command_handlers/device_presence_command_handler.py)

- `vinevault.device.telemetry.recorded`
  - Publicado por el core.
  - Se emite cuando el edge registra una observacion de telemetry.
  - Payload base:
    - `telemetry_id`
    - `device_id`
    - `hardware_id`
    - `assignment_id`
    - `space_id`
    - `source`
    - `payload`
    - `occurred_at`
  - Referencias:
    - [app/device/infrastructure/kafka/device_event_publisher.py](D:/vinevault/vinevault-core/app/device/infrastructure/kafka/device_event_publisher.py)
    - [app/telemetry/applications/command_handlers/telemetry_command_handler.py](D:/vinevault/vinevault-core/app/telemetry/applications/command_handlers/telemetry_command_handler.py)

Notas:

- Si `KAFKA_BOOTSTRAP_SERVERS` esta vacio, el publisher queda deshabilitado y los eventos se omiten sin romper el flujo REST.
- Ahora si hay un topic dedicado para telemetry en este core.

## 5. Contratos de payload

### Device changed

Payload actual del publisher:

- `device_id`
- `hardware_id`
- `api_key`
- `status`

Referencias:
- [app/device/infrastructure/kafka/device_event_publisher.py](D:/vinevault/vinevault-core/app/device/infrastructure/kafka/device_event_publisher.py)

### Pair request

- `hardware_id`

Referencia:
- [app/device/interfaces/rest/resources/request_models.py](D:/vinevault/vinevault-core/app/device/interfaces/rest/resources/request_models.py)

### Claim request

- `claim_token`
- `space_id`

Referencia:
- [app/device/interfaces/rest/resources/request_models.py](D:/vinevault/vinevault-core/app/device/interfaces/rest/resources/request_models.py)

### Create device command

- `type`
- `payload`

Referencia:
- [app/device/interfaces/rest/resources/request_models.py](D:/vinevault/vinevault-core/app/device/interfaces/rest/resources/request_models.py)

### Threshold update

- `metric`
- `value`
- `enabled`

Referencia:
- [app/device/interfaces/rest/resources/request_models.py](D:/vinevault/vinevault-core/app/device/interfaces/rest/resources/request_models.py)

## 6. Diferencias clave vs el spec original

1. La autenticacion del edge no usa `X-Edge-Token`; usa `Authorization: Bearer <edge_api_key>`.
2. `vinevault-core` si tiene un flujo completo de pairing/claim, thresholds, organizations, spaces, telemetry y wine cellar.
3. El topic de provisioning real es `vinevault.provisioning.devices.changed`, no `clair.provisioning.devices.changed`.

## 7. Contrato minimo para integrar edge con este core

Si el edge necesita hablar con el core hoy, el minimo viable es:

1. Autenticarse contra el core con su api key via `Authorization: Bearer <edge_api_key>`.
2. Consumir `GET /api/v1/edges/devices` para sincronizar inventario.
3. Usar `POST /api/v1/devices/pair` y `POST /api/v1/devices/claim` para activar devices.
4. Leer y escribir thresholds desde `GET/POST/PUT/PATCH/DELETE /api/v1/devices/{device_id}/thresholds`.
5. Escuchar el topic `vinevault.provisioning.devices.changed` si necesita reaccionar a cambios de provisioning.

## 8. Puntos a validar

1. Si el edge necesita un contrato mas estricto para el `payload` de telemetry, conviene versionar ese esquema por separado.
2. Si se quiere compatibilidad con el spec viejo, habria que crear un adaptador o un endpoint nuevo; hoy no existe.
3. Si `wine cellar` forma parte del edge flow real, conviene documentar sus eventos y reglas aparte porque ya esta embebido en el core.
