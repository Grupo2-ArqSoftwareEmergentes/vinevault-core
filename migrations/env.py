import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.database import Base, _build_engine_url, _build_connect_args
from app.iam import models as _iam
from app.device.infrastructure.database import models as _device
from app.wine_cellar.infrastructure.database import models as _wine
from app.telemetry.infrastructure.database import models as _telemetry
from app.shared.infrastructure.database import models as _shared
from app.subscriptions.infrastructure.database import models as _subscriptions


def run_migrations(connection):
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_online():
    engine = create_async_engine(_build_engine_url(), connect_args=_build_connect_args())
    try:
        async with engine.connect() as connection:
            await connection.run_sync(run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("This data migration requires an online PostgreSQL connection")
elif context.config.attributes.get("connection") is not None:
    run_migrations(context.config.attributes["connection"])
else:
    asyncio.run(run_online())
