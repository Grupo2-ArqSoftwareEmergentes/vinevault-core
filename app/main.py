from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging
from pathlib import Path

from .core.config import settings
from .core.database import init_db, close_db, AsyncSessionLocal
from .iam import router as iam_router
from .shared.exceptions import setup_exception_handlers
from .device.applications.command_handlers import DeviceCommandServiceImpl
from .device.domain.commands import SeedDevicesCommand
from .device.domain.models import Device
from .device.domain.models.value_objects import ApiKey, DeviceType, HardwareId
from .device.infrastructure.database.repositories import (
    DeviceRepository,
    DeviceAssignmentRepository,
    SpaceRepository,
)
from .device.interfaces.rest.controllers.device_controller import router as device_router
from .device.interfaces.rest.controllers.organization_controller import router as organization_router
from .device.interfaces.rest.controllers.space_controller import router as space_router
from .device.interfaces.rest.controllers.threshold_controller import router as threshold_router
from .wine_cellar.interfaces.rest.controllers.wine_cellar_controller import router as wine_cellar_router

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)
FACTORY_DEVICES_FILE = Path(__file__).resolve().parent / "device" / "infrastructure" / "seeds" / "factory_devices.txt"


async def seed_fixed_factory_devices() -> None:
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
            await device_repo.save(device)
            seeded += 1

        if seeded:
            logger.info("Seeded %s fixed factory devices", seeded)
        else:
            logger.info("Fixed factory devices already present, skipping seed")


async def seed_factory_devices() -> None:
    """Create a minimal set of factory devices for frontend pairing flows."""
    async with AsyncSessionLocal() as session:
        service = DeviceCommandServiceImpl(
            device_repo=DeviceRepository(session),
            assignment_repo=DeviceAssignmentRepository(session),
            space_repo=SpaceRepository(session),
        )
        seeded = await service.handle_seed_devices(SeedDevicesCommand(count=2, start_index=6))
        if seeded:
            logger.info("Seeded %s factory devices", len(seeded))
        else:
            logger.info("Factory devices already present, skipping seed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown events"""
    logger.info(f"Starting up {settings.SERVICE_NAME}...")
    
    # Inicializar base de datos
    await init_db()
    logger.info("Database initialized")

    # Seed inicial de devices factory para el flujo de pairing del front
    await seed_fixed_factory_devices()
    await seed_factory_devices()
    
    # Iniciar consumidores Kafka (si existen)
    # await start_consumers()
    # logger.info("Kafka consumers started")
    
    yield
    
    # Shutdown
    logger.info(f"Shutting down {settings.SERVICE_NAME}...")
    await close_db()
    logger.info("Shutdown complete")


# Inicializar app
app = FastAPI(
    title=settings.SERVICE_NAME,
    version=settings.SERVICE_VERSION,
    description="Backend core de Vinevault",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200"],  # Configurar en producción
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configurar manejadores de excepciones
setup_exception_handlers(app)

# Registrar routers
app.include_router(iam_router.router)
app.include_router(device_router)
app.include_router(organization_router)
app.include_router(space_router)
app.include_router(threshold_router)
app.include_router(wine_cellar_router)

@app.get("/")
async def root():
    return {
        "service": settings.SERVICE_NAME,
        "version": settings.SERVICE_VERSION,
        "environment": settings.ENVIRONMENT,
        "docs": "/docs",
        "health": "/api/v1/iam/health"
    }
