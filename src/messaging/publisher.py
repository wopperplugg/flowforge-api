from types import TracebackType

import aio_pika
from aio_pika import DeliveryMode, ExchangeType, Message
from aio_pika.abc import (
    AbstractChannel,
    AbstractExchange,
    AbstractRobustConnection,
    FieldValue,
)

from src.messaging.contracts import OutboxMessage


class RabbitMQPublisher:
    exchange_name = "flowforge.events"

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._connection: AbstractRobustConnection | None = None
        self._channel: AbstractChannel | None = None
        self._exchange: AbstractExchange | None = None

    async def connect(self) -> None:
        self._connection = await aio_pika.connect_robust(self._dsn)
        self._channel = await self._connection.channel(
            publisher_confirms=True,
        )
        channel = self._channel
        self._exchange = await channel.declare_exchange(
            self.exchange_name,
            ExchangeType.TOPIC,
            durable=True,
        )

    async def publish(self, event: OutboxMessage) -> None:
        if self._exchange is None:
            raise RuntimeError("RabbitMQ publisher is not connected")

        headers: dict[str, FieldValue] = {
            "event_version": event.event_version,
            "aggregate_type": event.aggregate_type,
            "aggregate_id": str(event.aggregate_id),
        }

        if event.organization_id is not None:
            headers["organization_id"] = str(event.organization_id)

        if event.correlation_id is not None:
            headers["correlation_id"] = str(event.correlation_id)

        message = Message(
            body=event.model_dump_json().encode(),
            content_type="application/json",
            delivery_mode=DeliveryMode.PERSISTENT,
            message_id=str(event.event_id),
            correlation_id=(
                str(event.correlation_id) if event.correlation_id is not None else None
            ),
            type=event.event_type,
            timestamp=event.occurred_at,
            headers=headers,
        )
        await self._exchange.publish(
            message,
            routing_key=event.event_type,
            mandatory=True,
        )

    async def close(self) -> None:
        if self._channel is not None and not self._channel.is_closed:
            await self._channel.close()
        if self._connection is not None:
            await self._connection.close()

        self._exchange = None
        self._channel = None
        self._connection = None

    async def __aenter__(self) -> "RabbitMQPublisher":
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()
