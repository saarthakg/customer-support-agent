"""Load and validate the two static datasets once at startup.

Fails loudly on a malformed file: a bad dataset should stop the demo before the
first customer message, not surface as a confusing answer mid-conversation.
"""

import json
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
