from collections.abc import Mapping
from typing import Protocol

from aio_pika import DeliveryMode, Message
from aio_pika.abc import AbstractExchange, AbstractIncomingMessage

from src.messaging.topology import (
    RETRY_EXCHANGE,
    WEBHOOK_RETRY_10S_ROUTING_KEY,
    WEBHOOK_RETRY_60S_ROUTING_KEY,
    WEBHOOK_RETRY_300S_ROUTING_KEY,
)

RETRY_HEADERS = "x-retry-count"


class RetryChannel(Protocol):
    async def get_exchange(
        self,
        name: str,
        *,
        ensure: bool = True,
    ) -> AbstractExchange: ...


def get_retry_routing_key(retry_count: int) -> str | None:
    if retry_count == 0:
        return WEBHOOK_RETRY_10S_ROUTING_KEY
    elif retry_count == 1:
        return WEBHOOK_RETRY_60S_ROUTING_KEY
    elif retry_count == 2:
        return WEBHOOK_RETRY_300S_ROUTING_KEY

    return None


def get_retry_count(headers: Mapping[str, object]) -> int:
    retry_count = headers.get(RETRY_HEADERS, 0)
    if isinstance(retry_count, int):
        return retry_count

    return 0


async def publish_retry(
    channel: RetryChannel, message: AbstractIncomingMessage
) -> bool:
    headers = dict(message.headers or {})
    retry_count = get_retry_count(headers)
    routing_key = get_retry_routing_key(retry_count)
    if routing_key is None:
        return False

    headers[RETRY_HEADERS] = retry_count + 1
    retry_exchange = await channel.get_exchange(RETRY_EXCHANGE, ensure=True)

    retry_message = Message(
        body=message.body,
        headers=headers,
        message_id=message.message_id,
        correlation_id=message.correlation_id,
        content_type=message.content_type or "application/json",
        delivery_mode=DeliveryMode.PERSISTENT,
    )

    await retry_exchange.publish(
        retry_message,
        routing_key=routing_key,
    )
    return True
