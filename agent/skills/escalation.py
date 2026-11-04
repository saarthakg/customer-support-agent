"""Human handoff: escalate_to_human(email, summary, order_number?).

Appends a ticket to logs/handoffs.jsonl and returns its ID, so the agent can
truthfully say the issue was passed on (D-16). In production this would call a
ticketing system; the tool contract would stay the same.
"""

import json
import re
import secrets
from pathlib import Path

from agent.data import Datasets, normalize_email, normalize_order_number
from agent.registry import Deps, Skill, Tool
from agent.supervisor import GuardRule

# No 0/O, 1/I/L: IDs get read aloud and retyped.
_ID_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
# Deliberately looser than the real format (any length, any case) so a malformed
# invented ID like "HT-12345" is still caught by the supervisor.
TICKET_ID_PATTERN = re.compile(r"\bHT-[A-Z0-9]+\b", re.IGNORECASE)

INSTRUCTIONS = """\
Use escalate_to_human to pass an issue to our human support team.
- Offer it (never do it unasked) when an order has status error, when lookup_order returns too_many_attempts, \
or when the customer asks for a person or needs something you can't do (e.g. returns, cancellations, damaged items).
- Call it only after the customer agrees. You need their email; reuse it if they already gave it. \
Include the order number if one came up.
- summary: 1-2 factual sentences in English (for the support team) on what the customer needs and what you found. \
No guesses about causes.
- On success, say you've passed it to our support team and give the ticket_id on its own line. \
Don't promise a response time or how they'll be contacted.
- If they decline, respect that and ask if there's anything else you can help with.
- Tone: something went wrong for this customer. Keep it plain and warm: no emojis, no exclamation marks. \
This overrides the global closing rule: if you close, use a plain "Is there anything else I can help with?", \
never an adventure line."""


class HandoffDesk:
    def __init__(self, deps: Deps) -> None:
        self.datasets: Datasets = deps.datasets
        self.log_path: Path = deps.handoff_log
        self.now = deps.now

    def escalate_to_human(self, email: str, summary: str, order_number: str = "") -> dict:
        normalized_email = normalize_email(email)
        if normalized_email is None:
            return {"ok": False, "error": "invalid_email"}
        if not summary.strip():
            return {"ok": False, "error": "missing_summary"}

        normalized_number = normalize_order_number(order_number) if order_number.strip() else None
        ticket = {
            "ticket_id": "HT-" + "".join(secrets.choice(_ID_ALPHABET) for _ in range(6)),
            "created_at": self.now().isoformat(),
            "email": normalized_email,  # kept unredacted: support needs it to reach the customer (D-38)
            "order_number": normalized_number or order_number.strip() or None,
            # Computed here, never claimed by the model: on the lockout path the order is unverified by definition.
            "verified": bool(normalized_number and self.datasets.find_order(normalized_email, normalized_number)),
            "summary": summary.strip(),
        }
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(ticket, ensure_ascii=False) + "\n")
        # Only the ID goes back to the model; it has no reason to see or repeat the verification flag.
        return {"ok": True, "ticket_id": ticket["ticket_id"]}


def build(deps: Deps) -> Skill:
    desk = HandoffDesk(deps)
    return Skill(
        name="Human handoff",
        instructions=INSTRUCTIONS,
        tools=(
            Tool(
                name="escalate_to_human",
                description=(
                    "File a support ticket handing this issue to a human teammate. Call ONLY after the customer "
                    "agrees to be handed off. Returns a ticket_id to share with the customer."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "email": {"type": "string", "description": "The customer's email address."},
                        "order_number": {
                            "type": "string",
                            "description": "The related order number, if any, as the customer gave it.",
                        },
                        "summary": {
                            "type": "string",
                            "description": "1-2 factual sentences: what the customer needs and what you found.",
                        },
                    },
                    "required": ["email", "summary"],
                },
                handler=desk.escalate_to_human,
            ),
        ),
        guarded_values={"blocked_ticket": GuardRule(TICKET_ID_PATTERN)},
    )
