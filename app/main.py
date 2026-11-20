from contextlib import asynccontextmanager
from pathlib import Path
import logging

from fastapi import FastAPI, Depends
from .core.space_security import authorize_inventory_autocomplete, authorize_space_request
from fastapi.middleware.cors import CORSMiddleware

from .core.config import settings
from .core.database import AsyncSessionLocal, close_db, init_db
from .device.applications.command_handlers import DeviceCommandServiceImpl
from .device.domain.commands import SeedDevicesCommand
from .device.domain.models import Device, EdgeDevice
from .device.domain.models.value_objects import ApiKey, DeviceType, HardwareId
from .device.infrastructure.database.repositories import (
    DeviceAssignmentRepository,
    DeviceRepository,
    EdgeDeviceRepository,
    SpaceRepository,
)
from .device.infrastructure.database import models as _device_models  # noqa: F401
from .device.infrastructure.kafka import KafkaDeviceEventPublisher
from .device.infrastructure.kafka.device_event_consumer import KafkaEdgeEventConsumer
from .shared.infrastructure.database import models as _shared_models  # noqa: F401
from .subscriptions.infrastructure.database import models as _subscription_models  # noqa: F401
from .shared.infrastructure.kafka import KafkaOutboxPublisher
from .device.interfaces.rest.controllers.device_controller import router as device_router
from .device.interfaces.rest.controllers.alert_controller import router as alert_router
from .device.interfaces.rest.controllers.edge_controller import router as edge_router
from .device.interfaces.rest.controllers.organization_controller import router as organization_router
from .device.interfaces.rest.controllers.space_controller import router as space_router
from .device.interfaces.rest.controllers.user_context_controller import router as user_context_router
from .device.interfaces.rest.controllers.threshold_controller import router as threshold_router
from .iam import router as iam_router
from .telemetry.infrastructure.database import models as _telemetry_models  # noqa: F401
from .telemetry.interfaces.rest.controllers.telemetry_controller import router as telemetry_router
from .shared.exceptions import setup_exception_handlers
from .wine_cellar.interfaces.rest.controllers.wine_cellar_controller import router as wine_cellar_router
from .wine_cellar.interfaces.rest.controllers.inventory_export_controller import router as inventory_export_router
from .inventory_intelligence.interfaces.rest.controllers.intelligence_controller import router as intelligence_router
from .inventory_intelligence.interfaces.rest.controllers.wine_autocomplete_controller import router as autocomplete_router
from .assistant.interfaces.rest.controllers.assistant_controller import router as assistant_router
from .subscriptions.interfaces.rest.controllers.subscription_controller import router as subscription_router

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("aiokafka").setLevel(logging.WARNING)
logging.getLogger("aiokafka.consumer").setLevel(logging.WARNING)
logging.getLogger("aiokafka.producer").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

FACTORY_DEVICES_FILE = Path(__file__).resolve().parent / "device" / "infrastructure" / "seeds" / "factory_devices.txt"
EDGE_DEVICE_SEEDS = (
    {"name": "edge-lab-1", "api_key": "edge-test-key-001"},
    {"name": "edge-lab-2", "api_key": "edge-test-key-002"},
)


async def seed_fixed_factory_devices(
    device_event_publisher: KafkaDeviceEventPublisher | None = None,
) -> None:
    """Seed the 5 fixed devices used as stable factory inventory."""
    if not FACTORY_DEVICES_FILE.exists():
        logger.warning("Fixed factory devices file not found: %s", FACTORY_DEVICES_FILE)
        return

    async with AsyncSessionLocal() as session:
        device_repo = DeviceRepository(session)
        seeded = 0
        for raw_line in FACTORY_DEVICES_FILE.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            serial_number, name, factory_name, hardware_id, device_type = [part.strip() for part in line.split("|")]
            if await device_repo.find_by_serial_number(serial_number):
                continue

            device = Device(
                serial_number=serial_number,
                name=name,
                factory_name=factory_name,
                hardware_id=HardwareId(value=hardware_id),
                api_key=ApiKey.generate(),
                device_type=DeviceType(value=device_type),
            )
            saved = await device_repo.save(device)
            if device_event_publisher is not None:
                await device_event_publisher.publish_device_changed(saved, change_type="CREATED")
            seeded += 1

        if seeded:
            logger.info("Seeded %s fixed factory devices", seeded)
        else:
            logger.info("Fixed factory devices already present, skipping seed")


