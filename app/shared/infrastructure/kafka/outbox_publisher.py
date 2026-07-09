import asyncio
import logging
from contextlib import suppress
from datetime import datetime
from typing import Optional

from app.core.database import AsyncSessionLocal
from app.device.infrastructure.kafka.device_event_publisher import KafkaDeviceEventPublisher
from app.shared.infrastructure.database.repositories import IntegrationOutboxRepository

logger = logging.getLogger(__name__)


class KafkaOutboxPublisher:
    def __init__(
        self,
        *,
        device_event_publisher: KafkaDeviceEventPublisher,
        poll_interval_seconds: float = 1.0,
        batch_size: int = 20,
    ) -> None:
        self._device_event_publisher = device_event_publisher
        self._poll_interval_seconds = poll_interval_seconds
        self._batch_size = batch_size
        self._task: Optional[asyncio.Task[None]] = None
        self._started = False

    async def start(self) -> None:
        if self._started:
            return

        self._task = asyncio.create_task(self._run())
        self._started = True
        logger.info("Kafka outbox publisher started")

    async def stop(self) -> None:
        task = self._task
        self._task = None
        self._started = False

        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def _run(self) -> None:
        try:
            while True:
                processed = await self._flush_once()
                if processed == 0:
                    await asyncio.sleep(self._poll_interval_seconds)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Kafka outbox publisher loop crashed")

    async def _flush_once(self) -> int:
        processed = 0
        async with AsyncSessionLocal() as session:
            repo = IntegrationOutboxRepository(session)
            pending = await repo.fetch_pending(limit=self._batch_size)
            for event in pending:
                try:
                    await self._device_event_publisher.publish_payload(
                        event.payload,
                        topic=event.topic,
                        key=event.message_key,
                    )
                    await repo.mark_published(event.id, published_at=datetime.utcnow())
                    processed += 1
                except Exception as exc:
                    logger.exception(
                        "Failed to publish outbox event %s to topic %s",
                        event.id,
                        event.topic,
                    )
                    await repo.mark_failed(event.id, error=str(exc))
        return processed
