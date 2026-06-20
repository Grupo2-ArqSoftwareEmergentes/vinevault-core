from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from .config import settings

# Usar la propiedad ASYNC_DATABASE_URL
engine = create_async_engine(
    settings.ASYNC_DATABASE_URL,
    echo=settings.ENVIRONMENT == "development",
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

Base = declarative_base()

async def get_db():
    """Obtener sesión de base de datos asíncrona"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

async def init_db():
    """Inicializar base de datos (crear tablas)"""
    async with engine.begin() as conn:
        # En producción usar migraciones Alembic
        await conn.run_sync(Base.metadata.create_all)

async def close_db():
    """Cerrar conexión a base de datos"""
    await engine.dispose()
