import pytest

from agent.skills.escalation import TICKET_ID_PATTERN
from agent.supervisor import BASE_PATTERNS, URL_PATTERN, Supervisor, find_all

TRACKING_URL = "https://tools.usps.com/go/TrackConfirmAction?tLabels=TRK123456789"


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Shop here: https://www.sierraoutfitters.com/hiking-boots", {"https://www.sierraoutfitters.com/hiking-boots"}),
        ("see www.sierraoutfitters.com.", {"www.sierraoutfitters.com"}),
        ("visit sierraoutfitters.com/boots!", {"sierraoutfitters.com/boots"}),
        (f"Track it: [here]({TRACKING_URL}).", {TRACKING_URL}),
        (f"Track it:\n{TRACKING_URL}", {TRACKING_URL}),
        ("I have john.doe@example.com on file", set()),  # emails are not links
        ("Your order #W001 and item SOBP001", set()),
        ("No links here, just trail mix.", set()),
    ],
)
def test_url_detection(text, expected):
    assert find_all(URL_PATTERN, text) == expected


def test_blocks_url_no_tool_returned():
    # The real failure from session 9cd1151d (docs/before_grounding.md).
    verdict = Supervisor().check("Explore here:\n\nhttps://www.sierraoutfitters.com/hiking-boots\n\nOnward!")
    assert not verdict.ok
    assert verdict.violations == ["blocked_url: https://www.sierraoutfitters.com/hiking-boots"]
    assert verdict.kinds == ["blocked_url"]


def test_allows_url_a_tool_returned_even_in_a_later_turn():
    sup = Supervisor()
    sup.observe({"ok": True, "tracking_url": TRACKING_URL})
    assert sup.check(f"Here you go:\n{TRACKING_URL}").ok
    assert sup.check(f"Sure, here it is again: {TRACKING_URL}").ok  # D-09: conversation-scoped


def test_blocks_truncated_or_altered_tool_url():
    sup = Supervisor()
    sup.observe({"ok": True, "tracking_url": TRACKING_URL})
    assert not sup.check("Track at https://tools.usps.com").ok
    assert not sup.check(TRACKING_URL.replace("TRK123456789", "TRK000000000")).ok


def test_plain_reply_passes():
    assert Supervisor().check("Happy trails! 🌲 Anything else for your next adventure?").ok


def test_correction_names_the_blocked_value():
    verdict = Supervisor().check("go to sierraoutfitters.com")
    assert "sierraoutfitters.com" in Supervisor.correction(verdict)


# --- ticket IDs (declared by the escalation skill) ---

TICKET_PATTERNS = {**BASE_PATTERNS, "blocked_ticket": TICKET_ID_PATTERN}


def test_blocks_ticket_id_no_tool_returned():
    verdict = Supervisor(TICKET_PATTERNS).check("Your ticket ID is HT-7KQ2XM.")
    assert verdict.violations == ["blocked_ticket: HT-7KQ2XM"]


def test_allows_ticket_id_returned_by_escalation():
    sup = Supervisor(TICKET_PATTERNS)
    sup.observe({"ok": True, "ticket_id": "HT-VQ5R6R"})
    assert sup.check("I've passed this to our support team.\nHT-VQ5R6R").ok


def test_blocks_wrong_or_malformed_ticket_ids_even_after_a_real_one():
    sup = Supervisor(TICKET_PATTERNS)
    sup.observe({"ok": True, "ticket_id": "HT-VQ5R6R"})
    assert not sup.check("Your ticket is HT-VQ5R6X").ok  # one character off
    assert not sup.check("Reference HT-12345").ok  # wrong shape is still caught
