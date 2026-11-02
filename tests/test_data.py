import json

import pytest

from agent import config
from agent.data import ORDER_STATUSES, DataError, load_datasets


@pytest.fixture(scope="module")
def datasets():
    return load_datasets(config.DATA_DIR)


def test_ten_orders_and_ten_products(datasets):
    assert len(datasets.orders) == 10
    assert len(datasets.products) == 10


def test_order_fields_match_known_data_realities(datasets):
    by_number = {o.order_number: o for o in datasets.orders}
    assert {o.status for o in datasets.orders} == ORDER_STATUSES
    # fulfilled and error orders have no tracking number; everything else does
    for o in datasets.orders:
        assert (o.tracking_number is None) == (o.status in {"fulfilled", "error"})
    assert by_number["#W003"].status == "fulfilled"
    assert by_number["#W004"].status == "error"


def test_three_ordered_skus_are_missing_from_catalog(datasets):
    ordered = {sku for o in datasets.orders for sku in o.skus}
    assert ordered - datasets.products.keys() == {"SOCH010", "SOBN008", "SOGK009"}


def test_source_text_preserved_verbatim(datasets):
    # Typos and stray punctuation in the source are intentionally kept (DECISIONS D-01).
    assert "Caffnated" in datasets.products["SOWB004"].description
    assert datasets.products["SOJT005"].description.endswith("experience. .")


def test_rejects_unexpected_keys(tmp_path):
    (tmp_path / "CustomerOrders.json").write_text(json.dumps([{"Email": "x"}]))
    (tmp_path / "ProductCatalog.json").write_text("[]")
    with pytest.raises(DataError, match="keys"):
        load_datasets(tmp_path)


def test_rejects_unknown_status(tmp_path):
    order = {
        "CustomerName": "A", "Email": "a@b.c", "OrderNumber": "#W1",
        "ProductsOrdered": [], "Status": "lost", "TrackingNumber": None,
    }
    (tmp_path / "CustomerOrders.json").write_text(json.dumps([order]))
    (tmp_path / "ProductCatalog.json").write_text("[]")
    with pytest.raises(DataError, match="unknown status"):
        load_datasets(tmp_path)
