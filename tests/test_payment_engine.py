"""Tests for the PaymentEngine — vendor payment tracking and cash forecasting."""

from __future__ import annotations

import pytest

from bizops.parsers.payments import TERMS_DAYS, PaymentEngine
from bizops.utils.config import BizOpsConfig, VendorConfig


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def config():
    return BizOpsConfig(
        vendors=[
            VendorConfig(name="Sysco", email_patterns=["sysco"], category="food_supplies", payment_terms="net30", aliases=["sysco foods"]),
            VendorConfig(name="Om Produce", email_patterns=["om"], category="produce", payment_terms="cod", aliases=["om"]),
            VendorConfig(name="Yaman Halal", email_patterns=["yaman"], category="meat", payment_terms="net15", aliases=["yaman"]),
        ],
    )


@pytest.fixture
def engine(config):
    return PaymentEngine(config)


def _inv(vendor="Sysco", amount=500, date="2026-03-10", txn_type="payment"):
    return {
        "vendor": vendor,
        "amount": amount,
        "date": date,
        "transaction_type": txn_type,
        "subject": f"Invoice from {vendor}",
        "reconciled": False,
    }


def _bank(desc="SYSCO FOODS", amount=-500, date="2026-03-12", category="food_supplies"):
    return {
        "date": date,
        "description": desc,
        "raw_description": desc,
        "amount": amount,
        "abs_amount": abs(amount),
        "type": "debit",
        "category": category,
    }


# ── Payment Status ────────────────────────────────────────────


class TestPaymentStatus:
    def test_paid_invoice_matched(self, engine):
        invoices = [_inv(vendor="Sysco", amount=500, date="2026-03-10")]
        bank = [_bank(desc="SYSCO FOODS", amount=-500, date="2026-03-12")]

        result = engine.get_payment_status(invoices, bank, "2026-03-20")

        vendors = result["vendors"]
        assert len(vendors) == 1
        assert vendors[0]["total_paid"] == 500.0
        assert vendors[0]["balance_due"] == 0.0

    def test_unpaid_invoice(self, engine):
        invoices = [_inv(vendor="Sysco", amount=500, date="2026-03-10")]
        bank = []  # no bank payments

        result = engine.get_payment_status(invoices, bank, "2026-03-20")

        vendors = result["vendors"]
        assert vendors[0]["unpaid_count"] == 1  # not paid, but not overdue yet (net30)
        assert vendors[0]["overdue_count"] == 0  # due Apr 9, not overdue on Mar 20
        assert vendors[0]["balance_due"] == 500.0

    def test_overdue_invoice(self, engine):
        # Yaman Halal has net15 terms. Invoice from Mar 1 is due Mar 16.
        invoices = [_inv(vendor="Yaman Halal", amount=300, date="2026-03-01")]
        bank = []

        result = engine.get_payment_status(invoices, bank, "2026-03-20")

        vendors = result["vendors"]
        yaman = next(v for v in vendors if v["vendor"] == "Yaman Halal")
        assert yaman["overdue_count"] == 1

    def test_cod_overdue_immediately(self, engine):
        # Om Produce is COD. Invoice from yesterday is already overdue today.
        invoices = [_inv(vendor="Om Produce", amount=200, date="2026-03-19")]
        bank = []

        result = engine.get_payment_status(invoices, bank, "2026-03-20")

        vendors = result["vendors"]
        om = next(v for v in vendors if v["vendor"] == "Om Produce")
        assert om["overdue_count"] == 1

    def test_multiple_vendors(self, engine):
        invoices = [
            _inv(vendor="Sysco", amount=500, date="2026-03-10"),
            _inv(vendor="Om Produce", amount=200, date="2026-03-15"),
            _inv(vendor="Yaman Halal", amount=300, date="2026-03-12"),
        ]
        bank = [_bank(desc="SYSCO FOODS", amount=-500, date="2026-03-12")]

        result = engine.get_payment_status(invoices, bank, "2026-03-20")

        assert result["summary"]["total_vendors"] == 3
        assert result["summary"]["total_invoiced"] == 1000.0
        assert result["summary"]["total_paid"] == 500.0
        assert result["summary"]["total_outstanding"] == 500.0

    def test_non_payment_invoices_skipped(self, engine):
        invoices = [
            _inv(vendor="Sysco", amount=500, txn_type="payment"),
            _inv(vendor="Sysco", amount=100, txn_type="order"),  # informational, skip
        ]
        bank = []

        result = engine.get_payment_status(invoices, bank, "2026-03-20")

        assert result["summary"]["total_invoiced"] == 500.0

    def test_summary_totals(self, engine):
        invoices = [
            _inv(vendor="Sysco", amount=500, date="2026-03-10"),
            _inv(vendor="Yaman Halal", amount=300, date="2026-03-01"),
        ]
        bank = [_bank(desc="SYSCO FOODS", amount=-500, date="2026-03-12")]

        result = engine.get_payment_status(invoices, bank, "2026-03-20")
        summary = result["summary"]

        assert summary["total_invoiced"] == 800.0
        assert summary["total_paid"] == 500.0
        assert summary["total_outstanding"] == 300.0
        assert summary["overdue_vendor_count"] == 1  # Yaman overdue

    def test_empty_inputs(self, engine):
        result = engine.get_payment_status([], [])
        assert result["summary"]["total_vendors"] == 0
        assert result["summary"]["total_invoiced"] == 0

    def test_amount_tolerance(self, engine):
        # Bank amount slightly different (within 2% tolerance)
        invoices = [_inv(vendor="Sysco", amount=500, date="2026-03-10")]
        bank = [_bank(desc="SYSCO FOODS", amount=-505, date="2026-03-10")]

        result = engine.get_payment_status(invoices, bank, "2026-03-20")
        assert result["vendors"][0]["total_paid"] == 500.0


