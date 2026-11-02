"""Where issued discount codes live, behind a small interface (D-23).

In-memory by default: idempotency holds for the life of the process, which is
honest for a demo. A database-backed store would implement the same three
methods and nothing else would change.
"""

from datetime import date
from typing import Protocol


class CodeStore(Protocol):
    def get(self, email: str, day: date) -> str | None: ...
    def put(self, email: str, day: date, code: str) -> None: ...
    def exists(self, code: str) -> bool: ...


class InMemoryCodeStore:
    def __init__(self) -> None:
        self._by_customer_day: dict[tuple[str, date], str] = {}

    def get(self, email: str, day: date) -> str | None:
        return self._by_customer_day.get((email, day))

    def put(self, email: str, day: date, code: str) -> None:
        self._by_customer_day[(email, day)] = code

    def exists(self, code: str) -> bool:
        return code in self._by_customer_day.values()
