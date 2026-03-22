"""Tests for the LaborEngine — labor cost calculation, cash detection, alerts."""

from __future__ import annotations

import pytest

from bizops.parsers.labor import LaborEngine
from bizops.utils.config import BizOpsConfig, EmployeeConfig, LaborBudget


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def config():
    return BizOpsConfig(
        employees=[
            EmployeeConfig(name="Ahmed Khan", role="cook", pay_type="hourly", pay_rate=15, aliases=["ahmed", "khan"]),
            EmployeeConfig(name="Maria Garcia", role="server", pay_type="contract", pay_rate=12, aliases=["maria"]),
            EmployeeConfig(name="Inactive Person", role="cook", active=False, aliases=["inactive"]),
        ],
        labor_budget=LaborBudget(target_labor_pct=30.0, alert_threshold_pct=35.0),
    )


@pytest.fixture
def engine(config):
    return LaborEngine(config)


def _make_bank_txn(date="2026-03-15", description="ADP PAYROLL", amount=-5000, txn_type="debit", category="payroll"):
    return {
        "date": date,
        "description": description,
        "raw_description": description,
        "amount": amount,
        "abs_amount": abs(amount),
        "type": txn_type,
        "category": category,
    }


def _make_toast(date="2026-03-15", net_sales=2000):
    return {"date": date, "gross_sales": net_sales * 1.1, "net_sales": net_sales, "tax": 0, "tips": 0}


# ── Labor Cost Calculation ────────────────────────────────────


class TestLaborCostCalculation:
    def test_healthy_labor_cost(self, engine):
        bank = [_make_bank_txn(amount=-2500)]
        toast = [_make_toast(net_sales=10000)]
        result = engine.calculate_labor_cost(bank, toast)

        assert result["labor_pct"] == 25.0
        assert result["status"] == "healthy"
        assert result["total_labor"] == 2500.0

    def test_warning_labor_cost(self, engine):
        bank = [_make_bank_txn(amount=-3200)]
        toast = [_make_toast(net_sales=10000)]
        result = engine.calculate_labor_cost(bank, toast)

        assert result["labor_pct"] == 32.0
        assert result["status"] == "warning"

    def test_critical_labor_cost(self, engine):
        bank = [_make_bank_txn(amount=-4000)]
        toast = [_make_toast(net_sales=10000)]
        result = engine.calculate_labor_cost(bank, toast)

        assert result["labor_pct"] == 40.0
        assert result["status"] == "critical"

    def test_zero_sales(self, engine):
        bank = [_make_bank_txn(amount=-1000)]
        result = engine.calculate_labor_cost(bank, [])

        assert result["labor_pct"] == 0.0
        assert result["net_sales"] == 0.0
        assert result["total_labor"] == 1000.0

    def test_no_transactions(self, engine):
        result = engine.calculate_labor_cost([], [_make_toast()])
        assert result["total_labor"] == 0.0
        assert result["labor_pct"] == 0.0

    def test_only_payroll_category_counted(self, engine):
        bank = [
            _make_bank_txn(description="ADP PAYROLL", amount=-3000, category="payroll"),
            _make_bank_txn(description="SYSCO FOOD", amount=-2000, category="food_supplies"),
            _make_bank_txn(description="RENT", amount=-5000, category="rent"),
        ]
        toast = [_make_toast(net_sales=10000)]
        result = engine.calculate_labor_cost(bank, toast)

        assert result["total_labor"] == 3000.0
        assert result["labor_pct"] == 30.0

    def test_breakdown_by_source(self, engine):
        bank = [
            _make_bank_txn(description="ADP PAYROLL", amount=-5000, category="payroll"),
            _make_bank_txn(description="GUSTO PAYROLL", amount=-1000, category="payroll"),
        ]
        toast = [_make_toast(net_sales=20000)]
        result = engine.calculate_labor_cost(bank, toast)

        assert result["breakdown"]["adp"]["total"] == 5000.0
        assert result["breakdown"]["adp"]["count"] == 1
        assert result["breakdown"]["other"]["total"] == 1000.0
        assert result["breakdown"]["other"]["count"] == 1

    def test_credits_excluded(self, engine):
        bank = [
            _make_bank_txn(amount=-3000, category="payroll"),
            _make_bank_txn(amount=1000, txn_type="credit", category="payroll"),
        ]
        toast = [_make_toast(net_sales=10000)]
        result = engine.calculate_labor_cost(bank, toast)

        # Only debits should be counted
        assert result["total_labor"] == 3000.0


