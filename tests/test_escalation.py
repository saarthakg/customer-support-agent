import json
import re

from agent.loop import SUPERVISOR_FALLBACK_REPLY, Agent
from agent.skills import escalation
from agent.skills.escalation import HandoffDesk
from tests.conftest import FIXED_NOW
from tests.fakes import FakeLLM, calls, last_tool_result, text


def read_tickets(deps):
    return [json.loads(line) for line in deps.handoff_log.read_text().splitlines()]


def test_files_ticket_and_returns_only_the_id(deps):
    result = HandoffDesk(deps).escalate_to_human(
        email="Bob.Brown@example.com", order_number="W004", summary="Order W004 shows an error status."
    )
    assert result.keys() == {"ok", "ticket_id"} and result["ok"]
    assert re.fullmatch(r"HT-[A-HJ-KM-NP-Z2-9]{6}", result["ticket_id"])

    [ticket] = read_tickets(deps)
    assert ticket == {
        "ticket_id": result["ticket_id"],
        "created_at": FIXED_NOW.isoformat(),
        "email": "bob.brown@example.com",
        "order_number": "#W004",
        "verified": True,
        "summary": "Order W004 shows an error status.",
    }


def test_unverified_when_email_and_order_do_not_match(deps):
    # The lockout path: the customer couldn't prove ownership, support must know that.
    HandoffDesk(deps).escalate_to_human(email="john.doe@example.com", order_number="W004", summary="Locked out.")
    assert read_tickets(deps)[0]["verified"] is False


def test_no_order_number_is_allowed_and_unverified(deps):
    HandoffDesk(deps).escalate_to_human(email="new.customer@example.com", summary="Wants to return an item.")
    ticket = read_tickets(deps)[0]
    assert ticket["order_number"] is None and ticket["verified"] is False


def test_unrecognizable_order_number_is_kept_verbatim_for_support(deps):
    HandoffDesk(deps).escalate_to_human(email="a@b.com", order_number="the blue one", summary="Can't find order.")
    assert read_tickets(deps)[0]["order_number"] == "the blue one"


def test_appends_with_unique_ids(deps):
    desk = HandoffDesk(deps)
    ids = {desk.escalate_to_human(email="a@b.com", summary=f"issue {i}")["ticket_id"] for i in range(20)}
    assert len(ids) == 20 and len(read_tickets(deps)) == 20


def test_rejects_invalid_email_and_empty_summary_without_filing(deps):
    desk = HandoffDesk(deps)
    assert desk.escalate_to_human(email="nope", summary="x") == {"ok": False, "error": "invalid_email"}
    assert desk.escalate_to_human(email="a@b.com", summary="  ") == {"ok": False, "error": "missing_summary"}
    assert not deps.handoff_log.exists()


def test_supervisor_guards_ticket_ids_end_to_end(deps):
    # Real escalation skill + scripted model: only the ticket ID the tool returned may reach the customer.
    skill = escalation.build(deps)
    args = '{"email": "bob.brown@example.com", "order_number": "W004", "summary": "Error order."}'

    invented = Agent(FakeLLM(text("Done! Ticket HT-ABCDEF"), text("Ticket HT-ABCDEF")), skills=[skill])
    assert invented.respond("escalate please").reply == SUPERVISOR_FALLBACK_REPLY

    echo_real_id = lambda messages: text(f"Passed to support.\n{last_tool_result(messages)['ticket_id']}")  # noqa: E731
    agent = Agent(FakeLLM(calls(("escalate_to_human", args)), echo_real_id), skills=[skill])
    result = agent.respond("escalate please")
    assert result.supervisor == "pass"
    assert result.reply.endswith(read_tickets(deps)[0]["ticket_id"])
