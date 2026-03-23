"""Tests for InventoryEstimator — stock estimation and reorder logic."""

from __future__ import annotations

import pytest

from bizops.parsers.inventory import InventoryEstimator
from bizops.utils.config import BizOpsConfig, VendorConfig


@pytest.fixture
def config():
    return BizOpsConfig(
        vendors=[
            VendorConfig(name="Sysco", email_patterns=["sysco"], category="food_supplies"),
            VendorConfig(name="Om Produce", email_patterns=["om"], category="produce"),
            VendorConfig(name="Yaman Halal", email_patterns=["yaman"], category="meat"),
        ],
    )


@pytest.fixture
def engine(config):
    return InventoryEstimator(config)


def _inv(vendor="Sysco", amount=500, date="2026-03-10"):
    return {"vendor": vendor, "amount": amount, "date": date, "transaction_type": "payment"}


def _toast(net_sales=1000, date="2026-03-15"):
    return {"net_sales": net_sales, "date": date}


# ── Stock Estimation ─────────────────────────────────────────


class TestEstimateStock:
    def test_basic_estimate(self, engine):
        invoices = [_inv("Sysco", 3000, "2026-03-01")]
        toast = [_toast(1000, f"2026-03-{d:02d}") for d in range(1, 16)]

        data = engine.estimate_stock(invoices, toast, as_of_date="2026-03-15")

        assert data["as_of"] == "2026-03-15"
        assert len(data["items"]) > 0
        food = next(i for i in data["items"] if i["category"] == "food_supplies")
        assert food["total_purchased"] == 3000
        assert food["days_since_purchase"] == 14

    def test_low_stock_detected(self, engine):
        invoices = [_inv("Sysco", 500, "2026-03-01")]
        toast = [_toast(1000, f"2026-03-{d:02d}") for d in range(1, 16)]

        data = engine.estimate_stock(invoices, toast, as_of_date="2026-03-15")

        food = next(i for i in data["items"] if i["category"] == "food_supplies")
        # $500 purchased, 14 days ago, ~$300/day usage → should be depleted
        assert food["status"] in ("critical", "low")

    def test_adequate_stock(self, engine):
        invoices = [_inv("Sysco", 10000, "2026-03-14")]  # big order yesterday
        toast = [_toast(1000, f"2026-03-{d:02d}") for d in range(1, 16)]

        data = engine.estimate_stock(invoices, toast, as_of_date="2026-03-15")

        food = next(i for i in data["items"] if i["category"] == "food_supplies")
        assert food["status"] == "adequate"
        assert food["days_since_purchase"] == 1

    def test_multiple_categories(self, engine):
        invoices = [
            _inv("Sysco", 3000, "2026-03-10"),
            _inv("Om Produce", 800, "2026-03-12"),
            _inv("Yaman Halal", 1500, "2026-03-08"),
        ]
        toast = [_toast(1000)] * 15

        data = engine.estimate_stock(invoices, toast, as_of_date="2026-03-15")

        categories = [i["category"] for i in data["items"]]
        assert "food_supplies" in categories
        assert "produce" in categories
        assert "meat" in categories

    def test_empty_invoices(self, engine):
        data = engine.estimate_stock([], as_of_date="2026-03-15")

        assert data["items"] == []
        assert data["low_stock_count"] == 0

    def test_total_inventory_value(self, engine):
        invoices = [_inv("Sysco", 5000, "2026-03-14")]

        data = engine.estimate_stock(invoices, as_of_date="2026-03-15")

        assert data["total_inventory_value"] >= 0

    def test_sorted_critical_first(self, engine):
        invoices = [
            _inv("Sysco", 100, "2026-03-01"),     # likely depleted
            _inv("Om Produce", 10000, "2026-03-14"),  # plenty left
        ]
        toast = [_toast(1000)] * 15

        data = engine.estimate_stock(invoices, toast, as_of_date="2026-03-15")

        if len(data["items"]) >= 2:
            status_order = {"critical": 0, "low": 1, "reorder_soon": 2, "adequate": 3}
            first_priority = status_order.get(data["items"][0]["status"], 4)
            second_priority = status_order.get(data["items"][1]["status"], 4)
            assert first_priority <= second_priority

    def test_no_toast_fallback(self, engine):
        invoices = [_inv("Sysco", 3000, "2026-03-01")]

        # Without toast, uses 30-day usage cycle
        data = engine.estimate_stock(invoices, as_of_date="2026-03-15")

        food = next(i for i in data["items"] if i["category"] == "food_supplies")
        assert food["est_daily_usage"] > 0  # should fallback to purchase/30


