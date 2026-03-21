"""Tests for the BizOps MCP server tools."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from bizops.mcp_server import (
    _resolve_dates,
    _top_vendors,
    get_invoices,
    get_expenses,
    get_toast_sales,
    get_vendor_summary,
    get_pl_summary,
    list_expense_categories,
    list_vendors,
)
from bizops.utils.config import BizOpsConfig, VendorConfig


# ──────────────────────────────────────────────────────────────
#  Fixtures
# ──────────────────────────────────────────────────────────────


@pytest.fixture
def mock_config():
    """A BizOpsConfig for testing."""
    return BizOpsConfig(
        vendors=[
            VendorConfig(name="Sysco", email_patterns=["sysco.com"], category="food_supplies"),
            VendorConfig(name="Om Produce", email_patterns=["omproduce"], category="produce"),
        ]
    )


@pytest.fixture
def sample_invoices():
    return [
        {"vendor": "Sysco", "amount": 1250.00, "date": "2026-03-01", "subject": "Invoice"},
        {"vendor": "Om Produce", "amount": 340.50, "date": "2026-03-05", "subject": "Delivery"},
        {"vendor": "Sysco", "amount": 980.00, "date": "2026-03-10", "subject": "Invoice"},
    ]


@pytest.fixture
def sample_expenses():
    return {
        "period": {"start": "2026-03-01", "end": "2026-03-21"},
        "revenue": {"gross_sales": 15000.0, "net_sales": 14200.0, "tax": 800.0, "tips": 1200.0},
        "expenses_by_category": {
            "food_supplies": [
                {"vendor": "Sysco", "amount": 1250.00, "date": "2026-03-01"},
                {"vendor": "Sysco", "amount": 980.00, "date": "2026-03-10"},
            ],
            "produce": [
                {"vendor": "Om Produce", "amount": 340.50, "date": "2026-03-05"},
            ],
            "utilities": [],
        },
        "totals": {"total_revenue": 14200.0, "total_expenses": 2570.50, "net_profit": 11629.50},
    }


@pytest.fixture
def sample_toast():
    return [
        {"date": "2026-03-01", "gross_sales": 5000, "net_sales": 4700, "tax": 300, "tips": 400, "total_orders": 120},
        {"date": "2026-03-02", "gross_sales": 4500, "net_sales": 4200, "tax": 280, "tips": 350, "total_orders": 105},
    ]


# ──────────────────────────────────────────────────────────────
#  _resolve_dates
# ──────────────────────────────────────────────────────────────


def test_resolve_dates_today():
    start, end = _resolve_dates("today")
    assert start == end
    assert len(start) == 10  # YYYY-MM-DD


def test_resolve_dates_week():
    start, end = _resolve_dates("week")
    assert start <= end


def test_resolve_dates_month():
    start, end = _resolve_dates("month")
    assert start.endswith("-01")
    assert start <= end


def test_resolve_dates_quarter():
    start, end = _resolve_dates("quarter")
    assert start <= end


def test_resolve_dates_default():
    """Unknown period defaults to month."""
    start, end = _resolve_dates("unknown")
    assert start.endswith("-01")


# ──────────────────────────────────────────────────────────────
#  _top_vendors
# ──────────────────────────────────────────────────────────────


def test_top_vendors():
    items = [
        {"vendor": "A", "amount": 100},
        {"vendor": "B", "amount": 200},
        {"vendor": "A", "amount": 50},
    ]
    result = _top_vendors(items, limit=2)
    assert len(result) == 2
    assert result[0]["vendor"] == "B"
    assert result[0]["total"] == 200.0
    assert result[1]["vendor"] == "A"
    assert result[1]["total"] == 150.0


def test_top_vendors_empty():
    assert _top_vendors([], limit=5) == []


# ──────────────────────────────────────────────────────────────
#  get_invoices
# ──────────────────────────────────────────────────────────────


@patch("bizops.mcp_server.load_invoices")
@patch("bizops.mcp_server.load_config")
def test_get_invoices_all(mock_config, mock_load, sample_invoices):
    mock_config.return_value = BizOpsConfig()
    mock_load.return_value = sample_invoices

    result = json.loads(get_invoices(period="month"))
    assert result["count"] == 3
    assert result["total_amount"] == 2570.50


@patch("bizops.mcp_server.load_invoices")
@patch("bizops.mcp_server.load_config")
def test_get_invoices_vendor_filter(mock_config, mock_load, sample_invoices):
    mock_config.return_value = BizOpsConfig()
    mock_load.return_value = sample_invoices

    result = json.loads(get_invoices(period="month", vendor="sysco"))
    assert result["count"] == 2
    assert result["total_amount"] == 2230.00


@patch("bizops.mcp_server.load_invoices")
@patch("bizops.mcp_server.load_config")
def test_get_invoices_empty(mock_config, mock_load):
    mock_config.return_value = BizOpsConfig()
    mock_load.return_value = []

    result = json.loads(get_invoices())
    assert result["count"] == 0
    assert result["total_amount"] == 0


# ──────────────────────────────────────────────────────────────
#  get_expenses
# ──────────────────────────────────────────────────────────────


@patch("bizops.mcp_server.load_expenses")
@patch("bizops.mcp_server.load_config")
def test_get_expenses_with_data(mock_config, mock_load, sample_expenses):
    mock_config.return_value = BizOpsConfig()
    mock_load.return_value = sample_expenses

    result = json.loads(get_expenses(period="month"))
    assert "revenue" in result
    assert "totals" in result
    assert "expenses_by_category" in result
    assert result["expenses_by_category"]["food_supplies"]["total"] == 2230.0


@patch("bizops.mcp_server.load_expenses")
@patch("bizops.mcp_server.load_config")
def test_get_expenses_no_data(mock_config, mock_load):
    mock_config.return_value = BizOpsConfig()
    mock_load.return_value = {}

    result = json.loads(get_expenses())
    assert "message" in result


# ──────────────────────────────────────────────────────────────
#  get_toast_sales
# ──────────────────────────────────────────────────────────────


@patch("bizops.mcp_server.load_toast_reports")
@patch("bizops.mcp_server.load_config")
def test_get_toast_sales_with_data(mock_config, mock_load, sample_toast):
    mock_config.return_value = BizOpsConfig()
    mock_load.return_value = sample_toast

    result = json.loads(get_toast_sales(period="month"))
    assert result["days"] == 2
    assert result["totals"]["gross_sales"] == 9500
    assert result["totals"]["total_orders"] == 225
    assert len(result["daily"]) == 2


@patch("bizops.mcp_server.load_toast_reports")
@patch("bizops.mcp_server.load_config")
def test_get_toast_sales_empty(mock_config, mock_load):
    mock_config.return_value = BizOpsConfig()
    mock_load.return_value = []

    result = json.loads(get_toast_sales())
    assert result["days"] == 0
    assert "message" in result


# ──────────────────────────────────────────────────────────────
#  get_vendor_summary
# ──────────────────────────────────────────────────────────────


@patch("bizops.mcp_server.load_invoices")
@patch("bizops.mcp_server.load_config")
def test_get_vendor_summary(mock_config, mock_load, sample_invoices):
    mock_config.return_value = BizOpsConfig()
    mock_load.return_value = sample_invoices

    result = json.loads(get_vendor_summary(period="month"))
    assert result["total_vendors"] == 2
    assert result["total_spend"] == 2570.50
    # Sysco should be first (highest spend)
    assert result["vendors"][0]["vendor"] == "Sysco"
    assert result["vendors"][0]["total_spend"] == 2230.0


# ──────────────────────────────────────────────────────────────
#  get_pl_summary
# ──────────────────────────────────────────────────────────────


@patch("bizops.mcp_server.load_expenses")
@patch("bizops.mcp_server.load_config")
def test_get_pl_summary_with_data(mock_config, mock_load, sample_expenses):
    mock_config.return_value = BizOpsConfig()
    mock_load.return_value = sample_expenses

    result = json.loads(get_pl_summary(period="month"))
    assert result["revenue"]["gross_sales"] == 15000.0
    assert result["net_profit"] == 11629.50
    assert "Food Supplies" in result["expenses"]


@patch("bizops.mcp_server.load_expenses")
@patch("bizops.mcp_server.load_config")
def test_get_pl_summary_no_data(mock_config, mock_load):
    mock_config.return_value = BizOpsConfig()
    mock_load.return_value = {}

    result = json.loads(get_pl_summary())
    assert "message" in result


# ──────────────────────────────────────────────────────────────
#  list_expense_categories
# ──────────────────────────────────────────────────────────────


@patch("bizops.mcp_server.load_config")
def test_list_expense_categories(mock_config):
    mock_config.return_value = BizOpsConfig()

    result = json.loads(list_expense_categories())
    categories = result["categories"]
    assert len(categories) >= 13
    names = [c["name"] for c in categories]
    assert "food_supplies" in names
    assert "utilities" in names
    assert "produce" in names


# ──────────────────────────────────────────────────────────────
#  list_vendors
# ──────────────────────────────────────────────────────────────


@patch("bizops.mcp_server.load_config")
def test_list_vendors(mock_config, mock_config_obj=None):
    mock_config.return_value = BizOpsConfig(
        vendors=[
            VendorConfig(name="Sysco", email_patterns=["sysco.com"], category="food_supplies"),
            VendorConfig(name="Om Produce", email_patterns=["omproduce"], category="produce"),
        ]
    )

    result = json.loads(list_vendors())
    assert result["total_vendors"] == 2
    assert result["vendors"][0]["name"] == "Sysco"
    assert result["vendors"][1]["category"] == "produce"
