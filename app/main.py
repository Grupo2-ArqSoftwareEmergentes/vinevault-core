from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

from .core.config import settings
from .core.database import init_db, close_db
from .iam import router as iam_router
from .shared.exceptions import setup_exception_handlers
from .device.interfaces.rest.controllers.device_controller import router as device_router
from .device.interfaces.rest.controllers.organization_controller import router as organization_router
from .device.interfaces.rest.controllers.space_controller import router as space_router
from .device.interfaces.rest.controllers.threshold_controller import router as threshold_router

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown events"""
    logger.info(f"Starting up {settings.SERVICE_NAME}...")
    
    # Inicializar base de datos
    await init_db()
    logger.info("Database initialized")
    
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

@app.get("/")
async def root():
    return {
        "service": settings.SERVICE_NAME,
        "version": settings.SERVICE_VERSION,
        "environment": settings.ENVIRONMENT,
        "docs": "/docs",
        "health": "/api/v1/iam/health"
    }
