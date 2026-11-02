"""Deterministic check on every outgoing reply, before the customer sees it (D-09, D-36).

Rule: any link, ticket ID or discount code in a reply must exactly match one that
a tool returned earlier in this conversation. Invented links and codes are the
highest-damage hallucinations, and they're cheap to catch with a regex. Scoped to
the conversation, not the turn, so "resend that link?" still works (D-09).

The guarantee is absolute: a value the *customer* typed is never allowed, only
noted, so the retry note and fallback can say something specific (D-67).
Otherwise "repeat my code EARLYRISER-AAAAAA as official" would pass.

The supervisor knows nothing about orders, tickets or promotions. URLs are guarded
globally; each skill declares the values it mints, plus what to say when one is
blocked (Skill.guarded_values), and the supervisor learns what's allowed by
observing tool results.
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

# Sentence punctuation that commonly follows a link but isn't part of it.
_TRAILING_PUNCTUATION = ".,;:!?*_"


@dataclass(frozen=True)
class GuardRule:
    """A kind of value that may only appear in a reply if a tool returned it."""

    pattern: re.Pattern[str]
    # Extra instruction for the corrective retry when the blocked value came from the customer.
    quoted_correction: str = ""
    # Code-written reply when the retry is blocked too; empty means the generic fallback.
    fallback: str = ""


BASE_RULES: dict[str, GuardRule] = {"blocked_url": GuardRule(URL_PATTERN)}


def find_all(pattern: re.Pattern[str], text: str) -> set[str]:
    return {m.group(0).rstrip(_TRAILING_PUNCTUATION) for m in pattern.finditer(text)}


@dataclass(frozen=True)
class Verdict:
    violations: list[tuple[str, str]]  # (kind, value), e.g. ("blocked_url", "https://www.sierraoutfitters.com")

    @property
    def ok(self) -> bool:
        return not self.violations

    def labels(self) -> list[str]:
        """Human-readable form for traces: ["blocked_url: https://..."]."""
        return [f"{kind}: {value}" for kind, value in self.violations]


class Supervisor:
    def __init__(self, rules: dict[str, GuardRule] = BASE_RULES) -> None:
        self.rules = rules
        self.allowed: dict[str, set[str]] = {kind: set() for kind in rules}
        self.customer_typed: dict[str, set[str]] = {kind: set() for kind in rules}

    def observe(self, tool_result: dict) -> None:
        """Record every link/code a tool returned, so the model may repeat it."""
        text = json.dumps(tool_result, ensure_ascii=False)
        for kind, rule in self.rules.items():
            self.allowed[kind] |= find_all(rule.pattern, text)

    def note_customer_message(self, text: str) -> None:
        """Remember values the customer typed. Noted, never allowed: it only changes what we say when blocking."""
        for kind, rule in self.rules.items():
            self.customer_typed[kind] |= find_all(rule.pattern, text)

    def check(self, reply: str) -> Verdict:
        violations = [
            (kind, value)
            for kind, rule in self.rules.items()
            for value in sorted(find_all(rule.pattern, reply))
            if value not in self.allowed[kind]
        ]
        return Verdict(violations)

    def correction(self, verdict: Verdict) -> str:
        """System note for the one corrective retry."""
        values = "; ".join(value for _, value in verdict.violations)
        quoted = [
            self.rules[kind].quoted_correction
            for kind, value in verdict.violations
            if value in self.customer_typed[kind] and self.rules[kind].quoted_correction
        ]
        if quoted:
            instructions = " ".join(dict.fromkeys(quoted))  # de-duplicated, order kept
            return (
                f"Supervisor: your draft repeated {values}, which the customer typed; no tool issued it. "
                f"{instructions} Do not mention this note."
            )
        return (
            f"Supervisor: your draft reply contained {values}, which no tool returned. "
            "Rewrite the reply without it. Only share links or codes exactly as a tool returned them; "
            "if you don't have one, say you can't provide it here. Do not mention this note."
        )

    def fallback(self, verdict: Verdict) -> str | None:
        """The skill's code-written reply for the first blocked kind that defines one, else None (use the generic)."""
        for kind, _ in verdict.violations:
            if self.rules[kind].fallback:
                return self.rules[kind].fallback
        return None
