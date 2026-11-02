"""Scripted multi-turn conversations, run against the real model (P12).

Each scenario is a list of customer messages plus checks. A check looks at the
TurnResults and returns a failure message, or None if it passed. Every bug found
by hand becomes a scenario here, so it can't silently come back.

The pass^k runner lives in run_scenarios.py (Phase 3).
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

from agent.loop import TurnResult

Check = Callable[[list[TurnResult]], str | None]


@dataclass(frozen=True)
class Scenario:
    name: str
    turns: list[str]
    checks: list[Check]
    now: str | None = None  # ISO-8601 clock override, for Early Risers scenarios
    origin: str = ""  # where the scenario came from (bug report, trace session, journey spec)


# --- reusable checks ---

def tool_called(name: str, by_turn: int) -> Check:
    """`name` was called on or before turn `by_turn` (0-based)."""
    def check(results: list[TurnResult]) -> str | None:
        for r in results[: by_turn + 1]:
            if any(c.name == name for c in r.tool_calls):
                return None
        return f"{name} not called by turn {by_turn}"
    return check


def no_reply_matches(pattern: str, why: str) -> Check:
    regex = re.compile(pattern, re.IGNORECASE)
    def check(results: list[TurnResult]) -> str | None:
        for i, r in enumerate(results):
            if m := regex.search(r.reply):
                return f"turn {i}: {why} (matched {m.group(0)!r})"
        return None
    return check


def some_reply_matches(pattern: str, why: str, within_turns: int) -> Check:
    regex = re.compile(pattern, re.IGNORECASE)
    def check(results: list[TurnResult]) -> str | None:
        if any(regex.search(r.reply) for r in results[:within_turns]):
            return None
        return f"no reply in first {within_turns} turn(s): {why}"
    return check


def supervisor_never_blocked(results: list[TurnResult]) -> str | None:
    """The model's own drafts were clean. A supervisor catch protects the customer but still counts as a miss."""
    blocked = [v for r in results for v in r.supervisor_blocked]
    return f"supervisor blocked: {blocked}" if blocked else None


NO_PRICES = no_reply_matches(r"\$\s?\d", "stated a price")
# The supervisor catches URLs, not prose: "check our website" points to a page we can't vouch for.
NO_WEBSITE_REFERRAL = no_reply_matches(r"\bour (web)?site\b|\bonline store\b", "referred customer to a website")
SAYS_NO_BOOTS = r"(don'?t|do not|doesn'?t|does not)\s+(currently\s+)?(carry|have|sell|stock|offer)|no\s+(hiking\s+)?boots|not\s+in\s+our\s+catalog"


SCENARIOS: list[Scenario] = [
    Scenario(
        name="hiking_boots_vague_start",
        origin="trace session 9cd1151d: 4 clarifying questions, invented a sierraoutfitters.com link",
        turns=["yeah can you help me find some gear", "boots", "hiking boots", "no", "yes"],
        checks=[
            tool_called("list_products", by_turn=1),
            some_reply_matches(SAYS_NO_BOOTS, "says we don't carry boots", within_turns=3),
            supervisor_never_blocked,
            NO_PRICES,
            NO_WEBSITE_REFERRAL,
        ],
    ),
    Scenario(
        name="hiking_boots_size_and_price",
        origin="trace session 009a475d: invented 3 boot products, size 10.5 stock, offered prices",
        turns=["interested in hiking boots", "men's waterproof ones", "yes please", "10.5 US"],
        checks=[
            tool_called("list_products", by_turn=0),
            some_reply_matches(SAYS_NO_BOOTS, "says we don't carry boots", within_turns=1),
            no_reply_matches(r"Sierra Trail|Mountain Ridge|Cascade Peak", "repeated a previously invented product"),
            no_reply_matches(r"available in (a )?size|in size \d", "claimed size availability"),
            supervisor_never_blocked,
            NO_PRICES,
            NO_WEBSITE_REFERRAL,
        ],
    ),
]