# ── Cash Labor Detection ──────────────────────────────────────


class TestCashLaborDetection:
    def test_detects_zelle_to_employee(self, engine):
        bank = [
            _make_bank_txn(description="ZELLE TO AHMED", amount=-500, category="uncategorized"),
        ]
        flagged = engine.detect_cash_labor(bank)

        assert len(flagged) == 1
        assert flagged[0]["match_reason"] == "employee_alias"
        assert flagged[0]["matched_employee"] == "Ahmed Khan"

    def test_detects_venmo_to_employee(self, engine):
        bank = [
            _make_bank_txn(description="VENMO PAYMENT MARIA", amount=-400, category="uncategorized"),
        ]
        flagged = engine.detect_cash_labor(bank)

        assert len(flagged) == 1
        assert flagged[0]["matched_employee"] == "Maria Garcia"

    def test_ignores_zelle_to_vendor(self, engine):
        bank = [
            _make_bank_txn(description="ZELLE TO OM PRODUCE", amount=-800, category="uncategorized"),
        ]
        flagged = engine.detect_cash_labor(bank)

        assert len(flagged) == 0

    def test_detects_round_atm_withdrawal(self, engine):
        bank = [
            _make_bank_txn(description="ATM WITHDRAWAL", amount=-500, category="uncategorized"),
        ]
        flagged = engine.detect_cash_labor(bank)

        assert len(flagged) == 1
        assert flagged[0]["match_reason"] == "round_atm_withdrawal"

    def test_ignores_small_atm(self, engine):
        bank = [
            _make_bank_txn(description="ATM WITHDRAWAL", amount=-60, category="uncategorized"),
        ]
        flagged = engine.detect_cash_labor(bank)

        assert len(flagged) == 0

    def test_ignores_non_round_atm(self, engine):
        bank = [
            _make_bank_txn(description="ATM WITHDRAWAL", amount=-175, category="uncategorized"),
        ]
        flagged = engine.detect_cash_labor(bank)

        assert len(flagged) == 0

    def test_skips_already_payroll(self, engine):
        bank = [
            _make_bank_txn(description="ZELLE TO AHMED", amount=-500, category="payroll"),
        ]
        flagged = engine.detect_cash_labor(bank)

        assert len(flagged) == 0

    def test_skips_credits(self, engine):
        bank = [
            _make_bank_txn(description="ZELLE TO AHMED", amount=500, txn_type="credit", category="uncategorized"),
        ]
        flagged = engine.detect_cash_labor(bank)

        assert len(flagged) == 0

    def test_skips_inactive_employees(self, engine):
        bank = [
            _make_bank_txn(description="ZELLE TO INACTIVE", amount=-300, category="uncategorized"),
        ]
        flagged = engine.detect_cash_labor(bank)

        assert len(flagged) == 0

    def test_no_employees_configured(self):
        config = BizOpsConfig(employees=[])
        engine = LaborEngine(config)
        bank = [
            _make_bank_txn(description="ZELLE TO SOMEONE", amount=-500, category="uncategorized"),
        ]
        flagged = engine.detect_cash_labor(bank)

        assert len(flagged) == 0


# ── Labor Alerts ──────────────────────────────────────────────


class TestLaborAlerts:
    def test_no_alerts_when_healthy(self, engine):
        data = {"labor_pct": 25.0, "detected_cash_labor": []}
        alerts = engine.check_labor_alerts(data)

        assert len(alerts) == 0

    def test_warning_alert(self, engine):
        data = {"labor_pct": 32.0, "detected_cash_labor": []}
        alerts = engine.check_labor_alerts(data)

        assert len(alerts) == 1
        assert alerts[0]["type"] == "warning"

    def test_critical_alert(self, engine):
        data = {"labor_pct": 40.0, "detected_cash_labor": []}
        alerts = engine.check_labor_alerts(data)

        assert len(alerts) == 1
        assert alerts[0]["type"] == "critical"

    def test_cash_labor_info_alert(self, engine):
        data = {"labor_pct": 25.0, "detected_cash_labor": [{"txn": {}, "match_reason": "test"}]}
        alerts = engine.check_labor_alerts(data)

        assert len(alerts) == 1
        assert alerts[0]["type"] == "info"
        assert "1 potential" in alerts[0]["message"]

    def test_multiple_alerts(self, engine):
        data = {"labor_pct": 40.0, "detected_cash_labor": [{"txn": {}}]}
        alerts = engine.check_labor_alerts(data)

        assert len(alerts) == 2  # critical + cash info
