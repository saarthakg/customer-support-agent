import pytest

from agent.data import normalize_email, normalize_order_number
from agent.skills.orders import MAX_FAILED_LOOKUPS, STATUS_MEANINGS, OrderLookup


@pytest.fixture
def lookup(datasets):
    return OrderLookup(datasets)


# --- normalization ---

@pytest.mark.parametrize(
    "raw", ["W001", "#W001", "w001", " #W001 ", "#w001", "w1", "1", "001", "order 1", "Order #W001", "order number 1", "no. 1", "#W 001"]
)
def test_order_number_variants_normalize(raw):
    assert normalize_order_number(raw) == "#W001"


@pytest.mark.parametrize("raw", ["", "order", "WX1", "W001 W002", "A001", "W-1"])
def test_unrecognizable_order_numbers(raw):
    assert normalize_order_number(raw) is None


def test_email_normalization():
    assert normalize_email("  John.Doe@Example.COM ") == "john.doe@example.com"
    assert normalize_email("john") is None
    assert normalize_email("john doe@example.com") is None


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


def test_result_never_includes_email_or_full_name(lookup):
    r = lookup.lookup_order("john.doe@example.com", "W001")
    flat = str(r)
    assert "john.doe@example.com" not in flat and "John Doe" not in flat