# ── Payment Calendar ──────────────────────────────────────────


class TestPaymentCalendar:
    def test_upcoming_payments(self, engine):
        # Yaman net15: inv Mar 10 → due Mar 25
        invoices = [_inv(vendor="Yaman Halal", amount=300, date="2026-03-10")]
        bank = []

        from unittest.mock import patch
        with patch("bizops.parsers.payments.datetime") as mock_dt:
            mock_dt.now.return_value = __import__("datetime").datetime(2026, 3, 20)
            mock_dt.strptime = __import__("datetime").datetime.strptime
            upcoming = engine.get_payment_calendar(invoices, bank, days_ahead=14)

        assert len(upcoming) == 1
        assert upcoming[0]["vendor"] == "Yaman Halal"
        assert upcoming[0]["due_date"] == "2026-03-25"
        assert upcoming[0]["is_overdue"] is False

    def test_overdue_in_calendar(self, engine):
        # Om COD: inv Mar 15 → due Mar 15, checking on Mar 20
        invoices = [_inv(vendor="Om Produce", amount=200, date="2026-03-15")]
        bank = []

        from unittest.mock import patch
        with patch("bizops.parsers.payments.datetime") as mock_dt:
            mock_dt.now.return_value = __import__("datetime").datetime(2026, 3, 20)
            mock_dt.strptime = __import__("datetime").datetime.strptime
            upcoming = engine.get_payment_calendar(invoices, bank, days_ahead=14)

        assert len(upcoming) == 1
        assert upcoming[0]["is_overdue"] is True

    def test_paid_not_in_calendar(self, engine):
        invoices = [_inv(vendor="Sysco", amount=500, date="2026-03-10")]
        bank = [_bank(desc="SYSCO FOODS", amount=-500, date="2026-03-12")]

        upcoming = engine.get_payment_calendar(invoices, bank, days_ahead=30)
        assert len(upcoming) == 0

    def test_sorted_by_date(self, engine):
        invoices = [
            _inv(vendor="Yaman Halal", amount=300, date="2026-03-15"),
            _inv(vendor="Om Produce", amount=200, date="2026-03-10"),
        ]
        bank = []

        from unittest.mock import patch
        with patch("bizops.parsers.payments.datetime") as mock_dt:
            mock_dt.now.return_value = __import__("datetime").datetime(2026, 3, 20)
            mock_dt.strptime = __import__("datetime").datetime.strptime
            upcoming = engine.get_payment_calendar(invoices, bank, days_ahead=30)

        # Om (COD, due Mar 10) should be first (overdue)
        assert upcoming[0]["vendor"] == "Om Produce"


# ── Cash Forecast ─────────────────────────────────────────────


