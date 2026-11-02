from agent.skills.products import LOW_STOCK_THRESHOLD, list_products


def test_returns_full_catalog(datasets):
    result = list_products(datasets)
    assert result["ok"] and len(result["products"]) == 10
    assert {p["sku"] for p in result["products"]} == datasets.products.keys()


def test_tags_are_withheld(datasets):
    # D-02: tags are wrong in ways that cause false claims (energy drink "Weatherproof", jetpack "Safety-Enhanced").
    result = list_products(datasets)
    assert all(p.keys() == {"sku", "name", "description", "inventory", "low_stock"} for p in result["products"])
    flat = str(result)
    assert "Weatherproof" not in flat and "Safety-Enhanced" not in flat


def test_low_stock_flag_is_computed_in_code(datasets):
    by_sku = {p["sku"]: p for p in list_products(datasets)["products"]}
    assert LOW_STOCK_THRESHOLD == 20
    assert {sku for sku, p in by_sku.items() if p["low_stock"]} == {"SOSV008", "SOSV010"}
    assert by_sku["SOSV008"]["inventory"] == 14


def test_descriptions_are_passed_through_unchanged(datasets):
    by_sku = {p["sku"]: p for p in list_products(datasets)["products"]}
    assert by_sku["SOWB004"]["description"] == datasets.products["SOWB004"].description


def test_result_has_no_price_field(datasets):
    assert not any("price" in key.lower() for p in list_products(datasets)["products"] for key in p)
