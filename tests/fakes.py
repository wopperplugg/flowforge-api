from types import TracebackType
from typing import Self


class AsyncTransaction:
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.deleted: list[object] = []
        self.refreshed: list[object] = []
        self.begin_count = 0
        self._in_transaction = False

    def in_transaction(self) -> bool:
        return self._in_transaction

    def begin(self) -> AsyncTransaction:
        self.begin_count += 1
        return AsyncTransaction()

    def add(self, item: object) -> None:
        self.added.append(item)

    async def delete(self, item: object) -> None:
        self.deleted.append(item)

    async def refresh(self, item: object) -> None:
        self.refreshed.append(item)
