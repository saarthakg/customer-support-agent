import re
from datetime import datetime, timezone

import pytest

from agent.clock import PACIFIC, parse_now
from agent.code_store import InMemoryCodeStore, JsonCodeStore
from agent.skills.early_risers import CODE_PATTERN, EarlyRisers, in_window
from agent.supervisor import BASE_PATTERNS, Supervisor

EMAIL = "jane.smith@example.com"


def pt(hour: int, minute: int, second: int = 0, day: int = 3, month: int = 11) -> datetime:
    return datetime(2026, month, day, hour, minute, second, tzinfo=PACIFIC)


def promo_at(moment: datetime, store: InMemoryCodeStore | None = None) -> EarlyRisers:
    return EarlyRisers(now=lambda: moment, store=store or InMemoryCodeStore())


# --- window boundaries: [08:00, 10:00) Pacific (D-20) ---

@pytest.mark.parametrize(
    "moment, expected",
    [
        (pt(7, 59, 59), False),
        (pt(8, 0, 0), True),
        (pt(9, 59, 59), True),
        (pt(10, 0, 0), False),
        (pt(0, 0), False),
        (pt(23, 59), False),
    ],
)
def test_window_boundaries(moment, expected):
    assert in_window(moment) is expected
    assert promo_at(moment).issue_early_risers_code(EMAIL)["ok"] is expected


def test_window_follows_daylight_saving():
    # 15:30 UTC is 08:30 PDT in July (UTC-7) but 07:30 PST in January (UTC-8).
    assert in_window(datetime(2026, 7, 15, 15, 30, tzinfo=timezone.utc))
    assert not in_window(datetime(2026, 1, 15, 15, 30, tzinfo=timezone.utc))


def test_outside_window_explains_hours_and_issues_nothing():
    store = InMemoryCodeStore()
    result = promo_at(pt(10, 0), store).issue_early_risers_code(EMAIL)
    assert result == {
        "ok": False,
        "error": "outside_promo_window",
        "window": "8:00-10:00 AM Pacific Time",
        "current_time_pt": "10:00 AM PT",
    }
    assert store.get(EMAIL, pt(10, 0).date()) is None


def test_current_time_is_reported_in_pacific_even_for_utc_clock():
    result = promo_at(datetime(2026, 11, 3, 15, 59, tzinfo=timezone.utc)).issue_early_risers_code(EMAIL)
    assert result["current_time_pt"] == "7:59 AM PT"


# --- issuance, identity, idempotency (D-22, D-23) ---

def test_issues_readable_code_keyed_to_normalized_email():
    result = promo_at(pt(8, 30)).issue_early_risers_code("  Jane.Smith@Example.COM ")
    assert result["ok"] and result["discount_percent"] == 10
    assert result["email"] == EMAIL
    assert result["already_issued"] is False
    assert re.fullmatch(r"EARLYRISER-[A-HJ-KM-NP-Z2-9]{6}", result["code"])


def test_same_email_same_day_gets_same_code():
    store = InMemoryCodeStore()
    first = promo_at(pt(8, 5), store).issue_early_risers_code(EMAIL)
    again = promo_at(pt(9, 55), store).issue_early_risers_code("JANE.SMITH@example.com")
    assert again["code"] == first["code"]
    assert again["already_issued"] is True


def test_new_day_gets_new_code():
    store = InMemoryCodeStore()
    monday = promo_at(pt(8, 30, day=2), store).issue_early_risers_code(EMAIL)
    tuesday = promo_at(pt(8, 30, day=3), store).issue_early_risers_code(EMAIL)
    assert monday["code"] != tuesday["code"] and tuesday["already_issued"] is False


def test_codes_are_unique_across_customers():
    store = InMemoryCodeStore()
    promo = promo_at(pt(9, 0), store)
    codes = {promo.issue_early_risers_code(f"customer{i}@example.com")["code"] for i in range(200)}
    assert len(codes) == 200


def test_collision_is_redrawn():
    store = InMemoryCodeStore()
    store.put("someone@example.com", pt(9, 0).date(), "EARLYRISER-AAAAAA")
    draws = iter(["EARLYRISER-AAAAAA", "EARLYRISER-BBBBBB"])
    promo = EarlyRisers(now=lambda: pt(9, 0), store=store, new_code=lambda: next(draws))
    assert promo.issue_early_risers_code(EMAIL)["code"] == "EARLYRISER-BBBBBB"


# --- window first, then email (D-62) ---

def test_outside_window_needs_no_email():
    result = promo_at(pt(14, 20)).issue_early_risers_code()
    assert result["error"] == "outside_promo_window" and result["current_time_pt"] == "2:20 PM PT"


def test_outside_window_wins_even_over_a_bad_email():
    assert promo_at(pt(7, 59)).issue_early_risers_code("jane")["error"] == "outside_promo_window"


def test_inside_window_without_email_asks_for_it():
    assert promo_at(pt(8, 30)).issue_early_risers_code() == {"ok": False, "error": "needs_email"}
    assert promo_at(pt(8, 30)).issue_early_risers_code("   ") == {"ok": False, "error": "needs_email"}


def test_inside_window_invalid_email():
    assert promo_at(pt(8, 30)).issue_early_risers_code("jane") == {"ok": False, "error": "invalid_email"}


# --- supervision of codes (D-47) ---

@pytest.mark.parametrize("text", ["EARLYRISER-7KQ2XM", "EARLYBIRD10", "EARLY-RISERS-2026", "SIERRA10"])
def test_code_pattern_catches_real_and_lookalike_codes(text):
    assert CODE_PATTERN.search(f"Use {text} at checkout")


@pytest.mark.parametrize("text", ["the Early Risers promotion", "Sierra Outfitters", "EARLY RISERS runs 8-10", "#W001"])
def test_code_pattern_ignores_prose(text):
    assert not CODE_PATTERN.search(text)


def test_supervisor_blocks_codes_no_tool_issued():
    sup = Supervisor({**BASE_PATTERNS, "blocked_code": CODE_PATTERN})
    sup.observe({"ok": True, "code": "EARLYRISER-7KQ2XM"})
    assert sup.check("Here you go:\nEARLYRISER-7KQ2XM").ok
    assert sup.check("Try EARLYBIRD10 too!").violations == ["blocked_code: EARLYBIRD10"]


# --- --now parsing ---

def test_parse_now_defaults_to_pacific_and_respects_offsets():
    assert parse_now("2026-11-03T08:30") == pt(8, 30)
    assert parse_now("2026-11-03T16:30+00:00") == pt(8, 30)
    assert parse_now("2026-11-03T08:30-08:00") == pt(8, 30)


# --- persistence (D-61) ---

def test_json_store_survives_restart(tmp_path):
    path = tmp_path / "state" / "issued_codes.json"
    first = EarlyRisers(now=lambda: pt(8, 30), store=JsonCodeStore(path)).issue_early_risers_code(EMAIL)
    # A new store instance on the same file is what a CLI restart looks like.
    again = EarlyRisers(now=lambda: pt(9, 45), store=JsonCodeStore(path)).issue_early_risers_code(EMAIL)
    assert again["code"] == first["code"] and again["already_issued"] is True
    assert JsonCodeStore(path).exists(first["code"])
