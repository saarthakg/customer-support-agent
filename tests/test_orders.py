import json

import pytest

from agent.data import normalize_email, normalize_order_number
from agent.skills.orders import MAX_FAILED_LOOKUPS, STATUS_MEANINGS, OrderLookup


@pytest.fixture
def lookup(datasets):
    return OrderLookup(datasets)


# --- normalization ---

@pytest.mark.parametrize(
    "raw",
    [
        "W001", "#W001", "w001", " #W001 ", "#w001", "w1", "1", "001",
        "order 1", "Order #W001", "order number 1", "no. 1", "#W 001",
    ],
)
def test_order_number_variants_normalize(raw):
    assert normalize_order_number(raw) == "#W001"


@pytest.mark.parametrize(
    "raw", ["W001.", "it's W001, thanks", "my order is #w001", "W001 please", "(W001)", "order W1!"]
)
def test_one_order_number_inside_other_text_is_extracted(raw):
    # D-72: customers paste numbers mid-sentence; the model passes text "exactly as typed".
    assert normalize_order_number(raw) == "#W001"


@pytest.mark.parametrize(
    "raw", ["", "order", "WX1", "W001 W002", "A001", "W-1", "W001 and W002", "SOWB004", "order 2 please"]
)
def test_unrecognizable_order_numbers(raw):
    # Two order numbers are ambiguous, a SKU is not an order number, and bare digits only count on their own.
    assert normalize_order_number(raw) is None


def test_email_normalization():
    assert normalize_email("  John.Doe@Example.COM ") == "john.doe@example.com"
    assert normalize_email("john") is None
    assert normalize_email("john doe@example.com") is None


@pytest.mark.parametrize("raw", ["john.doe@example.com.", "<john.doe@example.com>", "mailto:john.doe@example.com", '"john.doe@example.com",'])
def test_email_wrapping_from_pastes_is_stripped(raw):
    assert normalize_email(raw) == "john.doe@example.com"


@pytest.mark.parametrize(
    "raw", ["john@example", "john@@example.com", "@example.com", "john.doe@example.com jdoe@work.com", "a@x.com,b@y.com"]
)
def test_malformed_or_doubled_emails_are_rejected(raw):
    assert normalize_email(raw) is None


def test_pasted_punctuation_does_not_burn_a_lookup(lookup):
    # Without stripping, "john.doe@example.com." was a valid-looking email that matched nothing: a counted failure.
    assert lookup.lookup_order("john.doe@example.com.", "W001.")["ok"]
    assert lookup.failed_lookups == 0


# --- each status ---

def test_delivered_has_tracking_link(lookup):
    r = lookup.lookup_order("john.doe@example.com", "W001")
    assert r["ok"] and r["status"] == "delivered"
    assert r["tracking_url"] == "https://tools.usps.com/go/TrackConfirmAction?tLabels=TRK123456789"
    assert r["customer_first_name"] == "John"
    assert r["items"] == [
        {"sku": "SOBP001", "name": "Bhavish's Backcountry Blaze Backpack"},
        {"sku": "SOWB004", "name": "Beth's Caffeinated Energy Drink"},
    ]


def test_in_transit_has_tracking_link(lookup):
    r = lookup.lookup_order("jane.smith@example.com", "#W002")
    assert r["status"] == "in-transit"
    assert r["tracking_url"].endswith("tLabels=TRK987654321")


def test_fulfilled_has_no_link(lookup):
    r = lookup.lookup_order("alice.johnson@example.com", "w3")
    assert r["status"] == "fulfilled"
    assert r["tracking_url"] is None
    assert "no tracking number yet" in r["status_meaning"]


def test_error_has_no_link_and_unknown_sku_has_no_name(lookup):
    r = lookup.lookup_order("bob.brown@example.com", "order 4")
    assert r["status"] == "error" and r["tracking_url"] is None
    assert r["status_meaning"] == STATUS_MEANINGS["error"]
    assert r["items"] == [{"sku": "SOSV007", "name": "Nishita's Invisibility Cloak"}, {"sku": "SOCH010", "name": None}]


def test_order_whose_only_item_is_missing_from_catalog(lookup):
    r = lookup.lookup_order("charlie.davis@example.com", "W005")
    assert r["ok"] and r["items"] == [{"sku": "SOBN008", "name": None}]


