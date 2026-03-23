"""Tests for VendorPriceEngine — spending analysis, price changes, negotiation."""

from __future__ import annotations

import pytest

from bizops.parsers.vendor_prices import VendorPriceEngine
from bizops.utils.config import BizOpsConfig, VendorConfig


@pytest.fixture
def config():
    return BizOpsConfig(
        vendors=[
            VendorConfig(name="Sysco", email_patterns=["sysco"], category="food_supplies", aliases=["sysco foods"]),
            VendorConfig(name="Om Produce", email_patterns=["om"], category="produce", aliases=["om"]),
            VendorConfig(name="Yaman Halal", email_patterns=["yaman"], category="meat", aliases=["yaman"]),
        ],
    )


@pytest.fixture
def engine(config):
    return VendorPriceEngine(config)


def _inv(vendor="Sysco", amount=500, date="2026-03-10", txn_type="payment"):
    return {"vendor": vendor, "amount": amount, "date": date, "transaction_type": txn_type}


def _bank(desc="SYSCO FOODS", amount=-500, date="2026-03-12"):
    return {"date": date, "description": desc, "amount": amount, "type": "debit"}


# ── Vendor Spending ──────────────────────────────────────────


class TestVendorSpending:
    def test_basic_spending(self, engine):
        invoices = [
            _inv("Sysco", 500, "2026-03-10"),
            _inv("Sysco", 600, "2026-03-15"),
            _inv("Om Produce", 300, "2026-03-12"),
        ]
        data = engine.get_vendor_spending(invoices)

        assert data["vendor_count"] == 2
        assert data["total_spend"] == 1400.0
        assert data["top_vendor"] == "Sysco"

        sysco = next(v for v in data["vendors"] if v["vendor"] == "Sysco")
        assert sysco["total_spend"] == 1100.0
        assert sysco["invoice_count"] == 2
        assert sysco["avg_per_invoice"] == 550.0

    def test_sorted_by_spend(self, engine):
        invoices = [
            _inv("Om Produce", 1000),
            _inv("Sysco", 500),
            _inv("Yaman Halal", 2000),
        ]
        data = engine.get_vendor_spending(invoices)

        vendors = [v["vendor"] for v in data["vendors"]]
        assert vendors == ["Yaman Halal", "Om Produce", "Sysco"]

    def test_bank_txns_included(self, engine):
        invoices = [_inv("Sysco", 500)]
        bank_txns = [_bank("SYSCO FOODS", -300, "2026-03-14")]

        data = engine.get_vendor_spending(invoices, bank_txns)

        sysco = next(v for v in data["vendors"] if v["vendor"] == "Sysco")
        assert sysco["total_spend"] == 800.0  # 500 + 300

    def test_empty_inputs(self, engine):
        data = engine.get_vendor_spending([])
        assert data["vendor_count"] == 0
        assert data["top_vendor"] is None

    def test_non_payment_skipped(self, engine):
        invoices = [
            _inv("Sysco", 500, txn_type="payment"),
            _inv("Sysco", 100, txn_type="order"),  # informational
        ]
        data = engine.get_vendor_spending(invoices)

        sysco = next(v for v in data["vendors"] if v["vendor"] == "Sysco")
        assert sysco["total_spend"] == 500.0

    def test_min_max_range(self, engine):
        invoices = [
            _inv("Sysco", 200, "2026-03-10"),
            _inv("Sysco", 800, "2026-03-15"),
            _inv("Sysco", 500, "2026-03-20"),
        ]
        data = engine.get_vendor_spending(invoices)

        sysco = next(v for v in data["vendors"] if v["vendor"] == "Sysco")
        assert sysco["min_invoice"] == 200.0
        assert sysco["max_invoice"] == 800.0


# ── Price Changes ────────────────────────────────────────────


class TestPriceChanges:
    def test_increase_detected(self, engine):
        current = [_inv("Sysco", 700), _inv("Sysco", 800)]
        prev = [_inv("Sysco", 500), _inv("Sysco", 500)]

        changes = engine.detect_price_changes(current, prev, threshold_pct=10)

        assert len(changes) == 1
        assert changes[0]["vendor"] == "Sysco"
        assert changes[0]["direction"] == "up"
        assert changes[0]["pct_change"] == 50.0

    def test_decrease_detected(self, engine):
        current = [_inv("Sysco", 300)]
        prev = [_inv("Sysco", 500)]

        changes = engine.detect_price_changes(current, prev, threshold_pct=10)

        assert len(changes) == 1
        assert changes[0]["direction"] == "down"
        assert changes[0]["impact"] == "positive"

    def test_no_change(self, engine):
        current = [_inv("Sysco", 500)]
        prev = [_inv("Sysco", 510)]

        changes = engine.detect_price_changes(current, prev, threshold_pct=10)
        assert len(changes) == 0

    def test_skip_tiny_vendors(self, engine):
        current = [_inv("Sysco", 30)]
        prev = [_inv("Sysco", 20)]

        changes = engine.detect_price_changes(current, prev, threshold_pct=10)
        assert len(changes) == 0  # prev avg < 50

    def test_sorted_by_change(self, engine):
        current = [_inv("Sysco", 700), _inv("Om Produce", 900)]
        prev = [_inv("Sysco", 500), _inv("Om Produce", 500)]

        changes = engine.detect_price_changes(current, prev, threshold_pct=10)

        assert len(changes) == 2
        # Om Produce has larger % change (80% vs 40%)
        assert changes[0]["vendor"] == "Om Produce"