# ── Reorder List ─────────────────────────────────────────────


class TestReorderList:
    def test_reorder_generated(self, engine):
        invoices = [_inv("Sysco", 200, "2026-03-01")]
        toast = [_toast(1000)] * 15

        reorders = engine.get_reorder_list(invoices, toast, as_of_date="2026-03-15")

        assert len(reorders) >= 1
        assert reorders[0]["vendor"] == "Sysco"

    def test_no_reorders_when_stocked(self, engine):
        invoices = [_inv("Sysco", 20000, "2026-03-14")]
        toast = [_toast(500)] * 15

        reorders = engine.get_reorder_list(invoices, toast, as_of_date="2026-03-15")

        # Should have nothing to reorder
        sysco_reorders = [r for r in reorders if r["vendor"] == "Sysco"]
        assert len(sysco_reorders) == 0

    def test_urgency_levels(self, engine):
        invoices = [
            _inv("Sysco", 100, "2026-03-01"),      # critical
        ]
        toast = [_toast(1000)] * 15

        reorders = engine.get_reorder_list(invoices, toast, as_of_date="2026-03-15")

        if reorders:
            assert reorders[0]["urgency"] in ("order_today", "order_soon", "plan_order")

    def test_suggested_order_value(self, engine):
        invoices = [_inv("Sysco", 200, "2026-03-01")]
        toast = [_toast(1000)] * 15

        reorders = engine.get_reorder_list(invoices, toast, as_of_date="2026-03-15")

        if reorders:
            assert reorders[0]["suggested_order_value"] > 0


# ── Purchase Frequency ───────────────────────────────────────


class TestPurchaseFrequency:
    def test_frequency_analysis(self, engine):
        invoices = [
            _inv("Sysco", 500, "2026-03-01"),
            _inv("Sysco", 600, "2026-03-08"),
            _inv("Sysco", 550, "2026-03-15"),
        ]

        patterns = engine.get_purchase_frequency(invoices)

        assert len(patterns) == 1
        assert patterns[0]["vendor"] == "Sysco"
        assert patterns[0]["order_count"] == 3
        assert patterns[0]["estimated_frequency"] == "weekly"

    def test_biweekly_frequency(self, engine):
        invoices = [
            _inv("Om Produce", 300, "2026-03-01"),
            _inv("Om Produce", 350, "2026-03-15"),
        ]

        patterns = engine.get_purchase_frequency(invoices)

        om = next(p for p in patterns if p["vendor"] == "Om Produce")
        assert om["estimated_frequency"] == "biweekly"

    def test_monthly_frequency(self, engine):
        invoices = [
            _inv("Sysco", 2000, "2026-02-01"),
            _inv("Sysco", 2200, "2026-03-01"),
        ]

        patterns = engine.get_purchase_frequency(invoices)

        assert patterns[0]["estimated_frequency"] == "monthly"

    def test_single_order_skipped(self, engine):
        invoices = [_inv("Sysco", 500, "2026-03-01")]

        patterns = engine.get_purchase_frequency(invoices)
        assert len(patterns) == 0  # needs at least 2

    def test_sorted_by_spend(self, engine):
        invoices = [
            _inv("Sysco", 500, "2026-03-01"),
            _inv("Sysco", 600, "2026-03-08"),
            _inv("Om Produce", 2000, "2026-03-01"),
            _inv("Om Produce", 2500, "2026-03-15"),
        ]

        patterns = engine.get_purchase_frequency(invoices)

        assert patterns[0]["vendor"] == "Om Produce"  # higher total spend


# ── Helpers ──────────────────────────────────────────────────


class TestHelpers:
    def test_vendor_category(self, engine):
        assert engine._vendor_category("Sysco") == "food_supplies"
        assert engine._vendor_category("Om Produce") == "produce"
        assert engine._vendor_category("Unknown Vendor") == "miscellaneous"

    def test_frequency_labels(self, engine):
        assert engine._frequency_label(2) == "multiple_per_week"
        assert engine._frequency_label(7) == "weekly"
        assert engine._frequency_label(14) == "biweekly"
        assert engine._frequency_label(30) == "monthly"
        assert engine._frequency_label(60) == "infrequent"
        assert engine._frequency_label(0) == "unknown"
