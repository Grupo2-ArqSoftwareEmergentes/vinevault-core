# Vinevault Core

Backend de Vinevault con FastAPI y PostgreSQL. Esta guía ejecuta la infraestructura en Docker Desktop y el backend directamente en tu equipo.

## Requisitos

- Python 3.11 y `pip`.
- Docker Desktop iniciado, con contenedores Linux y Docker Compose disponibles.
- Puertos libres: `5432` para PostgreSQL, `8000` para la API y `9092` si usas Kafka.
- Para integración con Kafka, el repositorio `vinevault-edge` debe estar junto a `vinevault-core`.

Los comandos siguientes son para **PowerShell**, ejecutados desde la raíz de `vinevault-core`.

## 1. Preparar Python

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Si ya tienes el entorno `venv`, no necesitas crearlo de nuevo. Si PowerShell bloquea su activación, usa directamente el intérprete: `.\venv\Scripts\python.exe -m pip install -r requirements.txt`.

## 2. Configurar el entorno

Crea `.env` solo si todavía no existe:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Revisa que contenga estos valores para la infraestructura local:

```dotenv
DATABASE_URL=
DATABASE_HOST=localhost
DATABASE_PORT=5432
DATABASE_NAME=vinevault_core_db
DATABASE_USER=postgres
DATABASE_PASSWORD=postgres
DATABASE_SSL=false
ENVIRONMENT=development
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
KAFKA_CONSUMER_GROUP_ID=vinevault-core
```

Deja `DATABASE_URL` vacío: si tiene un valor, prevalece sobre los componentes `DATABASE_HOST`, `DATABASE_NAME`, etc. Define también tu propio `SECRET_KEY` en `.env`; no publiques credenciales.

## 3. Levantar la infraestructura

### PostgreSQL (necesario)

```powershell
docker compose -f docker-compose-test.yml up -d --wait
```

Este archivo levanta **solo PostgreSQL 15**, no el backend ni una suite de tests. La base de datos se conserva en un volumen Docker.

### Kafka (para integración Core–Edge)

```powershell
docker compose -f ..\vinevault-edge\docker-compose.yml up -d
docker exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list
```

El segundo comando permite comprobar que el broker responde; un listado vacío es normal al principio. Si todavía está arrancando, vuelve a intentarlo unos segundos después.

Se usa el compose principal del Edge porque anuncia `localhost:9092`. No uses su `docker-compose-test.yml` sin adaptarlo: anuncia una IP fija de red. No levantes ambos a la vez, ya que comparten nombre de contenedor y puerto. Este Kafka no tiene un volumen persistente configurado.

**Si solo necesitas probar REST**, omite Kafka y deja en `.env`:

```dotenv
KAFKA_BOOTSTRAP_SERVERS=
```

Esto deshabilita el productor y el consumidor Kafka. No permite verificar los flujos de eventos Core–Edge.

## 4. Iniciar el backend Core

Antes de iniciar una versión con cambios de esquema, respalda la base y ejecuta la migración con las instancias del backend detenidas:

```powershell
.\venv\Scripts\python.exe -m alembic upgrade head
```

La migración añade planes/tipos por espacio y convierte propietarios existentes en miembros OWNER. Si detecta propietarios sin identidad válida, se detiene sin reasignar datos. Revisa el destino de `.env` antes de ejecutarla. Detalles: [docs/space-tenancy.md](docs/space-tenancy.md).

Con el entorno virtual activado:

```powershell
python run.py
```

Sin activar el entorno virtual:

```powershell
.\venv\Scripts\python.exe run.py
```

El backend carga `.env` y arranca `app.main:app` en el puerto **8000**, con recarga automática para desarrollo.

> **Atención:** usa una base local de pruebas. Al iniciar, el backend crea las tablas faltantes y ejecuta seeds de dispositivos. También elimina registros de edges cuyos nombres no estén en `EDGE_DEVICE_SEEDS` de `app/main.py`, restablece las claves de los dos edges predefinidos y los reactiva. Esto sucede incluso en modo producción. La creación de tablas no migra tablas existentes si cambia el esquema.

## 5. Comprobar que funciona

- Swagger y pruebas de endpoints: <http://localhost:8000/docs>
- Información del servicio: <http://localhost:8000/>
- Health básico: <http://localhost:8000/api/v1/iam/health>

```powershell
Invoke-RestMethod http://localhost:8000/api/v1/iam/health
```

Para probar rutas autenticadas, registra un usuario desde Swagger y usa el login de IAM. El login recibe `username` y `password` como formulario, no JSON. Los endpoints de usuario usan `Authorization: Bearer <jwt>`; los endpoints de edge usan `Authorization: Bearer <edge_api_key>`.

El health no verifica Kafka: los errores de arranque del broker se registran sin impedir necesariamente el funcionamiento REST. Para pruebas de integración, comprueba los logs y los eventos. Los contratos están en [edge-core-integration-spec.md](edge-core-integration-spec.md) y [core-edge-topic-contract.md](core-edge-topic-contract.md).

## Navegación personal y selector global

Las rutas mantienen el prefijo real del proyecto, `/api/v1`, y el término `wine-cellars` para cavas. Todas las rutas siguientes requieren `Authorization: Bearer <jwt>` del usuario:

