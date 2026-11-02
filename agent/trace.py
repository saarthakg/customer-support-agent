"""Append-only JSONL trace: one record per user turn.

Records include raw customer messages (emails, order numbers). Fine for a local
demo; production would redact PII before writing.
"""

import json
from datetime import datetime, timezone
from pathlib import Path


class Tracer:
    def __init__(self, path: Path, session_id: str) -> None:
        self.path = path
        self.session_id = session_id
        path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, record: dict) -> None:
        line = {"ts": datetime.now(timezone.utc).isoformat(), "session_id": self.session_id, **record}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
