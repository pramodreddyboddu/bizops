"""Tests for reconciliation engine."""

from __future__ import annotations

import pytest

from bizops.parsers.reconciliation import ReconciliationEngine
from bizops.utils.config import BizOpsConfig


@pytest.fixture
def config():
    return BizOpsConfig()


@pytest.fixture
def engine(config):
    return ReconciliationEngine(config, tolerance_days=3, tolerance_amount=0.01)


def _make_bank_txn(date, description, amount):
    return {
        "date": date,
        "description": description,
        "amount": amount,
        "abs_amount": abs(amount),
        "type": "credit" if amount > 0 else "debit",
        "category": "uncategorized",
        "reconciled": False,
        "matched_invoice_id": None,
    }


def _make_invoice(date, vendor, amount, message_id="msg_1"):
    return {
        "date": date,
        "vendor": vendor,
        "amount": amount,
        "message_id": message_id,
        "subject": f"Payment to {vendor}",
    }


# ──────────────────────────────────────────────────────────────
#  Reconciliation
# ──────────────────────────────────────────────────────────────


class TestReconciliation:
    def test_exact_match(self, engine):
        bank = [_make_bank_txn("2026-03-15", "ZELLE TO OM PRODUCE", -1500.00)]
        invoices = [_make_invoice("2026-03-15", "Om Produce", 1500.00)]

        result = engine.reconcile(bank, invoices)

        assert result["summary"]["matched_count"] == 1
        assert result["summary"]["match_rate"] == 100.0
        assert len(result["unmatched_bank"]) == 0
        assert len(result["unmatched_invoices"]) == 0
        assert bank[0]["reconciled"] is True

    def test_close_date_match(self, engine):
        bank = [_make_bank_txn("2026-03-17", "PAYMENT", -500.00)]
        invoices = [_make_invoice("2026-03-15", "Vendor", 500.00)]

        result = engine.reconcile(bank, invoices)

        assert result["summary"]["matched_count"] == 1
        assert result["matched"][0]["match_type"] in ("close_date", "exact")

    def test_no_match_date_too_far(self, engine):
        bank = [_make_bank_txn("2026-03-20", "PAYMENT", -500.00)]
        invoices = [_make_invoice("2026-03-10", "Vendor", 500.00)]

        result = engine.reconcile(bank, invoices)

        assert result["summary"]["matched_count"] == 0
        assert len(result["unmatched_bank"]) == 1
        assert len(result["unmatched_invoices"]) == 1

    def test_no_match_amount_differs(self, engine):
        bank = [_make_bank_txn("2026-03-15", "PAYMENT", -500.00)]
        invoices = [_make_invoice("2026-03-15", "Vendor", 600.00)]

        result = engine.reconcile(bank, invoices)

        assert result["summary"]["matched_count"] == 0

    def test_vendor_name_boost(self, engine):
        bank = [_make_bank_txn("2026-03-15", "ZELLE TO OM PRODUCE", -500.00)]
        inv1 = _make_invoice("2026-03-15", "Om Produce", 500.00, "msg_1")
        inv2 = _make_invoice("2026-03-15", "Other Vendor", 500.00, "msg_2")

        result = engine.reconcile(bank, [inv1, inv2])

        assert result["summary"]["matched_count"] == 1
        assert result["matched"][0]["invoice"]["vendor"] == "Om Produce"
        assert result["matched"][0]["match_type"] == "vendor_match"

    def test_multiple_matches(self, engine):
        bank = [
            _make_bank_txn("2026-03-15", "PAYMENT A", -500.00),
            _make_bank_txn("2026-03-16", "PAYMENT B", -300.00),
        ]
        invoices = [
            _make_invoice("2026-03-15", "Vendor A", 500.00, "msg_1"),
            _make_invoice("2026-03-16", "Vendor B", 300.00, "msg_2"),
        ]

        result = engine.reconcile(bank, invoices)

        assert result["summary"]["matched_count"] == 2
        assert result["summary"]["match_rate"] == 100.0

    def test_unmatched_bank_only(self, engine):
        bank = [
            _make_bank_txn("2026-03-15", "MATCHED", -500.00),
            _make_bank_txn("2026-03-16", "CARD FEE", -25.00),
        ]
        invoices = [_make_invoice("2026-03-15", "Vendor", 500.00)]

        result = engine.reconcile(bank, invoices)

        assert result["summary"]["matched_count"] == 1
        assert len(result["unmatched_bank"]) == 1
        assert result["unmatched_bank"][0]["description"] == "CARD FEE"

    def test_credits_are_unmatched(self, engine):
        bank = [_make_bank_txn("2026-03-15", "DEPOSIT", 1200.00)]
        invoices = []

        result = engine.reconcile(bank, invoices)

        assert result["summary"]["matched_count"] == 0
        assert len(result["unmatched_bank"]) == 1

    def test_empty_inputs(self, engine):
        result = engine.reconcile([], [])

        assert result["summary"]["matched_count"] == 0
        assert result["summary"]["match_rate"] == 0

    def test_summary_totals(self, engine):
        bank = [
            _make_bank_txn("2026-03-15", "PAYMENT", -1000.00),
            _make_bank_txn("2026-03-16", "DEPOSIT", 500.00),
        ]

        result = engine.reconcile(bank, [])

        assert result["summary"]["total_bank_debits"] == -1000.00
        assert result["summary"]["total_bank_credits"] == 500.00
        assert result["summary"]["net_bank_flow"] == -500.00

    def test_invoice_consumed_only_once(self, engine):
        """One invoice should not match multiple bank transactions."""
        bank = [
            _make_bank_txn("2026-03-15", "PAYMENT 1", -500.00),
            _make_bank_txn("2026-03-16", "PAYMENT 2", -500.00),
        ]
        invoices = [_make_invoice("2026-03-15", "Vendor", 500.00)]

        result = engine.reconcile(bank, invoices)

        assert result["summary"]["matched_count"] == 1
        assert len(result["unmatched_bank"]) == 1