class TestCashForecast:
    def test_forecast_structure(self, engine):
        invoices = [_inv(vendor="Om Produce", amount=200, date="2026-03-15")]
        bank = [
            {"date": "2026-03-15", "description": "DEPOSIT", "amount": 5000, "type": "credit"},
            {"date": "2026-03-14", "description": "RENT", "amount": -2000, "type": "debit", "category": "rent"},
        ]
        toast = [{"date": "2026-03-15", "net_sales": 2000}]

        forecast = engine.get_cash_forecast(invoices, bank, toast, days_ahead=7)

        assert "current_balance" in forecast
        assert "upcoming_payments" in forecast
        assert "projected_income" in forecast
        assert "projected_end_balance" in forecast
        assert "daily_forecast" in forecast
        assert len(forecast["daily_forecast"]) == 7

    def test_current_balance_from_bank(self, engine):
        bank = [
            {"date": "2026-03-15", "amount": 10000, "type": "credit"},
            {"date": "2026-03-14", "amount": -3000, "type": "debit"},
        ]

        forecast = engine.get_cash_forecast([], bank, [], days_ahead=7)
        assert forecast["current_balance"] == 7000.0

    def test_avg_daily_income(self, engine):
        toast = [
            {"date": "2026-03-14", "net_sales": 2000},
            {"date": "2026-03-15", "net_sales": 3000},
        ]

        forecast = engine.get_cash_forecast([], [], toast, days_ahead=7)
        assert forecast["avg_daily_income"] == 2500.0

    def test_no_data(self, engine):
        forecast = engine.get_cash_forecast([], [], [], days_ahead=7)
        assert forecast["current_balance"] == 0
        assert forecast["avg_daily_income"] == 0
        assert forecast["projected_end_balance"] == 0

    def test_danger_days_flagged(self, engine):
        # Start with $1000 balance, no income, $500 due tomorrow
        bank = [{"date": "2026-03-20", "amount": 1000, "type": "credit"}]
        invoices = [_inv(vendor="Om Produce", amount=500, date="2026-03-15")]

        from unittest.mock import patch
        with patch("bizops.parsers.payments.datetime") as mock_dt:
            mock_dt.now.return_value = __import__("datetime").datetime(2026, 3, 20)
            mock_dt.strptime = __import__("datetime").datetime.strptime
            forecast = engine.get_cash_forecast(invoices, bank, [], days_ahead=7)

        # Balance starts at $1000, payment of $500 due (already overdue for COD)
        # With no income, should have danger days
        assert len(forecast["danger_days"]) > 0


# ── Vendor History ────────────────────────────────────────────


class TestVendorHistory:
    def test_basic_history(self, engine):
        invoices = [
            _inv(vendor="Sysco", amount=500, date="2026-03-10"),
            _inv(vendor="Sysco", amount=300, date="2026-03-15"),
        ]
        bank = [_bank(desc="SYSCO FOODS", amount=-500, date="2026-03-12")]

        history = engine.get_vendor_payment_history("Sysco", invoices, bank)

        assert history["vendor"] == "Sysco"
        assert history["payment_terms"] == "net30"
        assert history["total_invoiced"] == 800.0
        assert history["total_paid"] == 500.0
        assert history["balance_due"] == 300.0
        assert history["paid_count"] == 1
        assert history["unpaid_count"] == 1

    def test_vendor_not_found(self, engine):
        history = engine.get_vendor_payment_history("Unknown Vendor", [], [])
        assert "message" in history

    def test_avg_days_to_pay(self, engine):
        invoices = [_inv(vendor="Sysco", amount=500, date="2026-03-10")]
        bank = [_bank(desc="SYSCO FOODS", amount=-500, date="2026-03-12")]

        history = engine.get_vendor_payment_history("Sysco", invoices, bank)
        assert history["avg_days_to_pay"] == 2.0


# ── Terms ─────────────────────────────────────────────────────


class TestTerms:
    def test_terms_days_mapping(self):
        assert TERMS_DAYS["cod"] == 0
        assert TERMS_DAYS["net15"] == 15
        assert TERMS_DAYS["net30"] == 30

    def test_vendor_terms_lookup(self, engine):
        assert engine._get_terms("Sysco") == "net30"
        assert engine._get_terms("Om Produce") == "cod"
        assert engine._get_terms("Unknown") == "cod"  # default

    def test_alias_terms_lookup(self, engine):
        assert engine._get_terms("sysco foods") == "net30"
