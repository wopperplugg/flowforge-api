import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Self

import pytest

from src import worker
from src.common.enums import OutboxStatus
from src.config import settings
from src.messaging.contracts import OutboxMessage
from src.outbox.models import OutboxEvent
from src.outbox.repository import OutboxRepository


class FakeScalarResult:
    def __init__(self, events: list[OutboxEvent]) -> None:
        self.events = events

    def all(self) -> list[OutboxEvent]:
        return self.events


class FakeExecuteResult:
    def __init__(self, events: list[OutboxEvent]) -> None:
        self.events = events

    def scalars(self) -> FakeScalarResult:
        return FakeScalarResult(self.events)


class FakeOutboxSession:
    def __init__(self, events: list[OutboxEvent]) -> None:
        self.events = events
        self.flushed = False

    async def execute(self, statement: object) -> FakeExecuteResult:
        return FakeExecuteResult(self.events)

    async def flush(self) -> None:
        self.flushed = True


class FakeBegin:
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


class FakeWorkerSession:
    def __init__(self) -> None:
        self.begin_count = 0

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def begin(self) -> FakeBegin:
        self.begin_count += 1
        return FakeBegin()


class FakeStopEvent:
    def __init__(self) -> None:
        self.wait_count = 0
        self._is_set = False

    def is_set(self) -> bool:
        return self._is_set

    async def wait(self) -> None:
        self.wait_count += 1
        if self.wait_count >= 2:
            self._is_set = True


def make_outbox_event() -> OutboxEvent:
    return OutboxEvent(
        id=uuid.uuid4(),
        event_type="task.created",
        aggregate_type="task",
        aggregate_id=uuid.uuid4(),
        payload={"task_id": str(uuid.uuid4())},
        status=OutboxStatus.PENDING,
        attempts=0,
        created_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_outbox_repository_claim_and_mark_states() -> None:
    event = make_outbox_event()
    session = FakeOutboxSession([event])
    repository = OutboxRepository(session)  # type: ignore[arg-type]

    claimed = await repository.claim_pending(limit=10)

    assert claimed == [event]
    assert event.status == OutboxStatus.PROCESSING
    assert session.flushed is True

    await repository.mark_processed(event)
    assert event.status.value == OutboxStatus.PROCESSED.value
    assert event.processed_at is not None
    assert event.last_error is None

    await repository.mark_failed_or_retry(event, "x" * 3000, max_attempts=5)
    assert event.status.value == OutboxStatus.PENDING.value
    assert event.last_error == "x" * 2000
    assert event.next_attempt_at is not None

    event.attempts = 4
    await repository.mark_failed_or_retry(event, "final", max_attempts=5)
    assert event.status.value == OutboxStatus.FAILED.value


def test_build_outbox_message() -> None:
    event = make_outbox_event()

    message = worker.build_outbox_message(event)

    assert message.event_id == event.id
    assert message.event_type == event.event_type
    assert message.aggregate_type == event.aggregate_type
    assert message.aggregate_id == event.aggregate_id
    assert message.occurred_at == event.created_at
    assert message.payload == event.payload


@pytest.mark.asyncio
async def test_worker_processes_successful_and_failed_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = [make_outbox_event(), make_outbox_event()]
    marked_processed: list[uuid.UUID] = []
    marked_failed: list[uuid.UUID] = []
    published_messages: list[OutboxMessage] = []

    class FakeRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        async def claim_pending(
            self,
            batch_size: int,
        ) -> list[OutboxEvent]:
            return events

        async def mark_processed(
            self,
            event: OutboxEvent,
        ) -> None:
            marked_processed.append(event.id)

        async def mark_failed_or_retry(
            self,
            event: OutboxEvent,
            error: str,
        ) -> None:
            marked_failed.append(event.id)

    class FakePublisher:
        async def publish(
            self,
            message: OutboxMessage,
        ) -> None:
            published_messages.append(message)

            if message.event_id == events[1].id:
                raise RuntimeError("publish failed")

    monkeypatch.setattr(
        worker,
        "async_session_maker",
        lambda: FakeWorkerSession(),
    )
    monkeypatch.setattr(
        worker,
        "OutboxRepository",
        FakeRepository,
    )

    processed = await worker.process_outbox_once(
        FakePublisher(),  # type: ignore[arg-type]
        batch_size=2,
    )

    assert processed == 1
    assert marked_processed == [events[0].id]
    assert marked_failed == [events[1].id]

    assert len(published_messages) == 2
    assert published_messages[0].event_id == events[0].id
    assert published_messages[1].event_id == events[1].id


@pytest.mark.asyncio
async def test_worker_returns_zero_when_no_outbox_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        async def claim_pending(self, batch_size: int) -> list[OutboxEvent]:
            assert batch_size == 50
            return []

    class FakePublisher:
        async def publish(self, message: OutboxMessage) -> None:
            raise AssertionError("publish should not be called")

    monkeypatch.setattr(worker, "async_session_maker", lambda: FakeWorkerSession())
    monkeypatch.setattr(worker, "OutboxRepository", FakeRepository)

    processed = await worker.process_outbox_once(
        FakePublisher(),  # type: ignore[arg-type]
        batch_size=50,
    )

    assert processed == 0


@pytest.mark.asyncio
async def test_run_outbox_loop_uses_active_and_idle_intervals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processed_batches = [1, 0]
    batch_sizes: list[int] = []
    timeouts: list[float] = []
    stop_event = FakeStopEvent()

    async def fake_process_outbox_once(
        publisher: object,
        batch_size: int,
    ) -> int:
        batch_sizes.append(batch_size)
        return processed_batches.pop(0)

    async def fake_wait_for(
        awaitable: object,
        timeout: float,
    ) -> None:
        timeouts.append(timeout)
        await awaitable  # type: ignore[misc]

    monkeypatch.setattr(
        worker,
        "process_outbox_once",
        fake_process_outbox_once,
    )
    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)

    await worker.run_outbox_loop(
        object(),  # type: ignore[arg-type]
        stop_event,  # type: ignore[arg-type]
        batch_size=10,
        active_poll_interval=0.5,
        idle_poll_interval=2.0,
    )

    assert batch_sizes == [10, 10]
    assert timeouts == [0.5, 2.0]


