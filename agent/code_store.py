"""Where issued discount codes live, behind a small interface (D-23, D-61).

The CLI uses JsonCodeStore so "same customer, same day, same code" survives a
restart. Tests and scenarios use InMemoryCodeStore so runs never leak into each
other. A database-backed store would implement the same three methods and
nothing else would change.
"""

import json
import logging
import os
import time
from datetime import date
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)


class CodeStore(Protocol):
    def get(self, email: str, day: date) -> str | None: ...
    def put(self, email: str, day: date, code: str) -> None: ...
    def exists(self, code: str) -> bool: ...


class InMemoryCodeStore:
    def __init__(self) -> None:
        self._codes: dict[str, str] = {}  # "email|YYYY-MM-DD" -> code

    def get(self, email: str, day: date) -> str | None:
        return self._codes.get(_key(email, day))

    def put(self, email: str, day: date, code: str) -> None:
        self._codes[_key(email, day)] = code

    def exists(self, code: str) -> bool:
        return code in self._codes.values()


class JsonCodeStore(InMemoryCodeStore):
    """The in-memory store, loaded from and saved to a JSON file on every write."""

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path
        if path.exists():
            self._codes = self._load(path)

    @staticmethod
    def _load(path: Path) -> dict[str, str]:
        """The saved codes; a corrupt file is moved aside and the store starts empty (D-73).

        The promotion keeps working in peak season, at the cost of forgetting today's
        codes: a returning customer could get a second one. The bad file is kept for inspection.
        """
        try:
            codes = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(codes, dict) and all(isinstance(v, str) for v in codes.values()):
                return codes
            reason = "not a JSON object of codes"
        except ValueError as e:  # bad JSON or non-UTF-8 bytes
            reason = str(e)
        backup = path.with_name(f"{path.name}.corrupt-{int(time.time())}")
        os.replace(path, backup)
        logger.warning("code store %s is unreadable (%s); moved to %s and starting empty", path, reason, backup.name)
        return {}

    def put(self, email: str, day: date, code: str) -> None:
        super().put(email, day, code)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Write to a temp file, then rename: a crash mid-write can't leave a half-written store.
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._codes, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.path)


def _key(email: str, day: date) -> str:
    return f"{email}|{day.isoformat()}"
