"""Deterministic check on every outgoing reply, before the customer sees it (D-09, D-36).

Rule: any link, ticket ID or discount code in a reply must exactly match one that
a tool returned earlier in this conversation. Invented links and codes are the
highest-damage hallucinations, and they're cheap to catch with a regex. Scoped to
the conversation, not the turn, so "resend that link?" still works (D-09).

The supervisor knows nothing about orders, tickets or promotions. URLs are guarded
globally; each skill declares the values it mints (Skill.guarded_values), and the
supervisor learns what's allowed by observing tool results.
"""

import json
import re
from dataclasses import dataclass

# Anything a customer could treat as a link: a scheme or "www.", or a bare domain
# with a common TLD ("sierraoutfitters.com/boots"). The lookbehind stops email
# addresses (john.doe@example.com) from matching as domains.
_URL_CHARS = r"[^\s<>()\[\]\"'`]"
URL_PATTERN = re.compile(
    rf"(?:https?://|www\.){_URL_CHARS}+"
    rf"|(?<![@\w.-])(?:[a-z0-9-]+\.)+(?:com|net|org|io|co|us|ai|shop|store)\b(?:/{_URL_CHARS}*)?",
    re.IGNORECASE,
)

BASE_PATTERNS: dict[str, re.Pattern[str]] = {"blocked_url": URL_PATTERN}

# Sentence punctuation that commonly follows a link but isn't part of it.
_TRAILING_PUNCTUATION = ".,;:!?*_"


def find_all(pattern: re.Pattern[str], text: str) -> set[str]:
    return {m.group(0).rstrip(_TRAILING_PUNCTUATION) for m in pattern.finditer(text)}


@dataclass(frozen=True)
class Verdict:
    violations: list[str]  # e.g. ["blocked_url: https://www.sierraoutfitters.com/hiking-boots"]

    @property
    def ok(self) -> bool:
        return not self.violations


class Supervisor:
    def __init__(self, patterns: dict[str, re.Pattern[str]] = BASE_PATTERNS) -> None:
        self.patterns = patterns
        self.allowed: dict[str, set[str]] = {kind: set() for kind in patterns}

    def observe(self, tool_result: dict) -> None:
        """Record every link/code a tool returned, so the model may repeat it."""
        text = json.dumps(tool_result, ensure_ascii=False)
        for kind, pattern in self.patterns.items():
            self.allowed[kind] |= find_all(pattern, text)

    def check(self, reply: str) -> Verdict:
        violations = [
            f"{kind}: {value}"
            for kind, pattern in self.patterns.items()
            for value in sorted(find_all(pattern, reply))
            if value not in self.allowed[kind]
        ]
        return Verdict(violations)

    @staticmethod
    def correction(verdict: Verdict) -> str:
        """System note for the one corrective retry."""
        values = "; ".join(v.split(": ", 1)[1] for v in verdict.violations)
        return (
            f"Supervisor: your draft reply contained {values}, which no tool returned. "
            "Rewrite the reply without it. Only share links or codes exactly as a tool returned them; "
            "if you don't have one, say you can't provide it here. Do not mention this note."
        )
