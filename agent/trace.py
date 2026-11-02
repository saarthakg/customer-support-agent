"""Append-only JSONL trace: one record per user turn.

Emails are masked everywhere in the record (user text, tool args, tool results,
replies) by redact(). Order numbers and first names are kept: they're needed to
debug a conversation and aren't enough on their own to identify a customer.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

_EMAIL = re.compile(r"\b([A-Za-z0-9])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")


def redact(value: object) -> object:
    """Mask emails anywhere in a JSON-like value: john.doe@example.com -> j***@example.com."""
    if isinstance(value, str):
        return _EMAIL.sub(r"\1***@\2", value)
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


class Tracer:
    def __init__(self, path: Path, session_id: str) -> None:
        self.path = path
        self.session_id = session_id
        path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, record: dict) -> None:
        line = {"ts": datetime.now(timezone.utc).isoformat(), "session_id": self.session_id, **record}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(redact(line), ensure_ascii=False) + "\n")
