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
| Listar espacios propios | `GET /api/v1/spaces` |
| Obtener espacios y cavas para el selector | `GET /api/v1/user/context` |
| Listar todas las cavas propias | `GET /api/v1/wine-cellars` |
| Filtrar cavas por espacio | `GET /api/v1/wine-cellars?spaceId=<uuid>` (también acepta `space_id`) |
| Crear una cava en un espacio propio | `POST /api/v1/spaces/<uuid>/wine-cellars` con `{"name":"Mi cava"}` |

Al crear un espacio por la ruta directa se reutiliza la organización más antigua del usuario (desempate por ID); si no existe, se crea `Organización Personal` en la misma transacción que el espacio. No hace falta inicialización previa ni cambiar las cuentas existentes. El contexto es de solo lectura y devuelve listas vacías para cuentas sin espacios. Se conserva el límite de cinco espacios por organización; no se crea otra organización automáticamente para eludirlo.

El contexto usa dos consultas, sin una consulta adicional por espacio, y tiene esta forma:

```json
{
  "spaces": [{"id": "<uuid-espacio>", "name": "Casa"}],
  "wine_cellars": [{"id": "<uuid-cava>", "name": "Mi cava", "space_id": "<uuid-espacio>"}]
}
```

Las rutas anteriores de organizaciones y espacios anidados siguen disponibles. No se modifican las foreign keys ni se necesita una migración para estas rutas.

## Pruebas de contexto personal

Con PostgreSQL local iniciado y las dependencias instaladas:

```powershell
$env:TEST_DATABASE_URL='postgresql+asyncpg://postgres:postgres@localhost:5432/vinevault_core_db'
.\venv\Scripts\python.exe -B -m unittest discover -s tests -p test_personal_context.py -v
```

Las pruebas crean y eliminan un esquema temporal único por caso; no usan las tablas existentes ni ejecutan el arranque/seeds de la aplicación. El usuario de pruebas necesita permisos para crear esquemas. Sin `TEST_DATABASE_URL`, las pruebas se omiten. Cubren JWT, aislamiento entre usuarios, filtros, compatibilidad de rutas, integridad referencial y creación concurrente sin duplicar organizaciones.

## Detener los servicios

Detén la API con `Ctrl+C`. Para detener la infraestructura sin eliminar sus contenedores ni volúmenes:

```powershell
docker compose -f docker-compose-test.yml stop
docker compose -f ..\vinevault-edge\docker-compose.yml stop
```

No uses `down -v` si quieres conservar los datos de PostgreSQL.

## Sobre el compose de producción

`docker-compose-prod.yml` levanta PostgreSQL **y la API en un contenedor**. No es necesario para el flujo local anterior y no debe ejecutarse junto al compose de PostgreSQL de desarrollo: comparten nombre de contenedor y puerto. Además, `localhost:9092` dentro del contenedor de la API no apunta al Kafka de tu equipo; esa modalidad requiere adaptar la conectividad del broker.
