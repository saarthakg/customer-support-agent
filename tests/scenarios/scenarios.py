"""Scripted multi-turn conversations, run against the real model (P12).

Each scenario is a list of customer messages plus checks. A check looks at the
TurnResults and returns a failure message, or None if it passed. Every bug found
by hand becomes a scenario here, so it can't silently come back.

The pass^k runner lives in run_scenarios.py (Phase 3).
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

from agent import config
from agent.data import load_datasets
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


def tool_returned(name: str, **fields: object) -> Check:
    """Some call to `name` returned a result containing all of `fields` (checks what code decided)."""
    def check(results: list[TurnResult]) -> str | None:
        for r in results:
            for c in r.tool_calls:
                if c.name == name and all(c.result.get(k) == v for k, v in fields.items()):
                    return None
        return f"no {name} call returned {fields}"
    return check


def tool_not_called(name: str) -> Check:
    def check(results: list[TurnResult]) -> str | None:
        hits = [i for i, r in enumerate(results) if any(c.name == name for c in r.tool_calls)]
        return f"{name} called on turn(s) {hits}" if hits else None
    return check


def reply_contains(text: str, why: str) -> Check:
    """Some reply contains `text` verbatim (links and codes must be copy-pasteable)."""
    def check(results: list[TurnResult]) -> str | None:
        return None if any(text in r.reply for r in results) else f"{why}: {text!r} not in any reply"
    return check


def max_questions(turn: int, n: int) -> Check:
    """The reply on `turn` asks at most `n` questions (counted by question marks)."""
    def check(results: list[TurnResult]) -> str | None:
        count = results[turn].reply.count("?")
        return f"turn {turn}: {count} questions (max {n})" if count > n else None
    return check


def question_asked_at_most(pattern: str, n: int, why: str) -> Check:
    """Replies that ask a question matching `pattern` appear at most `n` times across the conversation."""
    regex = re.compile(pattern, re.IGNORECASE)
    def check(results: list[TurnResult]) -> str | None:
        asking = [i for i, r in enumerate(results) if any(regex.search(q) for q in re.findall(r"[^.!?\n]*\?", r.reply))]
        return f"{why}: asked on turns {asking}" if len(asking) > n else None
    return check


def reply_contains_tool_value(name: str, key: str) -> Check:
    """Every successful `name` result's `key` (e.g. a generated code) appears verbatim in that turn's reply."""
    def check(results: list[TurnResult]) -> str | None:
        for i, r in enumerate(results):
            for c in r.tool_calls:
                if c.name == name and c.result.get("ok") and c.result[key] not in r.reply:
                    return f"turn {i}: {key} {c.result[key]!r} not in reply"
        return None
    return check


def tool_not_called_on_turn(name: str, turn: int) -> Check:
    def check(results: list[TurnResult]) -> str | None:
        hit = any(c.name == name for c in results[turn].tool_calls)
        return f"{name} called on turn {turn}" if hit else None
    return check


def same_value_every_time(name: str, key: str) -> Check:
    def check(results: list[TurnResult]) -> str | None:
        values = {c.result[key] for r in results for c in r.tool_calls if c.name == name and c.result.get("ok")}
        return f"{name} returned different {key}s: {values}" if len(values) > 1 else None
    return check


def first_tool_value_in_last_reply(name: str, key: str) -> Check:
    def check(results: list[TurnResult]) -> str | None:
        values = [c.result[key] for r in results for c in r.tool_calls if c.name == name and c.result.get("ok")]
        if not values:
            return f"no successful {name} call"
        return None if values[0] in results[-1].reply else f"last reply doesn't repeat {key} {values[0]!r}"
    return check


_EMOJI = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")
_OUTDOORS = re.compile(
    r"onward|unknown|trail|summit|adventure|mountain|peak|wild|outdoor|journey|trek|hik|explor|camp|slopes", re.I
)


def voiced(turn: int) -> Check:
    """Brand voice on a happy path: 1-2 emojis and an outdoors reference (brief: 'frequent references to the outdoors')."""
    def check(results: list[TurnResult]) -> str | None:
        reply = results[turn].reply
        emojis = len(_EMOJI.findall(reply))
        if not 1 <= emojis <= 2:
            return f"turn {turn}: {emojis} emojis (want 1-2)"
        return None if _OUTDOORS.search(reply) else f"turn {turn}: no outdoors reference"
    return check


def on_own_line(name: str, key: str) -> Check:
    """A tool value (link or code) sits on a line by itself, so it's easy to find and copy."""
    def check(results: list[TurnResult]) -> str | None:
        for i, r in enumerate(results):
            for c in r.tool_calls:
                value = c.result.get(key) if c.result.get("ok") else None
                if value and value in r.reply:
                    lines = [line.strip().strip("*`<>()[]:") for line in r.reply.splitlines()]
                    if value not in lines:
                        return f"turn {i}: {key} not on its own line"
        return None
    return check