def test_every_status_has_a_meaning():
    from agent.data import ORDER_STATUSES

    assert STATUS_MEANINGS.keys() == ORDER_STATUSES


# --- identity and errors ---

def test_mismatch_returns_generic_error_and_no_data(lookup):
    r = lookup.lookup_order("john.doe@example.com", "W002")  # W002 is Jane's
    assert r == {"ok": False, "error": "order_not_found"}


def test_unknown_order_returns_same_error_as_mismatch(lookup):
    assert lookup.lookup_order("john.doe@example.com", "W099") == {"ok": False, "error": "order_not_found"}


def test_invalid_inputs(lookup):
    assert lookup.lookup_order("not-an-email", "W001")["error"] == "invalid_email"
    assert lookup.lookup_order("john.doe@example.com", "banana")["error"] == "invalid_order_number"


def test_lockout_after_failed_lookups_blocks_even_correct_pair(lookup):
    results = [lookup.lookup_order("john.doe@example.com", f"W00{n}") for n in (2, 3, 4)]
    assert [r["error"] for r in results] == ["order_not_found", "order_not_found", "too_many_attempts"]
    assert MAX_FAILED_LOOKUPS == 3
    assert lookup.lookup_order("john.doe@example.com", "W001") == {"ok": False, "error": "too_many_attempts"}


def test_malformed_inputs_do_not_count_toward_lockout(lookup):
    for _ in range(5):
        lookup.lookup_order("nope", "W001")
        lookup.lookup_order("john.doe@example.com", "banana")
    assert lookup.lookup_order("john.doe@example.com", "W001")["ok"]


def test_lockout_is_per_session(datasets):
    first = OrderLookup(datasets)
    for n in (2, 3, 4):
        first.lookup_order("john.doe@example.com", f"W00{n}")
    assert OrderLookup(datasets).lookup_order("john.doe@example.com", "W001")["ok"]


def test_success_says_identity_is_verified(lookup):
    assert lookup.lookup_order("john.doe@example.com", "W001")["identity_verified"] is True


def test_verified_identity_reaches_the_model_on_later_turns(deps):
    # D-70: the fact lives in the tool result, which stays in history, so every later model call sees it.
    from agent.loop import Agent
    from agent.skills import orders
    from tests.fakes import FakeLLM, calls, text

    llm = FakeLLM(
        calls(("lookup_order", '{"email": "bob.brown@example.com", "order_number": "W004"}')),
        text("I'm sorry, there's a problem with order #W004. Shall I pass it to our support team?"),
        text("Done."),
    )
    agent = Agent(llm, skills=[orders.build(deps)])
    agent.respond("W004, bob.brown@example.com")
    agent.respond("yes please")

    next_turn = llm.seen_messages[2]
    tool_results = [json.loads(m["content"]) for m in next_turn if m["role"] == "tool"]
    assert tool_results and tool_results[0]["identity_verified"] is True
    spec = next_turn[0]["content"]
    assert "identity_verified is true" in spec and "never read them back" in spec


def test_result_never_includes_email_or_full_name(lookup):
    r = lookup.lookup_order("john.doe@example.com", "W001")
    flat = str(r)
    assert "john.doe@example.com" not in flat and "John Doe" not in flat


# --- lockout boundaries: the cap counts failures, not attempts ---

def test_two_failures_then_correct_third_lookup_succeeds(lookup):
    assert lookup.lookup_order("john.doe@example.com", "W002")["error"] == "order_not_found"
    assert lookup.lookup_order("john.doe@example.com", "W003")["error"] == "order_not_found"
    assert lookup.lookup_order("john.doe@example.com", "W001")["ok"]


def test_three_failures_then_blocked(lookup):
    errors = [lookup.lookup_order("john.doe@example.com", n)["error"] for n in ("W002", "W003", "W004")]
    assert errors == ["order_not_found", "order_not_found", "too_many_attempts"]
    assert lookup.lookup_order("john.doe@example.com", "W001")["error"] == "too_many_attempts"


def test_success_does_not_reset_failure_count(lookup):
    lookup.lookup_order("john.doe@example.com", "W002")
    lookup.lookup_order("john.doe@example.com", "W001")  # success
    lookup.lookup_order("john.doe@example.com", "W003")
    assert lookup.lookup_order("john.doe@example.com", "W004")["error"] == "too_many_attempts"