# ── Negotiation Targets ──────────────────────────────────────


class TestNegotiationTargets:
    def test_high_spend_flagged(self, engine):
        # Sysco at 100% of spend
        invoices = [_inv("Sysco", 5000)]

        targets = engine.get_negotiation_targets(invoices)

        assert len(targets) >= 1
        assert targets[0]["vendor"] == "Sysco"
        assert targets[0]["priority"] == "high"
        assert any("volume" in r.lower() or "top vendor" in r.lower() for r in targets[0]["reasons"])

    def test_price_increase_flagged(self, engine):
        current = [_inv("Sysco", 800)]
        prev = [_inv("Sysco", 500)]

        targets = engine.get_negotiation_targets(current, prev)

        sysco = next((t for t in targets if t["vendor"] == "Sysco"), None)
        assert sysco is not None
        assert any("up" in r.lower() or "price" in r.lower() for r in sysco["reasons"])

    def test_frequent_small_orders(self, engine):
        invoices = [_inv("Sysco", 100, f"2026-03-{d:02d}") for d in range(1, 11)]

        targets = engine.get_negotiation_targets(invoices)

        sysco = next((t for t in targets if t["vendor"] == "Sysco"), None)
        assert sysco is not None
        assert any("consolidate" in r.lower() for r in sysco["reasons"])

    def test_empty_inputs(self, engine):
        targets = engine.get_negotiation_targets([])
        assert len(targets) == 0

    def test_sorted_by_priority(self, engine):
        invoices = [
            _inv("Sysco", 5000),  # high priority (top vendor)
            _inv("Om Produce", 200),  # low priority
        ]

        targets = engine.get_negotiation_targets(invoices)

        if len(targets) >= 2:
            priority_order = {"high": 0, "medium": 1, "low": 2}
            for i in range(len(targets) - 1):
                assert priority_order[targets[i]["priority"]] <= priority_order[targets[i + 1]["priority"]]


# ── Vendor Comparison ────────────────────────────────────────


class TestVendorComparison:
    def test_grouped_by_category(self, engine):
        invoices = [
            _inv("Sysco", 500),
            _inv("Om Produce", 300),
            _inv("Yaman Halal", 200),
        ]

        data = engine.get_vendor_comparison(invoices)

        assert "food_supplies" in data["categories"]
        assert "produce" in data["categories"]
        assert "meat" in data["categories"]

    def test_category_filter(self, engine):
        invoices = [
            _inv("Sysco", 500),
            _inv("Om Produce", 300),
        ]

        data = engine.get_vendor_comparison(invoices, category="food_supplies")

        assert "food_supplies" in data["categories"]
        assert "produce" not in data["categories"]

    def test_pct_of_category(self, engine):
        invoices = [
            _inv("Sysco", 700),
            _inv("Om Produce", 300),
        ]

        data = engine.get_vendor_comparison(invoices)

        food = data["categories"]["food_supplies"]
        assert food["vendors"][0]["pct_of_category"] == 100.0


# ── Helpers ──────────────────────────────────────────────────


class TestHelpers:
    def test_price_trend_increasing(self, engine):
        records = [
            {"amount": 100, "date": "2026-03-01"},
            {"amount": 110, "date": "2026-03-05"},
            {"amount": 150, "date": "2026-03-10"},
            {"amount": 160, "date": "2026-03-15"},
        ]
        assert engine._calculate_price_trend(records) == "increasing"

    def test_price_trend_decreasing(self, engine):
        records = [
            {"amount": 200, "date": "2026-03-01"},
            {"amount": 190, "date": "2026-03-05"},
            {"amount": 150, "date": "2026-03-10"},
            {"amount": 140, "date": "2026-03-15"},
        ]
        assert engine._calculate_price_trend(records) == "decreasing"

    def test_price_trend_stable(self, engine):
        records = [
            {"amount": 100, "date": "2026-03-01"},
            {"amount": 102, "date": "2026-03-05"},
            {"amount": 99, "date": "2026-03-10"},
            {"amount": 101, "date": "2026-03-15"},
        ]
        assert engine._calculate_price_trend(records) == "stable"

    def test_price_trend_insufficient_data(self, engine):
        records = [{"amount": 100, "date": "2026-03-01"}]
        assert engine._calculate_price_trend(records) == "insufficient_data"
