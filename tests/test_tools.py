import pytest

from app.tools import analytics, build_registry
from app.tools.base import ToolError
from app.tools.schema import to_llm_schema
from app.schemas import ReportSubmission


def test_pct_change():
    assert analytics.pct_change(75, 100) == -25.0
    assert analytics.pct_change(10, 0) is None


def test_compare_and_declining():
    cur = [{"sku": "A", "name": "A", "category": "x", "revenue": 50.0, "units": 5}]
    prev = [{"sku": "A", "name": "A", "category": "x", "revenue": 100.0, "units": 10},
            {"sku": "B", "name": "B", "category": "x", "revenue": 20.0, "units": 2}]
    dec = analytics.declining(analytics.compare_products(cur, prev), 5)
    assert [d["sku"] for d in dec] == ["A", "B"]          # biggest absolute drop first
    assert dec[1]["revenue_change_pct"] == -100.0         # product that stopped selling


def test_sales_summary_ignores_cancelled(sample_data, settings):
    r = build_registry(settings).execute("get_sales_summary", {"start_date": "2026-10-01", "end_date": "2026-10-15"})
    assert r.data["total_revenue"] == 30000.0
    assert r.data["total_orders"] == 2
    assert r.data["units_sold"] == 112
    assert r.data["average_order_value"] == 15000.0
    assert r.sources[0]["tables"] == ["orders", "order_items"]


def test_find_declining_products(sample_data, settings):
    r = build_registry(settings).execute("find_declining_products", {
        "current_start": "2026-10-01", "current_end": "2026-10-15",
        "previous_start": "2026-09-01", "previous_end": "2026-09-15", "min_decline_pct": 5})
    dec = r.data["declining_products"]
    assert [d["sku"] for d in dec] == ["P1", "P4"]
    assert dec[0]["revenue_change_pct"] == -60.0 and dec[1]["revenue_change_pct"] == -100.0


def test_inventory_low_stock(sample_data, settings):
    r = build_registry(settings).execute("get_inventory_status", {})
    assert [i["sku"] for i in r.data["items"]] == ["P2"]
    assert r.data["items"][0]["shortfall"] == 5


def test_date_ranges(settings):
    d = build_registry(settings).execute("get_date_ranges", {}).data
    assert d["this_month_to_date"] == {"start_date": "2026-10-01", "end_date": "2026-10-15"}
    assert d["last_month_same_days"] == {"start_date": "2026-09-01", "end_date": "2026-09-15"}


def test_validation_errors_are_readable(sample_data, settings):
    reg = build_registry(settings)
    with pytest.raises(ToolError, match="YYYY-MM-DD"):
        reg.execute("get_sales_summary", {"start_date": "yesterday", "end_date": "2026-10-15"})
    with pytest.raises(ToolError, match="Invalid arguments"):
        reg.execute("get_sales_summary", {"start_date": "2026-10-01"})
    with pytest.raises(ToolError, match="Unknown tool"):
        reg.execute("drop_tables", {})


def test_default_registry_is_read_only(settings):
    reg = build_registry(settings)
    assert not any(t.mutating or t.requires_approval for t in reg.all())
    assert "create_restock_draft" not in reg.names()


def test_llm_schema_is_flat():
    schema = to_llm_schema(ReportSubmission)
    text = str(schema)
    assert "$ref" not in text and "$defs" not in text and "anyOf" not in text
    assert "title" in schema["properties"]            # field named 'title' must survive cleaning
    assert "properties" in schema["properties"]["key_metrics"]["items"]
