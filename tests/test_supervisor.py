import pytest

from agent.supervisor import URL_PATTERN, Supervisor, find_all

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