# ──────────────────────────────────────────────────────────────
#  Cash Flow
# ──────────────────────────────────────────────────────────────


class TestCashFlow:
    def test_basic_cash_flow(self, engine):
        bank = [
            _make_bank_txn("2026-03-15", "RENT", -2500.00),
            _make_bank_txn("2026-03-16", "UTILITIES", -150.00),
            _make_bank_txn("2026-03-17", "DEPOSIT", 3000.00),
        ]
        # Set categories
        bank[0]["category"] = "rent"
        bank[1]["category"] = "utilities"
        bank[2]["category"] = "uncategorized"

        cf = engine.get_cash_flow(bank)

        assert cf["total_expenses"] == -2650.00
        assert cf["total_income"] == 3000.00
        assert cf["net_cash_flow"] == 350.00
        assert "rent" in cf["expenses"]
        assert "utilities" in cf["expenses"]

    def test_empty_cash_flow(self, engine):
        cf = engine.get_cash_flow([])

        assert cf["total_expenses"] == 0
        assert cf["total_income"] == 0
        assert cf["net_cash_flow"] == 0
        assert cf["transaction_count"] == 0

    def test_cash_flow_category_grouping(self, engine):
        bank = [
            _make_bank_txn("2026-03-15", "FOOD 1", -100.00),
            _make_bank_txn("2026-03-16", "FOOD 2", -200.00),
        ]
        bank[0]["category"] = "food_supplies"
        bank[1]["category"] = "food_supplies"

        cf = engine.get_cash_flow(bank)

        assert cf["expenses"]["food_supplies"]["total"] == -300.00
        assert cf["expenses"]["food_supplies"]["count"] == 2


# ──────────────────────────────────────────────────────────────
#  Match scoring
# ──────────────────────────────────────────────────────────────


class TestMatchScoring:
    def test_exact_date_scores_higher(self, engine):
        txn = _make_bank_txn("2026-03-15", "PAYMENT", -500.00)
        inv_same = _make_invoice("2026-03-15", "Vendor", 500.00)
        inv_close = _make_invoice("2026-03-17", "Vendor", 500.00, "msg_2")

        score_same = engine._compute_match_score(txn, inv_same, 0)
        score_close = engine._compute_match_score(txn, inv_close, 2)

        assert score_same > score_close

    def test_zero_amount_no_match(self, engine):
        bank = [_make_bank_txn("2026-03-15", "ZERO", 0)]
        bank[0]["type"] = "debit"
        invoices = [_make_invoice("2026-03-15", "Vendor", 0)]

        result = engine.reconcile(bank, invoices)
        assert result["summary"]["matched_count"] == 0
