import uuid
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Self

import pytest

from src import worker
from src.common.enums import OutboxStatus
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