@pytest.mark.asyncio
async def test_main_uses_settings_for_outbox_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakePublisher:
        def __init__(self, dsn: str) -> None:
            captured["dsn"] = dsn

        async def __aenter__(self) -> "FakePublisher":
            return self

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            return None

    def fake_install_shutdown_handlers(stop_event: object) -> None:
        captured["stop_event"] = stop_event

    async def fake_run_outbox_loop(
        publisher: object,
        stop_event: object,
        *,
        batch_size: int,
        active_poll_interval: float,
        idle_poll_interval: float,
    ) -> None:
        captured["publisher"] = publisher
        captured["loop_stop_event"] = stop_event
        captured["batch_size"] = batch_size
        captured["active_poll_interval"] = active_poll_interval
        captured["idle_poll_interval"] = idle_poll_interval

    monkeypatch.setattr(worker, "RabbitMQPublisher", FakePublisher)
    monkeypatch.setattr(
        worker,
        "install_shutdown_handlers",
        fake_install_shutdown_handlers,
    )
    monkeypatch.setattr(worker, "run_outbox_loop", fake_run_outbox_loop)
    monkeypatch.setattr(settings, "outbox_batch_size", 17)
    monkeypatch.setattr(settings, "outbox_active_poll_interval", 0.25)
    monkeypatch.setattr(settings, "outbox_idle_poll_interval", 3.5)

    await worker.main()

    assert captured["dsn"] == str(settings.rabbitmq_dsn)
    assert captured["loop_stop_event"] is captured["stop_event"]
    assert captured["batch_size"] == 17
    assert captured["active_poll_interval"] == 0.25
    assert captured["idle_poll_interval"] == 3.5


@pytest.mark.asyncio
async def test_outbox_repository_retry_backoff_is_capped() -> None:
    event = make_outbox_event()
    event.attempts = 8
    repository = OutboxRepository(FakeOutboxSession([]))  # type: ignore[arg-type]

    before = datetime.now(UTC)
    await repository.mark_failed_or_retry(event, "temporary", max_attempts=20)
    after = datetime.now(UTC)

    assert event.attempts == 9
    assert event.status == OutboxStatus.PENDING
    assert event.next_attempt_at is not None
    assert (
        before + timedelta(seconds=300)
        <= event.next_attempt_at
        <= after + timedelta(seconds=300)
    )
