"""Tests for HealthScoreEngine — business health scoring."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from bizops.parsers.health_score import GRADE_THRESHOLDS, SCORE_WEIGHTS, HealthScoreEngine
from bizops.utils.config import BizOpsConfig, VendorConfig

STORAGE = "bizops.utils.storage"


@pytest.fixture
def config():
    return BizOpsConfig(
        vendors=[
            VendorConfig(name="Sysco", email_patterns=["sysco"], category="food_supplies", payment_terms="net30"),
        ],
    )


@pytest.fixture
def engine(config):
    return HealthScoreEngine(config)


def _expenses(food=3000, payroll=2500, rent=1000):
    data = {"expenses_by_category": {}}
    if food:
        data["expenses_by_category"]["food_supplies"] = [{"amount": food, "vendor": "Sysco"}]
    if payroll:
        data["expenses_by_category"]["payroll"] = [{"amount": payroll, "vendor": "ADP"}]
    if rent:
        data["expenses_by_category"]["rent"] = [{"amount": rent, "vendor": "Landlord"}]
    return data


def _toast(net_sales=10000, days=20):
    daily = net_sales / days
    return [{"date": f"2026-03-{d:02d}", "net_sales": daily, "gross_sales": daily * 1.1, "tips": daily * 0.1} for d in range(1, days + 1)]


def _bank(balance=15000):
    return [
        {"date": "2026-03-01", "amount": balance, "type": "credit"},
    ]


# ── Score Calculation ────────────────────────────────────────


class TestScoreCalculation:
    def test_structure(self, engine):
        with patch(f"{STORAGE}.load_expenses", return_value=_expenses()), \
             patch(f"{STORAGE}.load_toast_reports", return_value=_toast()), \
             patch(f"{STORAGE}.load_bank_transactions", return_value=_bank()), \
             patch(f"{STORAGE}.load_invoices", return_value=[]):
            data = engine.calculate_score()

        assert "overall_score" in data
        assert "grade" in data
        assert "components" in data
        assert "suggestions" in data
        assert 0 <= data["overall_score"] <= 100

    def test_all_components_present(self, engine):
        with patch(f"{STORAGE}.load_expenses", return_value=_expenses()), \
             patch(f"{STORAGE}.load_toast_reports", return_value=_toast()), \
             patch(f"{STORAGE}.load_bank_transactions", return_value=_bank()), \
             patch(f"{STORAGE}.load_invoices", return_value=[]):
            data = engine.calculate_score()

        for key in SCORE_WEIGHTS:
            assert key in data["components"]

    def test_weights_sum_to_100(self):
        assert sum(SCORE_WEIGHTS.values()) == 100

    def test_no_data(self, engine):
        with patch(f"{STORAGE}.load_expenses", return_value={}), \
             patch(f"{STORAGE}.load_toast_reports", return_value=[]), \
             patch(f"{STORAGE}.load_bank_transactions", return_value=[]), \
             patch(f"{STORAGE}.load_invoices", return_value=[]):
            data = engine.calculate_score()

        assert data["overall_score"] == 0
        assert data["grade"] == "F"

    def test_healthy_business(self, engine):
        # Low food cost, low labor, good sales, healthy cash
        with patch(f"{STORAGE}.load_expenses", return_value=_expenses(food=2500, payroll=2000, rent=500)), \
             patch(f"{STORAGE}.load_toast_reports", return_value=_toast(net_sales=10000)), \
             patch(f"{STORAGE}.load_bank_transactions", return_value=_bank(balance=25000)), \
             patch(f"{STORAGE}.load_invoices", return_value=[]):
            data = engine.calculate_score()

        assert data["overall_score"] >= 60
        assert data["grade"] in ("A", "B", "C")


# ── Component Scores ─────────────────────────────────────────


class TestFoodCostScore:
    def test_excellent_food_cost(self, engine):
        with patch(f"{STORAGE}.load_expenses", return_value=_expenses(food=2500)), \
             patch(f"{STORAGE}.load_toast_reports", return_value=_toast(net_sales=10000)):
            result = engine._score_food_cost()

        assert result["score"] >= 80  # 25% food cost

    def test_high_food_cost(self, engine):
        with patch(f"{STORAGE}.load_expenses", return_value=_expenses(food=4000)), \
             patch(f"{STORAGE}.load_toast_reports", return_value=_toast(net_sales=10000)):
            result = engine._score_food_cost()

        assert result["score"] < 50  # 40% food cost

    def test_no_data(self, engine):
        with patch(f"{STORAGE}.load_expenses", return_value={}), \
             patch(f"{STORAGE}.load_toast_reports", return_value=[]):
            result = engine._score_food_cost()

        assert result["status"] == "no_data"


class TestLaborScore:
    def test_good_labor(self, engine):
        bank = [{"date": "2026-03-01", "amount": -2500, "type": "debit", "category": "payroll", "description": "ADP"}]
        with patch(f"{STORAGE}.load_bank_transactions", return_value=bank), \
             patch(f"{STORAGE}.load_toast_reports", return_value=_toast(net_sales=10000)):
            result = engine._score_labor_cost()

        assert result["score"] >= 60

    def test_no_data(self, engine):
        with patch(f"{STORAGE}.load_bank_transactions", return_value=[]), \
             patch(f"{STORAGE}.load_toast_reports", return_value=[]):
            result = engine._score_labor_cost()

        assert result["status"] == "no_data"


class TestSalesTrendScore:
    def test_growing_sales(self, engine):
        current = _toast(net_sales=12000, days=20)
        prev = _toast(net_sales=10000, days=20)

        with patch(f"{STORAGE}.load_toast_reports", side_effect=[current, prev]):
            result = engine._score_sales_trend()

        assert result["score"] >= 70
        assert result["status"] == "growing"

    def test_declining_sales(self, engine):
        current = _toast(net_sales=7000, days=20)
        prev = _toast(net_sales=10000, days=20)

        with patch(f"{STORAGE}.load_toast_reports", side_effect=[current, prev]):
            result = engine._score_sales_trend()

        assert result["score"] < 70
        assert result["status"] == "declining"

    def test_no_prior_month(self, engine):
        current = _toast(net_sales=10000, days=20)

        with patch(f"{STORAGE}.load_toast_reports", side_effect=[current, []]):
            result = engine._score_sales_trend()

        assert result["score"] == 70  # neutral

    def test_no_data(self, engine):
        with patch(f"{STORAGE}.load_toast_reports", return_value=[]):
            result = engine._score_sales_trend()

        assert result["status"] == "no_data"


class TestCashScore:
    def test_healthy_balance(self, engine):
        with patch(f"{STORAGE}.load_bank_transactions", return_value=_bank(balance=25000)):
            result = engine._score_cash_position()

        assert result["score"] == 100

    def test_low_balance(self, engine):
        with patch(f"{STORAGE}.load_bank_transactions", return_value=_bank(balance=1000)):
            result = engine._score_cash_position()

        assert result["score"] < 30
        assert result["status"] == "critical"

    def test_no_data(self, engine):
        with patch(f"{STORAGE}.load_bank_transactions", return_value=[]):
            result = engine._score_cash_position()

        assert result["status"] == "no_data"


# ── Grading ──────────────────────────────────────────────────


class TestGrade:
    def test_grade_a(self, engine):
        assert engine._get_grade(95) == "A"

    def test_grade_b(self, engine):
        assert engine._get_grade(85) == "B"

    def test_grade_c(self, engine):
        assert engine._get_grade(75) == "C"

    def test_grade_d(self, engine):
        assert engine._get_grade(65) == "D"

    def test_grade_f(self, engine):
        assert engine._get_grade(50) == "F"

    def test_boundary_a(self, engine):
        assert engine._get_grade(90) == "A"

    def test_boundary_b(self, engine):
        assert engine._get_grade(80) == "B"


# ── Suggestions ──────────────────────────────────────────────


class TestSuggestions:
    def test_suggestions_for_weak_areas(self, engine):
        components = {
            "food_cost": {"score": 40, "value": 40, "status": "critical"},
            "labor_cost": {"score": 85, "value": 24, "status": "healthy"},
            "profit_margin": {"score": 30, "value": 3, "status": "critical"},
            "sales_trend": {"score": 70, "value": 0, "status": "stable"},
            "cash_position": {"score": 80, "value": 15000, "status": "healthy"},
            "payment_discipline": {"score": 90, "value": 90, "status": "excellent"},
        }

        suggestions = engine._generate_suggestions(components)

        assert len(suggestions) > 0
        areas = [s["area"] for s in suggestions]
        # Worst areas should be suggested
        assert "Profit Margin" in areas or "Food Cost" in areas

    def test_no_suggestions_when_all_good(self, engine):
        components = {k: {"score": 90, "value": 0, "status": "healthy"} for k in SCORE_WEIGHTS}
        suggestions = engine._generate_suggestions(components)
        assert len(suggestions) == 0

    def test_no_data_excluded(self, engine):
        components = {k: {"score": 0, "value": 0, "status": "no_data"} for k in SCORE_WEIGHTS}
        suggestions = engine._generate_suggestions(components)
        assert len(suggestions) == 0
