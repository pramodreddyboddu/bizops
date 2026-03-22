"""Tests for the AlertEngine — anomaly detection and proactive warnings."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest

from bizops.parsers.alerts import AlertEngine
from bizops.utils.config import BizOpsConfig, ProductItem, VendorConfig


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def config():
    return BizOpsConfig(
        vendors=[
            VendorConfig(
                name="Sysco",
                email_patterns=["sysco"],
                category="food_supplies",
                payment_terms="net30",
                aliases=["sysco foods"],
                order_day=1,  # Tuesday
                products=[ProductItem(name="Rice", unit_cost=25.0, par_level=10)],
            ),
            VendorConfig(
                name="Om Produce",
                email_patterns=["om"],
                category="produce",
                payment_terms="cod",
                aliases=["om"],
                order_day=3,  # Thursday
                products=[ProductItem(name="Tomatoes", unit_cost=5.0, par_level=20)],
            ),
        ],
    )


@pytest.fixture
def engine(config):
    return AlertEngine(config)


def _debit(amount, category="food_supplies", desc="SYSCO", date="2026-03-15"):
    return {
        "date": date,
        "description": desc,
        "amount": -abs(amount),
        "abs_amount": abs(amount),
        "type": "debit",
        "category": category,
    }


def _credit(amount, date="2026-03-15"):
    return {"date": date, "amount": amount, "type": "credit"}


def _toast(net_sales, date="2026-03-15"):
    return {"date": date, "net_sales": net_sales, "gross_sales": net_sales * 1.1}


def _inv(vendor="Sysco", amount=500, date="2026-03-10"):
    return {
        "vendor": vendor,
        "amount": amount,
        "date": date,
        "transaction_type": "payment",
    }


# ── Spending Spikes ──────────────────────────────────────────


class TestSpendingSpikes:
    def test_spike_detected(self, engine):
        current = [_debit(1500, "food_supplies"), _debit(300, "food_supplies")]
        prev = [_debit(1000, "food_supplies")]

        alerts = engine.check_spending_spikes(current, prev, threshold_pct=40)

        assert len(alerts) == 1
        assert alerts[0]["type"] == "spending_spike"
        assert alerts[0]["severity"] == "warning"
        assert alerts[0]["pct_change"] == 80.0

    def test_no_spike_under_threshold(self, engine):
        current = [_debit(1100, "food_supplies")]
        prev = [_debit(1000, "food_supplies")]

        alerts = engine.check_spending_spikes(current, prev, threshold_pct=40)
        assert len(alerts) == 0

    def test_skip_tiny_categories(self, engine):
        # Previous period under $100 → skip
        current = [_debit(200, "office")]
        prev = [_debit(50, "office")]

        alerts = engine.check_spending_spikes(current, prev)
        assert len(alerts) == 0

    def test_no_prev_data(self, engine):
        alerts = engine.check_spending_spikes([_debit(500)], [])
        assert len(alerts) == 0

    def test_multiple_categories(self, engine):
        current = [_debit(2000, "food_supplies"), _debit(1500, "produce")]
        prev = [_debit(1000, "food_supplies"), _debit(1000, "produce")]

        alerts = engine.check_spending_spikes(current, prev, threshold_pct=40)
        assert len(alerts) == 2


# ── Vendor Spikes ────────────────────────────────────────────


class TestVendorSpikes:
    def test_vendor_spike(self, engine):
        invoices = [_inv("Sysco", 1500)]
        prev_bank = [_debit(800, "food_supplies", "SYSCO FOODS")]

        alerts = engine.check_vendor_spikes(invoices, prev_bank, threshold_pct=50)

        assert len(alerts) == 1
        assert alerts[0]["type"] == "vendor_spike"
        assert alerts[0]["vendor"] == "Sysco"

    def test_no_spike(self, engine):
        invoices = [_inv("Sysco", 500)]
        prev_bank = [_debit(500, "food_supplies", "SYSCO FOODS")]

        alerts = engine.check_vendor_spikes(invoices, prev_bank)
        assert len(alerts) == 0

    def test_no_prev_data(self, engine):
        alerts = engine.check_vendor_spikes([_inv()], [])
        assert len(alerts) == 0


# ── Sales Anomalies ──────────────────────────────────────────


class TestSalesAnomalies:
    def test_sales_drop_detected(self, engine):
        # Average is ~2000, last day is 1000 → -50% drop
        data = [
            _toast(2000, "2026-03-10"),
            _toast(2000, "2026-03-11"),
            _toast(2000, "2026-03-12"),
            _toast(2000, "2026-03-13"),
            _toast(1000, "2026-03-14"),
        ]

        alerts = engine.check_sales_anomalies(data, threshold_pct=25)

        drops = [a for a in alerts if a["type"] == "sales_drop"]
        assert len(drops) >= 1
        assert drops[0]["severity"] == "warning"

    def test_sales_spike_detected(self, engine):
        # Average is ~2000, last day is 5000 → +150% spike
        data = [
            _toast(2000, "2026-03-10"),
            _toast(2000, "2026-03-11"),
            _toast(2000, "2026-03-12"),
            _toast(2000, "2026-03-13"),
            _toast(5000, "2026-03-14"),
        ]

        alerts = engine.check_sales_anomalies(data, threshold_pct=25)

        spikes = [a for a in alerts if a["type"] == "sales_spike"]
        assert len(spikes) >= 1
        assert spikes[0]["severity"] == "info"

    def test_normal_sales_no_alert(self, engine):
        data = [
            _toast(2000, "2026-03-10"),
            _toast(2100, "2026-03-11"),
            _toast(1950, "2026-03-12"),
            _toast(2050, "2026-03-13"),
        ]

        alerts = engine.check_sales_anomalies(data, threshold_pct=25)
        assert len(alerts) == 0

    def test_insufficient_data(self, engine):
        alerts = engine.check_sales_anomalies([_toast(2000)], threshold_pct=25)
        assert len(alerts) == 0

    def test_zero_sales_skipped(self, engine):
        data = [_toast(0, f"2026-03-{i:02d}") for i in range(10, 15)]
        alerts = engine.check_sales_anomalies(data)
        assert len(alerts) == 0


# ── Missed Orders ────────────────────────────────────────────


class TestMissedOrders:
    def test_order_day_today(self, engine):
        # Mock today to be Tuesday (weekday=1 = Sysco's order_day)
        with patch("bizops.parsers.alerts.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 24)  # Tuesday
            alerts = engine.check_missed_orders()

        reminders = [a for a in alerts if a["type"] == "order_reminder"]
        assert any(a["vendor"] == "Sysco" for a in reminders)

    def test_order_day_yesterday(self, engine):
        # Mock today to be Wednesday (weekday=2, Sysco order_day=1 was yesterday)
        with patch("bizops.parsers.alerts.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 25)  # Wednesday
            alerts = engine.check_missed_orders()

        missed = [a for a in alerts if a["type"] == "order_missed"]
        assert any(a["vendor"] == "Sysco" for a in missed)
        assert missed[0]["severity"] == "warning"

    def test_no_order_day_configured(self, engine):
        # Sunday (weekday=6): Sysco=Tue(1), Om=Thu(3) — neither today nor yesterday
        with patch("bizops.parsers.alerts.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 29)  # Sunday
            alerts = engine.check_missed_orders()

        assert len(alerts) == 0


# ── Combined Cost Ratio ──────────────────────────────────────


class TestCombinedCostRatio:
    def test_prime_cost_critical(self, engine):
        bank = [
            _debit(5000, "food_supplies"),
            _debit(3000, "payroll"),
        ]
        toast = [_toast(10000)]

        alerts = engine.check_combined_cost_ratio(bank, toast, threshold_pct=65)

        assert len(alerts) == 1
        assert alerts[0]["type"] == "prime_cost_high"
        assert alerts[0]["severity"] == "critical"  # 80% > 70%
        assert alerts[0]["prime_pct"] == 80.0

    def test_prime_cost_warning(self, engine):
        bank = [
            _debit(4000, "food_supplies"),
            _debit(2800, "payroll"),
        ]
        toast = [_toast(10000)]

        alerts = engine.check_combined_cost_ratio(bank, toast, threshold_pct=65)

        assert len(alerts) == 1
        assert alerts[0]["severity"] == "warning"  # 68% > 65% but < 70%

    def test_prime_cost_healthy(self, engine):
        bank = [
            _debit(2500, "food_supplies"),
            _debit(2000, "payroll"),
        ]
        toast = [_toast(10000)]

        alerts = engine.check_combined_cost_ratio(bank, toast, threshold_pct=65)
        assert len(alerts) == 0

    def test_no_sales_data(self, engine):
        alerts = engine.check_combined_cost_ratio([_debit(500)], [])
        assert len(alerts) == 0


# ── Large Transactions ───────────────────────────────────────


class TestLargeTransactions:
    def test_large_debit_flagged(self, engine):
        bank = [_debit(7500, "food_supplies", "BIG SUPPLIER")]

        alerts = engine.check_large_transactions(bank, threshold=5000)

        assert len(alerts) == 1
        assert alerts[0]["type"] == "large_transaction"
        assert alerts[0]["amount"] == 7500.0

    def test_under_threshold(self, engine):
        bank = [_debit(3000)]
        alerts = engine.check_large_transactions(bank, threshold=5000)
        assert len(alerts) == 0

    def test_credits_ignored(self, engine):
        bank = [_credit(10000)]
        alerts = engine.check_large_transactions(bank, threshold=5000)
        assert len(alerts) == 0


# ── Scan All ─────────────────────────────────────────────────


class TestScanAll:
    def test_scan_all_returns_sorted(self, engine):
        bank = [
            _debit(7500, "food_supplies", "BIG SUPPLIER"),
            _debit(5000, "food_supplies"),
            _debit(3000, "payroll"),
        ]
        toast = [_toast(10000)]
        invoices = []

        with patch("bizops.parsers.alerts.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 27)  # Friday, no order days
            alerts = engine.scan_all(bank, toast, invoices)

        # Should have at least prime cost + large txn alerts
        assert len(alerts) > 0

        # Check sorted by severity (critical first)
        severities = [a["severity"] for a in alerts]
        severity_order = {"critical": 0, "warning": 1, "info": 2}
        for i in range(len(severities) - 1):
            assert severity_order[severities[i]] <= severity_order[severities[i + 1]]

    def test_scan_all_empty_data(self, engine):
        with patch("bizops.parsers.alerts.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 27)
            alerts = engine.scan_all([], [], [])

        # No data → no alerts (or only order reminders depending on day)
        for a in alerts:
            assert a.get("type") in ("order_reminder", "order_missed")

    def test_scan_all_with_previous_period(self, engine):
        current_bank = [_debit(2000, "food_supplies")]
        prev_bank = [_debit(1000, "food_supplies")]

        with patch("bizops.parsers.alerts.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 27)
            alerts = engine.scan_all(
                current_bank, [], [], prev_bank_txns=prev_bank
            )

        spike_alerts = [a for a in alerts if a["type"] == "spending_spike"]
        assert len(spike_alerts) == 1
