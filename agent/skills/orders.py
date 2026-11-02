"""Order status and tracking: lookup_order(email, order_number).

Code decides: input normalization, identity match (email AND order number),
status meanings, the tracking URL, and the failed-lookup cap. The model decides
when to ask for what, and how to say the result.
"""

from agent.data import Datasets, normalize_email, normalize_order_number
from agent.registry import Deps, Skill, Tool

TRACKING_URL_TEMPLATE = "https://tools.usps.com/go/TrackConfirmAction?tLabels={tracking_number}"

# The order space is tiny (W001-W010) and emails are guessable, so a prompt rule
# isn't enough to stop enumeration. Counted per session, never reset (D-13).
MAX_FAILED_LOOKUPS = 3

# What each status means to the customer, defined once here so the model relays
# it instead of improvising (D-07, D-14, D-15). How to say it is in INSTRUCTIONS.
STATUS_MEANINGS = {
    "delivered": "The order has been delivered.",
    "in-transit": "The order has shipped and is on its way.",
    "fulfilled": (
        "The order is packed and getting ready to ship. It hasn't been handed to the carrier yet, "
        "so there is no tracking number yet."
    ),
    "error": (
        "There is a problem with this order that our support team needs to resolve. "
        "The cause is not known here."
    ),
}

INSTRUCTIONS = """\
Use lookup_order for any question about an order's status, tracking or contents.
- It needs BOTH the customer's email and order number. Ask only for whichever is missing. Pass both \
exactly as the customer typed them; the tool handles formats like "w1" or "order 2".
- Never call it with a guessed or placeholder value.
- Remember the email and order number given earlier in the conversation. If the customer corrects one \
("try W003"), reuse the other and call lookup_order again right away.

On success:
- Open with the status in plain words, based on status_meaning. You may use the customer's first name.
- If tracking_url is present, put it on its own line exactly as returned. If it is null, there is no link: don't offer one.
- Mention the items by name. For an item whose name is null, say "an item (item code <sku>)". Never guess what it is.
- fulfilled: it's packed and getting ready to ship, and tracking isn't available yet. Don't promise a ship date.
- error: no emojis and no exclamation marks. Apologize, say there's a problem with the order that our support \
team needs to resolve, don't guess the cause, and offer to pass it to our support team.

Errors:
- order_not_found: say you couldn't find an order matching that email and order number together, and ask them \
to double-check both. Never suggest which one is wrong.
- invalid_email / invalid_order_number: ask them to re-check that one value (order numbers look like W001).
- too_many_attempts: don't look anything up again. Apologize and offer to pass the request to our support team."""


class OrderLookup:
    """Holds the per-session failed-lookup count; one instance per conversation."""

    def __init__(self, datasets: Datasets) -> None:
        self.datasets = datasets
        self.failed_lookups = 0

    def lookup_order(self, email: str, order_number: str) -> dict:
        if self.failed_lookups >= MAX_FAILED_LOOKUPS:
            return {"ok": False, "error": "too_many_attempts"}
        normalized_email = normalize_email(email)
        if normalized_email is None:
            return {"ok": False, "error": "invalid_email"}
        normalized_number = normalize_order_number(order_number)
        if normalized_number is None:
            return {"ok": False, "error": "invalid_order_number"}

        order = self.datasets.find_order(normalized_email, normalized_number)
        if order is None:
            # Same error whether the order doesn't exist or belongs to another email,
            # so the tool can't be used to discover either (D-12).
            self.failed_lookups += 1
            if self.failed_lookups >= MAX_FAILED_LOOKUPS:
                return {"ok": False, "error": "too_many_attempts"}
            return {"ok": False, "error": "order_not_found"}

        products = self.datasets.products
        return {
            "ok": True,
            "order_number": order.order_number,
            "customer_first_name": order.customer_name.split()[0],
            "status": order.status,
            "status_meaning": STATUS_MEANINGS[order.status],
            # Unknown SKUs get name None so the model can't be tempted to fill one in (D-17).
            "items": [
                {"sku": sku, "name": products[sku].name if sku in products else None} for sku in order.skus
            ],
            "tracking_url": (
                TRACKING_URL_TEMPLATE.format(tracking_number=order.tracking_number)
                if order.tracking_number
                else None
            ),
        }


def build(deps: Deps) -> Skill:
    lookup = OrderLookup(deps.datasets)
    return Skill(
        name="Order status and tracking",
        instructions=INSTRUCTIONS,
        tools=(
            Tool(
                name="lookup_order",
                description=(
                    "Look up an order's status, items and tracking link. Requires BOTH the customer's email "
                    "and order number; ask for whichever is missing before calling. Pass values exactly as "
                    "the customer gave them (formats like 'w1', '#W001' or 'order 2' are handled here). "
                    "Returns order_not_found if the two don't belong to the same order."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "email": {"type": "string", "description": "The customer's email address, as given."},
                        "order_number": {
                            "type": "string",
                            "description": "The order number as given, e.g. 'W001', '#W001', 'order 1'.",
                        },
                    },
                    "required": ["email", "order_number"],
                },
                handler=lookup.lookup_order,
            ),
        ),
    )
