import ssl
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import inspect
from .config import settings


def _build_engine_url() -> str:
    url = settings.ASYNC_DATABASE_URL
    parts = urlsplit(url)
    # asyncpg does not understand psycopg-style query parameters like sslmode.
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _build_connect_args() -> dict:
    if not settings.DATABASE_SSL:
        return {}
    return {"ssl": ssl.create_default_context()}


# Usar la propiedad ASYNC_DATABASE_URL
engine = create_async_engine(
    _build_engine_url(),
    connect_args=_build_connect_args(),
    echo=settings.SQLALCHEMY_ECHO,
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
        def validate_existing_schema(connection):
            inspector = inspect(connection)
            tables = set(inspector.get_table_names())
            if "users" in tables and "subscription_intents" not in tables:
                raise RuntimeError("Database migration required: python -m alembic upgrade head")
            if "subscription_intents" in tables and "active_subscriptions" not in tables:
                raise RuntimeError("Database migration required: python -m alembic upgrade head")
            if "users" in tables and not {"full_name", "extra_spaces_allowance", "preferred_language"}.issubset({c["name"] for c in inspector.get_columns("users")}):
                raise RuntimeError("Database migration required: python -m alembic upgrade head")
            if "spaces" in tables:
                columns = {c["name"] for c in inspector.get_columns("spaces")}
                if "space_members" not in tables or not {"space_type", "subscription_plan", "subscription_status", "extra_cellars_allowance"}.issubset(columns):
                    raise RuntimeError("Database migration required: python -m alembic upgrade head")
            if "wine_inventory_items" in tables:
                from app.wine_cellar.domain.models.wine_item_details import WineItemDetails
                columns = {c["name"] for c in inspector.get_columns("wine_inventory_items")}
                if "wine_stock_movements" not in tables or not {"name", *WineItemDetails.model_fields}.issubset(columns):
                    raise RuntimeError("Database migration required: python -m alembic upgrade head")
        await conn.run_sync(validate_existing_schema)
        await conn.run_sync(Base.metadata.create_all)

async def close_db():
    """Cerrar conexión a base de datos"""
    await engine.dispose()