| Operación | Endpoint |
|---|---|
| Crear un espacio sin formulario de organización | `POST /api/v1/spaces` con `{"name":"Casa"}` |
| Onboarding con propósito explícito | `POST /api/v1/user/onboarding` con `{"name":"Casa","space_type":"COLLECTOR"}` |
| Listar espacios propios | `GET /api/v1/spaces` |
| Eliminar un espacio y todas sus cavas e inventarios | `DELETE /api/v1/spaces/<uuid>` |
| Obtener espacios y cavas para el selector | `GET /api/v1/user/context` |
| Listar todas las cavas propias | `GET /api/v1/wine-cellars` |
| Filtrar cavas por espacio | `GET /api/v1/wine-cellars?spaceId=<uuid>` (también acepta `space_id`) |
| Crear una cava en un espacio propio | `POST /api/v1/spaces/<uuid>/wine-cellars` con `{"name":"Mi cava"}` |

Al crear un espacio por la ruta directa se reutiliza la organización más antigua del usuario (desempate por ID); si no existe, se crea `Organización Personal`. Ambas rutas de creación de espacios (`POST /api/v1/spaces` y `POST /api/v1/organizations/{organization_id}/spaces`) crean también exactamente una **Cava Principal**, con descripción `Cava inicial creada automáticamente` y sin dispositivo vinculado.

La organización nueva (si aplica), el espacio, la membresía OWNER y su cava se guardan en una única transacción: si falla cualquier paso, se revierte todo. El espacio nace FREE/ACTIVE y admite propósito COLLECTOR o BUSINESS. Las cuentas existentes necesitan la migración descrita arriba; no se agregan cavas retroactivamente a espacios ya existentes.

La respuesta `201` conserva los campos del espacio y agrega `default_wine_cellar`, con los campos habituales de `WineCellarResponse`: `id`, `space_id`, `name`, `description`, `device_id`, `created_at` y `updated_at`. El frontend puede usar directamente `response.id` y `response.default_wine_cellar.id` para autoseleccionar ambos y actualizar el selector, sin recargar la página ni crear otra cava manualmente. `GET /api/v1/user/context` también refleja la cava después del commit; su contrato no cambia.

El contexto es de solo lectura e incluye espacios/cavas donde el usuario es miembro, aunque no sea el creador. Devuelve listas vacías para cuentas sin membresías. Se conserva el límite legacy de cinco espacios por organización; no es un plan global del usuario. El plan/estado pertenece a cada espacio; todavía no se integra cobro ni se añaden cuotas comerciales por cantidad de cavas.

El contexto usa una validación de identidad y dos consultas de directorio, sin N+1 por espacio:

```json
{
  "spaces": [{"id": "<uuid-espacio>", "name": "Casa", "space_type": "COLLECTOR", "subscription_plan": "FREE", "subscription_status": "ACTIVE", "role": "OWNER"}],
  "wine_cellars": [{"id": "<uuid-cava>", "name": "Mi cava", "space_id": "<uuid-espacio>"}]
}
```

Las rutas anteriores siguen disponibles. La autorización se basa en `space_members`, no en `owner_user_id`. Contrato de onboarding, roles y migración: [docs/space-tenancy.md](docs/space-tenancy.md).

### Eliminación de espacios

`DELETE /api/v1/spaces/{space_id}` permite eliminar espacios vacíos o con cavas. El backend valida al propietario y elimina **todos los inventarios de sus cavas, las cavas y el espacio**, en una única transacción. Responde `204 No Content`; no elimina la organización ni afecta otros espacios. Si hay dispositivos asignados al espacio, mantiene `409` con `detail: "Space has devices"`; primero deben desvincularse mediante el flujo existente.

El frontend debe pedir confirmación antes de enviar el DELETE, indicando que se eliminarán también las cavas y su inventario. No necesita borrar cada cava por separado ni enviar un parámetro de confirmación. Tras `204`, debe limpiar la selección si corresponde y actualizar el contexto global. Un fallo de la transacción revierte toda la eliminación. No es necesario cambiar las foreign keys de bases existentes.

## Pruebas de contexto personal

Con PostgreSQL local iniciado y las dependencias instaladas:

```powershell
$env:TEST_DATABASE_URL='postgresql+asyncpg://postgres:postgres@localhost:5432/vinevault_core_db'
.\venv\Scripts\python.exe -B -m unittest discover -s tests -p test_personal_context.py -v
```

Las pruebas crean y eliminan un esquema temporal único por caso; no usan las tablas existentes ni ejecutan el arranque/seeds de la aplicación. El usuario de pruebas necesita permisos para crear esquemas. Sin `TEST_DATABASE_URL`, las pruebas se omiten. Cubren JWT, aislamiento entre usuarios, filtros, compatibilidad de rutas, integridad referencial, creación concurrente sin duplicar organizaciones, una cava inicial por espacio y rollback completo ante fallos posteriores a la inserción de la cava.

## Análisis de inventario con IA

`POST /api/v1/ai/analyze-stock` conserva la respuesta JSON existente y omite Google cuando la cava no tiene registros de inventario. Para resultados incrementales, solicitar `Accept: text/event-stream` o `?stream=true`; el frontend debe procesar eventos SSE. Configuración, errores y contrato de integración: [docs/inventory-ai.md](docs/inventory-ai.md).

## Detener los servicios

Detén la API con `Ctrl+C`. Para detener la infraestructura sin eliminar sus contenedores ni volúmenes:

```powershell
docker compose -f docker-compose-test.yml stop
docker compose -f ..\vinevault-edge\docker-compose.yml stop
```

No uses `down -v` si quieres conservar los datos de PostgreSQL.

## Sobre el compose de producción

`docker-compose-prod.yml` levanta PostgreSQL **y la API en un contenedor**. No es necesario para el flujo local anterior y no debe ejecutarse junto al compose de PostgreSQL de desarrollo: comparten nombre de contenedor y puerto. Además, `localhost:9092` dentro del contenedor de la API no apunta al Kafka de tu equipo; esa modalidad requiere adaptar la conectividad del broker.
