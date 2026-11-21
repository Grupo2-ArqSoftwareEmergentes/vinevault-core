# Vinevault Core <-> Edge Kafka Contract

Este documento resume lo que el `edge` espera recibir y enviar por Kafka para que `vinevault-core` pueda integrarse correctamente.

## Topics que consume el edge

| Topic | Dirección | Qué espera el edge | Campos obligatorios | Campos recomendados | Key Kafka sugerida |
|---|---|---|---|---|---|
| `vinevault.device.alert.incident.changed` | Core -> Edge | El edge lo consume para guardar incidentes de alerta y exponerlos luego al device local. | `hardware_id`, `occurred_at` | `alert_id`, `device_id`, `space_id`, `metric`, `threshold_value`, `actual_value`, `message`, `status`, `resolved_at` | `hardware_id` |
| `vinevault.provisioning.devices.changed` | Core -> Edge | El edge lo consume para sincronizar su caché local de devices. | `device_id`, `hardware_id`, `api_key`, `status` | `change_type`, `changed_at` | `hardware_id` o `device_id` |
| `vinevault.device.commands.pending` | Core -> Edge | El edge lo consume para recibir comandos pendientes para un device. | `command_id`, `device_id`, `type` | `hardware_id`, `payload`, `issued_at` | `hardware_id` o `device_id` |

## Topics que publica el edge

| Topic | Dirección | Qué envía el edge | Campos obligatorios | Campos recomendados | Key Kafka sugerida |
|---|---|---|---|---|---|
| `vinevault.device.presence.changed` | Edge -> Core | El edge lo publica cuando un device cambia de estado de presencia. | `device_id`, `hardware_id`, `status`, `occurred_at` | ninguno extra necesario | `hardware_id` |
| `vinevault.device.commands.acknowledged` | Edge -> Core | El edge lo publica cuando confirma ejecución o fallo de un comando. | `device_id`, `hardware_id`, `command_id`, `status`, `acknowledged_at` | `failure_reason` si `status = FAILED` | `command_id` |
| `vinevault.device.telemetry.recorded` | Edge -> Core | El edge lo publica con la telemetría normalizada del device. | `device_id`, `device_time`, `uptime_seconds`, `co2`, `temperature`, `humidity`, `wifi_status`, `network_name`, `signal_strength`, `country`, `health_status`, `status`, `recorded_at`, `occurred_at` | `hardware_id` | `hardware_id` |
| `vinevault.provisioning.devices.sync.requested` | Edge -> Core | El edge lo publica al arrancar o para pedir resync completo del inventario. | `edge_instance_id`, `requested_at` | ninguno extra necesario | `edge_instance_id` |

## Reglas de interoperabilidad

- Las alertas se evalúan por asignación/espacio aun sin cava. La nueva consulta REST `GET /api/v1/alerts?space_id={UUID}` enriquece la asociación actual de cava y localiza mensajes sin alterar el payload del topic de alertas; los consumidores Edge no requieren cambios.

- `PUT /api/v1/devices/{id}/cellar` cambia o elimina únicamente la asociación de cava en Core. No desasigna el sensor de su espacio ni cambia API keys, estado operativo o payloads de provisioning/comandos. No se requieren cambios en el publicador/consumidor Edge por el selector rápido del frontend.

- La selección opcional de cava en `/devices/claim` y los campos REST `cellar_id`/`cellar_name` son metadatos de usuario de Core. La vinculación queda en `wine_cellars.device_id` y no añade campos obligatorios ni cambia el esquema de los eventos de provisioning/comandos/telemetría. Edge no necesita una modificación para este flujo.

- La conectividad visible en Core se evalúa por actividad UTC de hasta 5 minutos (`is_online` en REST de usuario y respuesta de presencia). Telemetría REST y `vinevault.device.telemetry.recorded` actualizan la última actividad mediante el mismo servicio. RSSI bajo no significa desconexión. Los eventos conservan sus campos actuales, sin exigir cambios al publicador Edge. La intención explícita STANDBY de Core bloquea la reactivación por telemetría/presencia hasta un comando WAKE y nueva actividad; no confundir el estado operativo del evento con el booleano de frescura calculado al consultar.

- Los permisos de usuarios del Core se validan ahora por membresía/rol del espacio. Esto no cambia la autenticación API-key del Edge ni los campos Kafka de propietario existentes, que siguen siendo metadatos legacy y no una autorización de usuario.

- El edge acepta algunos payloads en `snake_case` y también en `camelCase`, especialmente en provisioning e incidents.
- En `vinevault.provisioning.devices.changed`, el edge valida que existan al menos `device_id`, `hardware_id`, `api_key` y `status`.
- El seed Core normaliza `SN-0001`..`SN-0050` a `VINE-A001`..`VINE-A050` (incluidos 6/7). Publica los cambios conservando `device_id` y API key: el repositorio de caché de Edge hace upsert por `device_id` y actualiza `hardware_id`, sin crear otra identidad. No cambia el formato del evento. Simuladores/firmware deben actualizar el hardware ID local; si Kafka no estuvo disponible, solicitar `vinevault.provisioning.devices.sync.requested` para refrescar la caché. Las pruebas del seed simulan el publicador, no acreditan entrega real por Kafka.
- En `vinevault.device.commands.pending`, el edge resuelve el comando por `device_id` y luego lo asocia con `hardware_id`.
- Para `vinevault.device.commands.acknowledged`, si `status = FAILED`, conviene enviar `failure_reason` explícitamente.
- Para `vinevault.device.telemetry.recorded`, el edge normaliza la telemetría local y la reenvía con `hardware_id` como key Kafka.
- Para `vinevault.device.presence.changed`, el edge publica transiciones de estado como `ONLINE`, `OFFLINE`, `STANDBY` o `ERROR`.

## Referencias del edge

- [`alerting/application/services/alert_incident_event_application_service.py`](../alerting/application/services/alert_incident_event_application_service.py)
- [`provisioning/application/services/device_provisioning_application_service.py`](../provisioning/application/services/device_provisioning_application_service.py)
- [`device/application/services.py`](../device/application/services.py)
- [`iam/application/services.py`](../iam/application/services.py)
- [`device/application/outboundservices/acl/kafka_core_context_facade.py`](../device/application/outboundservices/acl/kafka_core_context_facade.py)
- [`iam/application/outboundservices/acl/kafka_presence_publisher.py`](../iam/application/outboundservices/acl/kafka_presence_publisher.py)
