"""Early Risers promotion: issue_early_risers_code(email).

Code decides everything that matters: whether it's 8-10 AM Pacific right now,
who the customer is (normalized email), whether they already have today's code,
and the code itself. The model decides only whether the customer explicitly
asked, and how to say the result (D-08, D-20 to D-24).
"""

import re
import secrets
from collections.abc import Callable
from datetime import datetime, time

from agent.clock import PACIFIC, Clock
from agent.code_store import CodeStore
from agent.data import normalize_email
from agent.registry import Deps, Skill, Tool
from agent.supervisor import GuardRule

DISCOUNT_PERCENT = 10
# Half-open window [08:00, 10:00) Pacific: 10:00:00 is outside (D-20).
WINDOW_START = time(8, 0)
WINDOW_END = time(10, 0)
WINDOW_TEXT = "8:00-10:00 AM Pacific Time"
STATUS_OPEN = "Early Risers status: OPEN until 10:00 AM PT"
STATUS_CLOSED = "Early Risers status: CLOSED (runs 8:00-10:00 AM PT)"

CODE_PREFIX = "EARLYRISER-"
# No 0/O, 1/I/L: codes get read aloud and retyped at checkout.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
# Deliberately looser than the real format, so the supervisor also catches invented
# look-alikes ("EARLYBIRD10", "SIERRA10"). Case-sensitive on purpose: prose like
# "the Early Risers promotion" must not match.
CODE_PATTERN = re.compile(r"\b(?:EARLY-?(?:RISERS?|BIRD)|SIERRA)(?:-[A-Z0-9]+|\d+)\b")
# What the supervisor says when a code no tool issued shows up in a draft (D-67). Code-written,
# so even a twice-blocked reply still tells the customer something true and useful.
CODE_GUARD = GuardRule(
    CODE_PATTERN,
    quoted_correction=(
        "Do not repeat codes the customer typed. Say you can't validate codes, "
        "and explain how to get a real Early Risers code."
    ),
    fallback=(
        "I can't verify discount codes. Only codes I issue in this chat are valid, "
        "and Early Risers codes are available 8:00–10:00 AM Pacific."
    ),
)

INSTRUCTIONS = f"""\
The Early Risers promotion is a {DISCOUNT_PERCENT}% discount code, available only {WINDOW_TEXT}. \
Code decides eligibility; you never work out the time yourself.
- Each turn a status line computed by code tells you whether it's open right now: \
"{STATUS_OPEN}" or "{STATUS_CLOSED}". Trust it.
- Never bring the promotion up unprompted. If the customer asks about discounts, deals, coupons or promotions in \
general (not for the Early Risers code itself), tell them about Early Risers ({DISCOUNT_PERCENT}% off, \
{WINDOW_TEXT}). If it's OPEN, ask whether they'd like a code; don't issue it until they explicitly say yes.
- If it's CLOSED: there's no code to give right now. If they ask for one, say the promotion runs {WINDOW_TEXT} and \
invite them back. Never ask for an email while it's CLOSED.
- If it's OPEN and the customer explicitly asks for the code (or says yes to your offer): they've already said \
they want it, so don't ask again. If you have their email from this conversation, call issue_early_risers_code \
with it right away; if not, ask for their email (only that), then call the tool.
- needs_email: ask for their email (only that), then call the tool again with it.
- On success: say it's {DISCOUNT_PERCENT}% off and put the code on its own line, exactly as returned. If \
already_issued is true, say this is the same code they were given earlier today. Don't invent an expiry date, \
minimum spend, exclusions, or redemption steps beyond "use it at checkout".
- outside_promo_window: no code. Say the promotion runs {WINDOW_TEXT}, mention the current Pacific time from \
the tool, and invite them back. Keep it friendly and brief.
- invalid_email: ask them to re-check their email.
- You can't validate codes. Only a code issue_early_risers_code returned in this chat is real. If the customer \
asks about any other code, don't repeat it; say you can't verify codes, never imply it will work (now or later), \
and explain how to get a real one: ask for it between 8:00 and 10:00 AM Pacific."""


def generate_code() -> str:
    return CODE_PREFIX + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))


def in_window(moment: datetime) -> bool:
    local = moment.astimezone(PACIFIC).time()
    return WINDOW_START <= local < WINDOW_END


class EarlyRisers:
    def __init__(self, now: Clock, store: CodeStore, new_code: Callable[[], str] = generate_code) -> None:
        self.now = now
        self.store = store
        self.new_code = new_code  # injectable so tests can force a collision

    def status_line(self) -> str:
        """The per-turn eligibility fact for the model (D-64). A fact, not the clock: the raw time stays out."""
        return STATUS_OPEN if in_window(self.now()) else STATUS_CLOSED

    def issue_early_risers_code(self, email: str = "") -> dict:
        # Window first: outside it the answer is "no" for everyone, so never make the customer
        # hand over an email just to be told to come back later (D-62).
        moment = self.now()
        if not in_window(moment):
            return {
                "ok": False,
                "error": "outside_promo_window",
                "window": WINDOW_TEXT,
                "current_time_pt": moment.astimezone(PACIFIC).strftime("%I:%M %p PT").lstrip("0"),
            }
        if not email.strip():
            return {"ok": False, "error": "needs_email"}
        normalized_email = normalize_email(email)
        if normalized_email is None:
            return {"ok": False, "error": "invalid_email"}

        # "Today" is the Pacific calendar day: the window and the idempotency key share a timezone.
        today = moment.astimezone(PACIFIC).date()
        existing = self.store.get(normalized_email, today)
        if existing:
            return self._issued(existing, normalized_email, already_issued=True)

        code = self.new_code()
        while self.store.exists(code):  # astronomically rare with 31^6 codes, but uniqueness is a promise
            code = self.new_code()
        self.store.put(normalized_email, today, code)
        return self._issued(code, normalized_email, already_issued=False)

    @staticmethod
    def _issued(code: str, email: str, already_issued: bool) -> dict:
        return {
            "ok": True,
            "code": code,
            "discount_percent": DISCOUNT_PERCENT,
            "email": email,  # the identity the code is keyed to, so trace and model see exactly who got it
            "already_issued": already_issued,
        }


def build(deps: Deps) -> Skill:
    promo = EarlyRisers(deps.now, deps.code_store)
    return Skill(
        name="Early Risers promotion",
        instructions=INSTRUCTIONS,
        tools=(
            Tool(
                name="issue_early_risers_code",
                description=(
                    f"Issue the customer's Early Risers {DISCOUNT_PERCENT}% discount code. Call ONLY when the "
                    "customer explicitly asks for the Early Risers code/discount, or explicitly says yes after "
                    f"you mention it, and then call it right away, with or without an email. Eligibility "
                    f"({WINDOW_TEXT}) is checked first; returns needs_email if it's within the window and no "
                    "email was given. The same email on the same day gets the same code back."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "email": {
                            "type": "string",
                            "description": "The customer's email address, if they've given one. Omit it otherwise.",
                        }
                    },
                    "required": [],
                },
                handler=promo.issue_early_risers_code,
            ),
        ),
        guarded_values={"blocked_code": CODE_GUARD},
        turn_context=promo.status_line,
    )