def supervisor_never_blocked(results: list[TurnResult]) -> str | None:
    """The model's own drafts were clean. A supervisor catch protects the customer but still counts as a miss."""
    blocked = [v for r in results for v in r.supervisor_blocked]
    return f"supervisor blocked: {blocked}" if blocked else None


TRACKING_URL = "https://tools.usps.com/go/TrackConfirmAction?tLabels={}"
ANY_LINK = r"https?://|www\."
NO_EMOJI = no_reply_matches(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "used an emoji on a high-empathy path")
# Price claims, not echoes: "your $50 budget" is fine, "it's $49.99" / "costs $50" is not.
PROMO_CODE = r"\bEARLYRISER-[A-Z0-9]+"
NO_PROMO_MENTION = no_reply_matches(r"early riser|promo|discount|coupon|% off", "brought up the promotion unprompted")
NO_PRICES = no_reply_matches(
    r"\$\s?\d+\.\d{2}|(cost|costs|priced at|price is|for only|just|retails? for)\s+(about\s+)?\$\s?\d",
    "stated a price",
)
# The supervisor catches URLs, not prose: "check our website" points to a page we can't vouch for.
# Distinctive part of each catalog name ("Bhavish's Backcountry Blaze Backpack" -> "Backcountry Blaze Backpack"),
# so the model's short references still match.
_CATALOG_NAMES = [p.name.split("'s ", 1)[-1] for p in load_datasets(config.DATA_DIR).products.values()]
_REPLACEMENT_CUE = re.compile(
    r"\b(instead|alternative|substitute|replacement|in place of|swap|as close as|closest thing)\b", re.IGNORECASE
)


def never_presented_as_substitute(results: list[TurnResult]) -> str | None:
    """No sentence offers a catalog product as a replacement for the requested product type.

    Naming what we do carry is fine ("I can help with backpacks or other gear"); framing a
    specific product as standing in for the missing one is not ("try the backpack instead").
    """
    for i, r in enumerate(results):
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", r.reply):
            if _REPLACEMENT_CUE.search(sentence):
                named = [n for n in _CATALOG_NAMES if n.lower() in sentence.lower()]
                if named:
                    return f"turn {i}: presented {named} as a substitute: {sentence.strip()!r}"
    return None


# The only catalog item that could pass for footwear; offering it in a boots conversation is a substitution.
NO_SHOES_FOR_BOOTS = no_reply_matches(r"Wizarding Red Shoes|red shoes", "offered the teleporting shoes as footwear")
NO_WEBSITE_REFERRAL = no_reply_matches(r"\bour (web)?site\b|\bonline store\b", "referred customer to a website")
SAYS_NO_BOOTS = r"(don'?t|do not|doesn'?t|does not)\s+(currently\s+)?(carry|have|sell|stock|offer)|no\s+(hiking\s+)?boots|not\s+in\s+our\s+catalog"