async def seed_factory_devices(
    device_event_publisher: KafkaDeviceEventPublisher | None = None,
) -> None:
    """Create a minimal set of factory devices for frontend pairing flows."""
    async with AsyncSessionLocal() as session:
        service = DeviceCommandServiceImpl(
            device_repo=DeviceRepository(session),
            assignment_repo=DeviceAssignmentRepository(session),
            space_repo=SpaceRepository(session),
            device_event_publisher=device_event_publisher,
        )
        seeded = await service.handle_seed_devices(SeedDevicesCommand(count=2, start_index=6))
        if seeded:
            logger.info("Seeded %s factory devices", len(seeded))
        else:
            logger.info("Factory devices already present, skipping seed")


async def seed_edge_devices() -> None:
    """Seed two deterministic edge credentials for development and tests."""
    async with AsyncSessionLocal() as session:
        edge_repo = EdgeDeviceRepository(session)
        desired_names = {seed["name"] for seed in EDGE_DEVICE_SEEDS}
        existing_edge_devices = await edge_repo.find_all()

        for existing in existing_edge_devices:
            if existing.name not in desired_names:
                await edge_repo.delete(existing)

        for seed in EDGE_DEVICE_SEEDS:
            existing = await edge_repo.find_by_name(seed["name"])
            if existing is None:
                await edge_repo.save(
                    EdgeDevice(
                        name=seed["name"],
                        api_key=ApiKey(value=seed["api_key"]),
                        active=True,
                    )
                )
                logger.info("Seeded edge device %s", seed["name"])
                continue

            needs_update = existing.api_key.value != seed["api_key"] or not existing.active
            if needs_update:
                existing.rotate_api_key(ApiKey(value=seed["api_key"]))
                existing.active = True
                await edge_repo.save(existing)
                logger.info("Updated edge device %s", seed["name"])
            else:
                logger.info("Edge device %s already present, skipping seed", seed["name"])


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown events."""
    logger.info("Starting up %s...", settings.SERVICE_NAME)

    device_event_publisher = KafkaDeviceEventPublisher(settings.KAFKA_BOOTSTRAP_SERVERS)
    device_event_consumer = KafkaEdgeEventConsumer(
        settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id=settings.KAFKA_CONSUMER_GROUP_ID,
        device_event_publisher=device_event_publisher,
    )
    outbox_publisher = KafkaOutboxPublisher(device_event_publisher=device_event_publisher)
    await device_event_publisher.start()
    app.state.device_event_publisher = device_event_publisher
    app.state.device_event_consumer = device_event_consumer
    app.state.outbox_publisher = outbox_publisher

    try:
        await init_db()
        logger.info("Database initialized")

        await seed_fixed_factory_devices(device_event_publisher)
        await seed_factory_devices(device_event_publisher)
        await seed_edge_devices()
        await outbox_publisher.start()
        await device_event_consumer.start()

        yield
    finally:
        logger.info("Shutting down %s...", settings.SERVICE_NAME)
        await device_event_consumer.stop()
        await outbox_publisher.stop()
        await device_event_publisher.stop()
        await close_db()
        logger.info("Shutdown complete")


app = FastAPI(
    title=settings.SERVICE_NAME,
    version=settings.SERVICE_VERSION,
    description="Backend core de Vinevault",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS_LIST,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

setup_exception_handlers(app)

app.include_router(iam_router.router)
app.include_router(device_router, dependencies=[Depends(authorize_space_request)])
app.include_router(alert_router, dependencies=[Depends(authorize_space_request)])
app.include_router(edge_router)
app.include_router(organization_router)
app.include_router(space_router, dependencies=[Depends(authorize_space_request)])
app.include_router(user_context_router, dependencies=[Depends(authorize_space_request)])
app.include_router(threshold_router, dependencies=[Depends(authorize_space_request)])
app.include_router(telemetry_router)
app.include_router(wine_cellar_router, dependencies=[Depends(authorize_space_request)])
app.include_router(inventory_export_router, dependencies=[Depends(authorize_space_request)])
app.include_router(intelligence_router, dependencies=[Depends(authorize_space_request)])
app.include_router(autocomplete_router, dependencies=[Depends(authorize_inventory_autocomplete)])
app.include_router(assistant_router)
app.include_router(subscription_router)


@app.get("/")
async def root():
    return {
        "service": settings.SERVICE_NAME,
        "version": settings.SERVICE_VERSION,
        "environment": settings.ENVIRONMENT,
        "docs": "/docs",
        "health": "/api/v1/iam/health",
    }
