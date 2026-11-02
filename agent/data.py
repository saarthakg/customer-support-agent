"""Load and validate the two static datasets once at startup.

Fails loudly on a malformed file: a bad dataset should stop the demo before the
first customer message, not surface as a confusing answer mid-conversation.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

ORDER_STATUSES = frozenset({"delivered", "in-transit", "fulfilled", "error"})
_ORDER_KEYS = {"CustomerName", "Email", "OrderNumber", "ProductsOrdered", "Status", "TrackingNumber"}
_PRODUCT_KEYS = {"ProductName", "SKU", "Inventory", "Description", "Tags"}


class DataError(Exception):
    pass


@dataclass(frozen=True)
class Order:
    customer_name: str
    email: str
    order_number: str  # as stored, e.g. "#W001"
    skus: tuple[str, ...]
    status: str
    tracking_number: str | None


@dataclass(frozen=True)
class Product:
    sku: str
    name: str
    inventory: int
    description: str
    tags: tuple[str, ...]


@dataclass(frozen=True)
class Datasets:
    orders: tuple[Order, ...]
    products: dict[str, Product]  # keyed by SKU

    def find_order(self, email: str, order_number: str) -> Order | None:
        """The order matching BOTH normalized values, or None. Never matches on one alone."""
        for order in self.orders:
            if order.email.lower() == email and order.order_number == order_number:
                return order
        return None


# Normalization lives in code, not the prompt: customers type "w1", "#W001" or
# "order 2", and the model should pass that through untouched (P3).
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Optional "order" / "number" / "no." words, optional "#", optional "W", then digits.
# Bare digits are accepted because every order in the data uses the W prefix (D-11).
_ORDER_NUMBER = re.compile(r"^(?:ORDER\s*)?(?:NUMBER\s*|NO\.?\s*)?#?\s*W?\s*(\d{1,6})$")


def normalize_email(raw: str) -> str | None:
    email = raw.strip().lower()
    return email if _EMAIL.match(email) else None


def normalize_order_number(raw: str) -> str | None:
    """'W001', '#w001', ' #W001 ', 'w1', 'order 2', '1' -> '#W001' style. None if unrecognizable."""
    match = _ORDER_NUMBER.match(raw.strip().upper())
    return f"#W{int(match.group(1)):03d}" if match else None


def load_datasets(data_dir: Path) -> Datasets:
    raw_orders = _read_records(data_dir / "CustomerOrders.json", _ORDER_KEYS)
    raw_products = _read_records(data_dir / "ProductCatalog.json", _PRODUCT_KEYS)

    orders = tuple(
        Order(
            customer_name=r["CustomerName"],
            email=r["Email"],
            order_number=r["OrderNumber"],
            skus=tuple(r["ProductsOrdered"]),
            status=r["Status"],
            tracking_number=r["TrackingNumber"],
        )
        for r in raw_orders
    )
    for o in orders:
        if o.status not in ORDER_STATUSES:
            raise DataError(f"{o.order_number}: unknown status {o.status!r}")

    products = {
        r["SKU"]: Product(
            sku=r["SKU"],
            name=r["ProductName"],
            inventory=r["Inventory"],
            description=r["Description"],
            tags=tuple(r["Tags"]),
        )
        for r in raw_products
    }
    if len(products) != len(raw_products):
        raise DataError("duplicate SKU in product catalog")
    return Datasets(orders=orders, products=products)


def _read_records(path: Path, expected_keys: set[str]) -> list[dict]:
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise DataError(f"cannot load {path.name}: {e}") from e
    if not isinstance(records, list):
        raise DataError(f"{path.name}: expected a JSON list")
    for i, r in enumerate(records):
        if set(r) != expected_keys:
            raise DataError(f"{path.name}[{i}]: keys {sorted(r)} != {sorted(expected_keys)}")
    return records