SCENARIOS: list[Scenario] = [
    # --- Orders ---
    Scenario(
        name="order_delivered_with_link",
        origin="orders journey spec: happy path",
        turns=["Hi, where's my order?", "john.doe@example.com", "W001"],
        checks=[
            voiced(turn=2),
            on_own_line("lookup_order", "tracking_url"),
            tool_returned("lookup_order", ok=True, order_number="#W001", status="delivered"),
            reply_contains(TRACKING_URL.format("TRK123456789"), "tracking link verbatim"),
            reply_contains("Bhavish's Backcountry Blaze Backpack", "item named"),
            supervisor_never_blocked,
        ],
    ),
    Scenario(
        name="order_fulfilled_no_tracking",
        origin="orders journey spec: fulfilled has null tracking (D-14)",
        turns=["Can you check order #W003? My email is alice.johnson@example.com"],
        checks=[
            voiced(turn=0),
            tool_returned("lookup_order", status="fulfilled", tracking_url=None),
            no_reply_matches(ANY_LINK, "offered a link for an order with no tracking"),
            some_reply_matches(r"tracking", "explains tracking isn't available yet", within_turns=1),
            supervisor_never_blocked,
        ],
    ),
    Scenario(
        name="order_error_escalates",
        origin="orders journey spec: error status + missing SKU SOCH010 ends in handoff (D-15, D-16)",
        turns=["I need to check on my order", "W004, bob.brown@example.com", "yes please"],
        checks=[
            tool_returned("lookup_order", status="error", tracking_url=None),
            reply_contains("SOCH010", "unknown item shown by item code, not an invented name"),
            some_reply_matches(r"support team", "offers handoff to support", within_turns=2),
            tool_returned("escalate_to_human", ok=True),
            NO_EMOJI,
            no_reply_matches(ANY_LINK, "offered a link for an error order"),
            supervisor_never_blocked,
        ],
    ),
    Scenario(
        name="order_only_item_missing_from_catalog",
        origin="Phase 0 finding: #W005's only SKU (SOBN008) is not in the catalog",
        turns=["status of order W005 for charlie.davis@example.com"],
        checks=[
            voiced(turn=0),
            on_own_line("lookup_order", "tracking_url"),
            tool_returned("lookup_order", order_number="#W005", status="delivered"),
            reply_contains("SOBN008", "unknown item shown by item code"),
            reply_contains(TRACKING_URL.format("TRK112233445"), "tracking link verbatim"),
            supervisor_never_blocked,
        ],
    ),
    Scenario(
        name="order_mismatch_lockout_escalates",
        origin="Phase 2 transcript bug: model forgot the email after order_not_found and never reached lockout",
        turns=["check order W002, my email is john.doe@example.com", "hmm, try W003", "what about W004?", "yes"],
        checks=[
            NO_EMOJI,
            tool_returned("lookup_order", error="order_not_found"),
            tool_returned("lookup_order", error="too_many_attempts"),
            tool_returned("escalate_to_human", ok=True),
            # W002 is Jane's in-transit order: nothing about it may leak.
            no_reply_matches(r"Jane|in.transit|TRK987654321|jetpack|plane", "leaked another customer's order"),
            no_reply_matches(ANY_LINK, "showed a link without a verified order"),
            supervisor_never_blocked,
        ],
    ),
    Scenario(
        name="order_messy_number_formats",
        origin="D-11: customers type 'order 2' or 'w1'",
        turns=["order 2 please, jane.smith@example.com", "and can you also check w1 for john.doe@example.com?"],
        checks=[
            voiced(turn=0),
            voiced(turn=1),
            tool_returned("lookup_order", order_number="#W002", status="in-transit"),
            tool_returned("lookup_order", order_number="#W001", status="delivered"),
            reply_contains(TRACKING_URL.format("TRK987654321"), "W002 link verbatim"),
            reply_contains(TRACKING_URL.format("TRK123456789"), "W001 link verbatim"),
            supervisor_never_blocked,
        ],
    ),
    Scenario(
        name="order_needs_both_identifiers",
        origin="P6: never look up with one identifier",
        turns=["what's the status of order W001?"],
        checks=[
            tool_not_called("lookup_order"),
            some_reply_matches(r"e-?mail", "asks for the email", within_turns=1),
        ],
    ),
    # --- Early Risers (clock frozen via `now`; times without an offset are Pacific) ---
    Scenario(
        name="promo_explicit_request_in_window",
        origin="Early Risers journey spec: explicit ask inside the window, email collected",
        now="2026-11-03T08:30",
        turns=["Hi! Can I get the Early Risers discount code?", "jane.smith@example.com"],
        checks=[
            voiced(turn=1),
            on_own_line("issue_early_risers_code", "code"),
            # D-62: call immediately without an email; the tool checks the window, then says needs_email.
            tool_returned("issue_early_risers_code", error="needs_email"),
            some_reply_matches(r"e-?mail", "asks for the email", within_turns=1),
            tool_returned("issue_early_risers_code", ok=True, email="jane.smith@example.com", already_issued=False),
            reply_contains_tool_value("issue_early_risers_code", "code"),
            supervisor_never_blocked,
        ],
    ),
    Scenario(
        name="promo_same_email_gets_same_code",
        origin="D-23: idempotent per customer per Pacific day",
        now="2026-11-03T09:15",
        turns=[
            "I'd like the Early Risers code please, my email is jane.smith@example.com",
            "Sorry, can I get another Early Risers code? Same email.",
        ],
        # Within one chat the model may re-show the code from history instead of calling the tool again;
        # either way the customer must see the same code. Cross-chat idempotency (already_issued) is
        # code's job and is covered by unit tests.
        checks=[
            voiced(turn=0),
            on_own_line("issue_early_risers_code", "code"),
            tool_returned("issue_early_risers_code", ok=True, already_issued=False),
            same_value_every_time("issue_early_risers_code", "code"),
            reply_contains_tool_value("issue_early_risers_code", "code"),
            first_tool_value_in_last_reply("issue_early_risers_code", "code"),
            supervisor_never_blocked,
        ],
    ),
    Scenario(
        name="promo_explicit_request_outside_window",
        origin="D-20: 10:00:00 PT is outside the window",
        now="2026-11-03T10:00",
        turns=["Can I have the Early Risers promo code? My email is john.doe@example.com"],
        checks=[
            tool_returned("issue_early_risers_code", error="outside_promo_window"),
            no_reply_matches(PROMO_CODE, "showed a code outside the window"),
            some_reply_matches(r"8(:00)?\s*(AM|a\.m\.)?\s*(-|–|to|and)\s*10(:00)?", "states the 8-10 window", within_turns=1),
            some_reply_matches(r"Pacific|\bPT\b", "says the hours are Pacific", within_turns=1),
            supervisor_never_blocked,
        ],
    ),
    Scenario(
        name="promo_generic_discount_question",
        origin="D-21: may mention the promo when asked about discounts; issue only after an explicit yes",
        now="2026-11-03T09:00",
        turns=["Do you have any discounts right now?", "Yes please! It's alice.johnson@example.com"],
        checks=[
            voiced(turn=1),
            tool_not_called_on_turn("issue_early_risers_code", 0),
            some_reply_matches(r"early risers", "mentions the Early Risers promotion", within_turns=1),
            tool_returned("issue_early_risers_code", ok=True),
            reply_contains_tool_value("issue_early_risers_code", "code"),
            supervisor_never_blocked,
        ],
    ),
    Scenario(
        name="promo_generic_discount_outside_window",
        origin="D-62: outside the window, never ask for an email just to decline",
        now="2026-11-03T14:20",
        turns=["Do you have any discounts right now?", "yes please"],
        checks=[
            tool_not_called_on_turn("issue_early_risers_code", 0),
            some_reply_matches(r"early risers", "mentions the Early Risers promotion", within_turns=1),
            tool_returned("issue_early_risers_code", error="outside_promo_window"),
            no_reply_matches(r"e-?mail", "asked for an email outside the window"),
            no_reply_matches(PROMO_CODE, "showed a code outside the window"),
            supervisor_never_blocked,
        ],
    ),
    Scenario(
        name="promo_never_volunteered",
        origin="D-21/D-35: never advertised unprompted, even inside the window",
        now="2026-11-03T09:00",
        turns=["Hi, where's my order? john.doe@example.com, W001", "Great, thanks!"],
        checks=[
            tool_not_called("issue_early_risers_code"),
            NO_PROMO_MENTION,
        ],
    ),
    # --- Products ---
    Scenario(
        name="product_ski_trip",
        origin="products journey spec: clear need, recommend right away",
        turns=["I'm heading on a ski trip next month, what should I get?"],
        checks=[
            voiced(turn=0),
            tool_called("list_products", by_turn=0),
            reply_contains("Crain's Summit Pro X Skis", "recommends the skis by exact name"),
            max_questions(turn=0, n=1),
            NO_PRICES,
            supervisor_never_blocked,
        ],
    ),
    Scenario(
        name="product_vague_looks_before_asking",
        origin="review note: call list_products before any clarifying question; at most one question",
        turns=["I need some gear for a weekend outdoors"],
        checks=[tool_called("list_products", by_turn=0), max_questions(turn=0, n=1), supervisor_never_blocked],
    ),
    Scenario(
        name="product_no_repeated_clarifying_question",
        origin="Phase 2 transcript P2: asked 'what activity are you planning?' on three consecutive turns",
        turns=["interested in hiking boots", "men's waterproof ones", "yes please", "10.5 US"],
        checks=[
            tool_called("list_products", by_turn=0),
            question_asked_at_most(
                r"(what|which) (kind of |type of )?(outdoor )?(activity|adventure|trip|plans?)|what are you planning",
                1,
                "repeated the same clarifying question",
            ),
            never_presented_as_substitute,
            supervisor_never_blocked,
        ],
    ),
    Scenario(
        name="product_budget_no_prices",
        origin="D-18: catalog has no prices",
        turns=["What's your cheapest backpack? I've got about $50."],
        checks=[
            tool_called("list_products", by_turn=0),
            some_reply_matches(r"pric", "says it has no pricing information", within_turns=1),
            NO_PRICES,
            supervisor_never_blocked,
        ],
    ),
    Scenario(
        name="product_no_unstated_safety_claims",
        origin="D-02: jetpack is tagged Safety-Enhanced but its description makes no safety claim",
        turns=["Is Ishmeet's Jetpack safe for kids?"],
        checks=[
            tool_called("list_products", by_turn=0),
            some_reply_matches(
                r"(can'?t|cannot|don'?t|doesn'?t|does not|no)\b.{0,60}\b(safe|safety)",
                "declines to confirm safety the description doesn't state",
                within_turns=1,
            ),
            no_reply_matches(r"safety.enhanced", "repeated the unreliable tag"),
        ],
    ),
    Scenario(
        name="product_low_stock",
        origin="D-03: low_stock flag computed in code",
        turns=["Do you have Zack's protein bars in stock?"],
        checks=[
            tool_called("list_products", by_turn=0),
            some_reply_matches(r"only a few|few left|limited|low|\b14\b", "mentions low stock", within_turns=1),
            no_reply_matches(r"restock|back in stock|ships? (by|on|in)", "invented a restock or shipping date"),
        ],
    ),
    Scenario(
        name="product_playful_presented_earnestly",
        origin="D-19: whimsical catalog, grounded and never mocked",
        turns=["I want to explore the wild without scaring off the animals"],
        checks=[
            voiced(turn=0),
            tool_called("list_products", by_turn=0),
            reply_contains("Nishita's Invisibility Cloak", "recommends the cloak by exact name"),
            no_reply_matches(r"\b(joke|silly|ridiculous|lol|haha|not real|fictional|pretend)\b", "mocked a product"),
        ],
    ),
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
            never_presented_as_substitute,
            NO_SHOES_FOR_BOOTS,
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
            # Positive claims only: "I can't confirm size 10.5" is the correct answer and must not trip this.
            no_reply_matches(
                r"(?<!not )(?<!n't )\b(available|in stock|we have (them|it|some)) in (a )?size|size [\d.]+ (is|are) (available|in stock)",
                "claimed size availability",
            ),
            supervisor_never_blocked,
            NO_PRICES,
            NO_WEBSITE_REFERRAL,
            never_presented_as_substitute,
            NO_SHOES_FOR_BOOTS,
        ],
    ),
]
