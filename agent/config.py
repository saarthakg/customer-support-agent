"""All tunables in one place. Changing the model or a limit should never mean hunting through modules."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
LOG_DIR = ROOT / "logs"
TRACE_LOG = LOG_DIR / "trace.jsonl"
HANDOFF_LOG = LOG_DIR / "handoffs.jsonl"

MODEL = "gpt-4.1-mini"
# Low temperature: a support agent should answer the same question the same way.
TEMPERATURE = 0.2

# Max model calls per user turn. Each journey needs at most ~2 tool rounds; the
# cap exists to stop a confused model from looping, not to constrain normal use.
MAX_TOOL_ITERATIONS = 5
REQUEST_TIMEOUT_S = 30.0
# Retries for transient errors (429, 5xx, connection) with exponential backoff,
# delegated to the openai client rather than re-implemented.
MAX_RETRIES = 2

TIMEZONE = "America/Los_Angeles"
