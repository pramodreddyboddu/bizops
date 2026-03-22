"""Tests for the BriefingEngine — daily owner briefing generation."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from bizops.parsers.briefing import BriefingEngine
from bizops.utils.config import (
    BizOpsConfig,
    EmployeeConfig,
    FoodCostBudget,
    LaborBudget,
    ProductItem,
    VendorConfig,
)


# ── Fixtures ──────────────────────────────────────────────────

STORAGE = "bizops.utils.storage"


@pytest.fixture
def config():
    return BizOpsConfig(
        vendors=[
            VendorConfig(
                name="Sysco",
                email_patterns=["sysco.com"],
                category="food_supplies",
                order_day=0,  # Monday
                products=[
                    ProductItem(name="Rice", unit="bag", unit_cost=25.0, par_level=10),
                    ProductItem(name="Oil", unit="case", unit_cost=40.0, par_level=5),
                ],
            ),
        ],
        employees=[
            EmployeeConfig(name="Ahmed", aliases=["ahmed"]),
        ],
        labor_budget=LaborBudget(target_labor_pct=30.0, alert_threshold_pct=35.0),
        food_cost_budget=FoodCostBudget(target_food_cost_pct=30.0, alert_threshold_pct=35.0),
    )


@pytest.fixture
def engine(config):
    return BriefingEngine(config)


def _mock_toast(date, net_sales=2500, gross_sales=2800):
    return [{"date": date, "gross_sales": gross_sales, "net_sales": net_sales, "tax": 200, "tips": 150}]


def _mock_bank_txns():
    return [
        {"date": "2026-03-15", "description": "DEPOSIT", "amount": 3000, "type": "credit", "category": "sales"},
        {"date": "2026-03-14", "description": "ADP PAYROLL", "amount": -2000, "type": "debit", "category": "payroll"},
        {"date": "2026-03-13", "description": "SYSCO", "amount": -500, "type": "debit", "category": "food_supplies"},
    ]


# ── Briefing Generation ──────────────────────────────────────


class TestBriefingGeneration:
    @patch(f"{STORAGE}.load_invoices", return_value=[])
    @patch(f"{STORAGE}.load_food_cost", return_value={})
    @patch(f"{STORAGE}.load_expenses", return_value={})
    @patch(f"{STORAGE}.load_bank_transactions", return_value=[])
    @patch(f"{STORAGE}.load_toast_reports", return_value=[])
    def test_generates_all_sections(self, mock_toast, mock_bank, mock_exp, mock_fc, mock_inv, engine):
        result = engine.generate_briefing("2026-03-20")

        assert result["briefing_date"] == "2026-03-20"
        assert "generated_at" in result
        sections = result["sections"]
        assert "sales" in sections
        assert "cash_position" in sections
        assert "labor" in sections
        assert "food_cost" in sections
        assert "orders_due" in sections
        assert "invoices" in sections
        assert "alerts" in sections

    @patch(f"{STORAGE}.load_invoices", return_value=[])
    @patch(f"{STORAGE}.load_food_cost", return_value={})
    @patch(f"{STORAGE}.load_expenses", return_value={})
    @patch(f"{STORAGE}.load_bank_transactions", return_value=[])
    @patch(f"{STORAGE}.load_toast_reports", return_value=[])
    def test_handles_no_data(self, mock_toast, mock_bank, mock_exp, mock_fc, mock_inv, engine):
        result = engine.generate_briefing("2026-03-20")

        sales = result["sections"]["sales"]
        assert sales["gross_sales"] == 0
        assert sales["net_sales"] == 0
        assert sales["vs_last_week"] is None

        cash = result["sections"]["cash_position"]
        assert cash["estimated_balance"] == 0

    @patch(f"{STORAGE}.load_invoices", return_value=[])
    @patch(f"{STORAGE}.load_food_cost", return_value={})
    @patch(f"{STORAGE}.load_expenses", return_value={})
    @patch(f"{STORAGE}.load_bank_transactions", return_value=[])
    @patch(f"{STORAGE}.load_toast_reports", return_value=[])
    def test_custom_date(self, mock_toast, mock_bank, mock_exp, mock_fc, mock_inv, engine):
        result = engine.generate_briefing("2026-01-15")
        assert result["briefing_date"] == "2026-01-15"


# ── Sales Section ─────────────────────────────────────────────


class TestSalesSection:
    @patch(f"{STORAGE}.load_toast_reports")
    def test_sales_with_data(self, mock_toast, engine):
        def side_effect(config, start, end):
            if start == "2026-03-20":
                return _mock_toast("2026-03-20", net_sales=2500, gross_sales=2800)
            elif start == "2026-03-13":
                return _mock_toast("2026-03-13", net_sales=2000, gross_sales=2200)
            return []

        mock_toast.side_effect = side_effect
        result = engine._build_sales_section("2026-03-20")

        assert result["net_sales"] == 2500
        assert result["gross_sales"] == 2800
        assert result["tips"] == 150
        assert result["vs_last_week"]["pct_change"] == 27.3  # (2800-2200)/2200*100

    @patch(f"{STORAGE}.load_toast_reports", return_value=[])
    def test_sales_no_data(self, mock_toast, engine):
        result = engine._build_sales_section("2026-03-20")

        assert result["net_sales"] == 0
        assert result["vs_last_week"] is None

    @patch(f"{STORAGE}.load_toast_reports")
    def test_sales_no_comparison(self, mock_toast, engine):
        def side_effect(config, start, end):
            if start == "2026-03-20":
                return _mock_toast("2026-03-20")
            return []

        mock_toast.side_effect = side_effect
        result = engine._build_sales_section("2026-03-20")

        assert result["vs_last_week"] is None


# ── Cash Position Section ─────────────────────────────────────


class TestCashPosition:
    @patch(f"{STORAGE}.load_bank_transactions")
    def test_cash_position_calculation(self, mock_bank, engine):
        mock_bank.return_value = _mock_bank_txns()
        result = engine._build_cash_position("2026-03-20")

        assert result["mtd_credits"] == 3000
        assert result["mtd_debits"] == -2500  # -2000 + -500
        assert result["estimated_balance"] == 500  # 3000 - 2500
        assert len(result["recent_deposits"]) == 1
        assert len(result["recent_payments"]) == 2

    @patch(f"{STORAGE}.load_bank_transactions", return_value=[])
    def test_empty_bank(self, mock_bank, engine):
        result = engine._build_cash_position("2026-03-20")
        assert result["estimated_balance"] == 0


# ── Alert Aggregation ─────────────────────────────────────────


class TestAlertAggregation:
    def test_food_cost_critical_alert(self, engine):
        alerts = engine._build_alerts(
            sales={"vs_last_week": None},
            cash={"estimated_balance": 10000},
            labor={"status": "healthy", "labor_pct": 25},
            food_cost={"status": "critical", "food_cost_pct": 40},
        )
        assert any(a["source"] == "food_cost" and a["type"] == "critical" for a in alerts)

    def test_labor_warning_alert(self, engine):
        alerts = engine._build_alerts(
            sales={"vs_last_week": None},
            cash={"estimated_balance": 10000},
            labor={"status": "warning", "labor_pct": 32},
            food_cost={"status": "healthy", "food_cost_pct": 25},
        )
        assert any(a["source"] == "labor" and a["type"] == "warning" for a in alerts)

    def test_low_cash_alert(self, engine):
        alerts = engine._build_alerts(
            sales={"vs_last_week": None},
            cash={"estimated_balance": 1500},
            labor={"status": "healthy", "labor_pct": 25},
            food_cost={"status": "healthy", "food_cost_pct": 25},
        )
        assert any(a["source"] == "cash" for a in alerts)

    def test_sales_drop_alert(self, engine):
        alerts = engine._build_alerts(
            sales={"vs_last_week": {"pct_change": -35}},
            cash={"estimated_balance": 10000},
            labor={"status": "healthy", "labor_pct": 25},
            food_cost={"status": "healthy", "food_cost_pct": 25},
        )
        assert any(a["source"] == "sales" for a in alerts)

    def test_sales_spike_info(self, engine):
        alerts = engine._build_alerts(
            sales={"vs_last_week": {"pct_change": 40}},
            cash={"estimated_balance": 10000},
            labor={"status": "healthy", "labor_pct": 25},
            food_cost={"status": "healthy", "food_cost_pct": 25},
        )
        assert any(a["source"] == "sales" and a["type"] == "info" for a in alerts)

    def test_no_alerts_when_all_healthy(self, engine):
        alerts = engine._build_alerts(
            sales={"vs_last_week": {"pct_change": 5}},
            cash={"estimated_balance": 10000},
            labor={"status": "healthy", "labor_pct": 25},
            food_cost={"status": "healthy", "food_cost_pct": 25},
        )
        assert len(alerts) == 0

    def test_multiple_alerts(self, engine):
        alerts = engine._build_alerts(
            sales={"vs_last_week": {"pct_change": -40}},
            cash={"estimated_balance": 1000},
            labor={"status": "critical", "labor_pct": 40},
            food_cost={"status": "critical", "food_cost_pct": 40},
        )
        assert len(alerts) == 4  # food critical + labor critical + cash warning + sales drop
