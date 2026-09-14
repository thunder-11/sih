"""Repository transaction boundary used by later domain modules."""

from typing import Protocol


class UnitOfWork(Protocol):
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
