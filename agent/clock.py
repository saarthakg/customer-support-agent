"""Time is a dependency: injected so tests, scenarios and `--now` can control it (P8).

Clocks are timezone-aware. Business rules convert to Pacific with zoneinfo, which
handles DST, rather than assuming a fixed UTC offset.
"""

from collections.abc import Callable
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from agent import config

PACIFIC = ZoneInfo(config.TIMEZONE)

Clock = Callable[[], datetime]


def system_clock() -> datetime:
    return datetime.now(timezone.utc)


def parse_now(value: str) -> datetime:
    """Parse a `--now` override. Without an offset, the time is taken as Pacific:
    `2026-11-03T08:30` means 8:30 AM PT, which is how a demo thinks about the promo window."""
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=PACIFIC)


def fixed_clock(moment: datetime) -> Clock:
    """A frozen clock: every call returns the same moment, so a demo behaves identically every run."""
    return lambda: moment
