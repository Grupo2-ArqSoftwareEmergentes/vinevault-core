from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .core.config import settings
from .core.database import Base, engine
from .iam import router as iam_router
from .shared.exceptions import setup_exception_handlers

# Crear tablas
Base.metadata.create_all(bind=engine)

# Inicializar app
app = FastAPI(
    title="Microservicio IAM",
    version=settings.SERVICE_VERSION,
    description="Servicio de Autenticación y Autorización",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configurar en producción
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configurar manejadores de excepciones
setup_exception_handlers(app)

# Registrar routers
app.include_router(iam_router.router)

@app.get("/")
def root():
    return {
        "service": settings.SERVICE_NAME,
        "version": settings.SERVICE_VERSION,
        "environment": settings.ENVIRONMENT,
        "docs": "/docs",
        "health": "/api/v1/iam/health"
    }