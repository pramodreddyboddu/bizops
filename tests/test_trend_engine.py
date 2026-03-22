"""Tests for the TrendEngine — P&L trends, benchmarks, and revenue forecasting."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from bizops.parsers.trends import INDUSTRY_BENCHMARKS, TrendEngine
from bizops.utils.config import BizOpsConfig, VendorConfig

STORAGE = "bizops.utils.storage"


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def config():
    return BizOpsConfig(
        vendors=[
            VendorConfig(name="Sysco", email_patterns=["sysco"], category="food_supplies"),
        ],
    )


@pytest.fixture
def engine(config):
    return TrendEngine(config)


def _expenses(food=3000, payroll=2500, rent=1500):
    """Build a mock expenses dict matching ExpenseEngine.categorize_all() output."""
    data = {"expenses_by_category": {}}
    if food:
        data["expenses_by_category"]["food_supplies"] = [
            {"vendor": "Sysco", "amount": food, "date": "2026-03-10"},
        ]
    if payroll:
        data["expenses_by_category"]["payroll"] = [
            {"vendor": "ADP", "amount": payroll, "date": "2026-03-15"},
        ]
    if rent:
        data["expenses_by_category"]["rent"] = [
            {"vendor": "Landlord", "amount": rent, "date": "2026-03-01"},
        ]
    return data


def _toast(net_sales=10000, days=20, date_prefix="2026-03"):
    """Build mock Toast reports."""
    daily = net_sales / days if days else 0
    return [
        {"date": f"{date_prefix}-{d:02d}", "net_sales": daily, "gross_sales": daily * 1.1, "tips": daily * 0.15}
        for d in range(1, days + 1)
    ]


# ── P&L Trend ────────────────────────────────────────────────


class TestPLTrend:
    def test_structure(self, engine):
        with patch(f"{STORAGE}.load_expenses", return_value=_expenses()), \
             patch(f"{STORAGE}.load_toast_reports", return_value=_toast()):
            data = engine.get_pl_trend(months=3)

        assert "snapshots" in data
        assert "averages" in data
        assert data["months_analyzed"] == 3
        assert len(data["snapshots"]) == 3

    def test_snapshot_fields(self, engine):
        with patch(f"{STORAGE}.load_expenses", return_value=_expenses()), \
             patch(f"{STORAGE}.load_toast_reports", return_value=_toast()):
            data = engine.get_pl_trend(months=1)

        snap = data["snapshots"][0]
        assert "month" in snap
        assert "net_sales" in snap
        assert "total_expenses" in snap
        assert "net_profit" in snap
        assert "net_profit_pct" in snap
        assert "expense_breakdown" in snap

    def test_profit_calculation(self, engine):
        with patch(f"{STORAGE}.load_expenses", return_value=_expenses(food=3000, payroll=2500, rent=1500)), \
             patch(f"{STORAGE}.load_toast_reports", return_value=_toast(net_sales=10000)):
            data = engine.get_pl_trend(months=1)

        snap = data["snapshots"][0]
        assert snap["net_sales"] == 10000.0
        assert snap["total_expenses"] == 7000.0
        assert snap["net_profit"] == 3000.0
        assert snap["net_profit_pct"] == 30.0

    def test_no_data(self, engine):
        with patch(f"{STORAGE}.load_expenses", return_value={}), \
             patch(f"{STORAGE}.load_toast_reports", return_value=[]):
            data = engine.get_pl_trend(months=3)

        assert data["months_with_data"] == 0
        assert data["averages"]["avg_monthly_revenue"] == 0

    def test_trends_added(self, engine):
        # Return different data for different months
        call_count = {"n": 0}
        def mock_expenses(config, ym):
            call_count["n"] += 1
            if call_count["n"] <= 1:
                return _expenses(food=2000, payroll=2000, rent=1000)
            return _expenses(food=4000, payroll=3000, rent=1500)

        toast_count = {"n": 0}
        def mock_toast(config, start, end):
            toast_count["n"] += 1
            if toast_count["n"] <= 1:
                return _toast(net_sales=8000)
            return _toast(net_sales=12000)

        with patch(f"{STORAGE}.load_expenses", side_effect=mock_expenses), \
             patch(f"{STORAGE}.load_toast_reports", side_effect=mock_toast):
            data = engine.get_pl_trend(months=2)

        snaps = data["snapshots"]
        # Second month should have trend info
        assert snaps[1].get("revenue_trend") in ("up", "down", "flat")
        assert snaps[1].get("expense_trend") in ("up", "down", "flat")

    def test_averages(self, engine):
        with patch(f"{STORAGE}.load_expenses", return_value=_expenses()), \
             patch(f"{STORAGE}.load_toast_reports", return_value=_toast()):
            data = engine.get_pl_trend(months=3)

        avgs = data["averages"]
        assert avgs["avg_monthly_revenue"] > 0
        assert avgs["avg_monthly_expenses"] > 0


# ── Category Trend ───────────────────────────────────────────


class TestCategoryTrend:
    def test_category_tracking(self, engine):
        with patch(f"{STORAGE}.load_expenses", return_value=_expenses(food=3000)), \
             patch(f"{STORAGE}.load_toast_reports", return_value=_toast(net_sales=10000)):
            data = engine.get_category_trend("food_supplies", months=3)

        assert data["category"] == "food_supplies"
        assert len(data["snapshots"]) == 3
        for snap in data["snapshots"]:
            assert "total" in snap
            assert "pct_of_revenue" in snap
            assert "trend" in snap

    def test_nonexistent_category(self, engine):
        with patch(f"{STORAGE}.load_expenses", return_value=_expenses()), \
             patch(f"{STORAGE}.load_toast_reports", return_value=_toast()):
            data = engine.get_category_trend("nonexistent", months=1)

        assert data["snapshots"][0]["total"] == 0

    def test_trend_direction(self, engine):
        call_count = {"n": 0}
        def mock_expenses(config, ym):
            call_count["n"] += 1
            if call_count["n"] <= 1:
                return _expenses(food=1000)
            return _expenses(food=2000)

        with patch(f"{STORAGE}.load_expenses", side_effect=mock_expenses), \
             patch(f"{STORAGE}.load_toast_reports", return_value=_toast()):
            data = engine.get_category_trend("food_supplies", months=2)

        assert data["snapshots"][1]["trend"] == "up"


# ── Revenue Forecast ─────────────────────────────────────────


class TestRevenueForecast:
    def test_forecast_structure(self, engine):
        reports = _toast(net_sales=60000, days=30)
        with patch(f"{STORAGE}.load_toast_reports", return_value=reports):
            data = engine.get_revenue_forecast(forecast_days=30)

        assert "projected_daily" in data
        assert "projected_weekly" in data
        assert "projected_total" in data
        assert "confidence" in data
        assert "day_of_week_pattern" in data

    def test_no_data(self, engine):
        with patch(f"{STORAGE}.load_toast_reports", return_value=[]):
            data = engine.get_revenue_forecast(forecast_days=30)

        assert data["projected_daily"] == 0
        assert data["confidence"] == "no_data"

    def test_high_confidence_with_data(self, engine):
        reports = _toast(net_sales=60000, days=60)
        with patch(f"{STORAGE}.load_toast_reports", return_value=reports):
            data = engine.get_revenue_forecast(forecast_days=30)

        assert data["confidence"] == "high"
        assert data["projected_daily"] > 0

    def test_medium_confidence(self, engine):
        reports = _toast(net_sales=14000, days=14)
        with patch(f"{STORAGE}.load_toast_reports", return_value=reports):
            data = engine.get_revenue_forecast(forecast_days=30)

        assert data["confidence"] == "medium"

    def test_low_confidence(self, engine):
        reports = _toast(net_sales=3000, days=3)
        with patch(f"{STORAGE}.load_toast_reports", return_value=reports):
            data = engine.get_revenue_forecast(forecast_days=30)

        assert data["confidence"] == "low"

    def test_day_of_week_pattern(self, engine):
        reports = _toast(net_sales=14000, days=14)
        with patch(f"{STORAGE}.load_toast_reports", return_value=reports):
            data = engine.get_revenue_forecast(forecast_days=30)

        dow = data["day_of_week_pattern"]
        assert "Monday" in dow
        assert "Sunday" in dow

    def test_projected_total(self, engine):
        reports = _toast(net_sales=30000, days=30)
        with patch(f"{STORAGE}.load_toast_reports", return_value=reports):
            data = engine.get_revenue_forecast(forecast_days=30)

        # Should be approximately 30000 (same as historical)
        assert data["projected_total"] > 0
        assert data["projected_weekly"] == data["projected_daily"] * 7


# ── Benchmarks ───────────────────────────────────────────────


class TestBenchmarks:
    def test_benchmark_structure(self, engine):
        with patch(f"{STORAGE}.load_toast_reports", return_value=_toast(net_sales=10000)), \
             patch(f"{STORAGE}.load_expenses", return_value=_expenses()), \
             patch(f"{STORAGE}.load_bank_transactions", return_value=[]):
            data = engine.get_benchmarks()

        assert "metrics" in data
        assert "overall_grade" in data
        assert "net_sales" in data

    def test_food_cost_graded(self, engine):
        with patch(f"{STORAGE}.load_toast_reports", return_value=_toast(net_sales=10000)), \
             patch(f"{STORAGE}.load_expenses", return_value=_expenses(food=2500)), \
             patch(f"{STORAGE}.load_bank_transactions", return_value=[]):
            data = engine.get_benchmarks()

        food_metric = next((m for m in data["metrics"] if "Food" in m["name"]), None)
        assert food_metric is not None
        assert food_metric["grade"] in ("A", "B", "C", "D")

    def test_excellent_grades(self, engine):
        # Low food cost (20%), should be grade A
        with patch(f"{STORAGE}.load_toast_reports", return_value=_toast(net_sales=10000)), \
             patch(f"{STORAGE}.load_expenses", return_value=_expenses(food=2000, payroll=0, rent=0)), \
             patch(f"{STORAGE}.load_bank_transactions", return_value=[]):
            data = engine.get_benchmarks()

        food_metric = next((m for m in data["metrics"] if "Food" in m["name"]), None)
        assert food_metric is not None
        assert food_metric["grade"] == "A"
        assert food_metric["value"] == 20.0

    def test_no_data(self, engine):
        with patch(f"{STORAGE}.load_toast_reports", return_value=[]), \
             patch(f"{STORAGE}.load_expenses", return_value={}), \
             patch(f"{STORAGE}.load_bank_transactions", return_value=[]):
            data = engine.get_benchmarks()

        assert data["net_sales"] == 0
        assert len(data["metrics"]) == 0


# ── Grade Helper ─────────────────────────────────────────────


class TestGradeMetric:
    def test_lower_is_better_excellent(self, engine):
        result = engine._grade_metric("Test", 25.0, INDUSTRY_BENCHMARKS["food_cost_pct"], lower_is_better=True)
        assert result["grade"] == "A"

    def test_lower_is_better_good(self, engine):
        result = engine._grade_metric("Test", 30.0, INDUSTRY_BENCHMARKS["food_cost_pct"], lower_is_better=True)
        assert result["grade"] == "B"

    def test_lower_is_better_needs_attention(self, engine):
        result = engine._grade_metric("Test", 35.0, INDUSTRY_BENCHMARKS["food_cost_pct"], lower_is_better=True)
        assert result["grade"] == "C"

    def test_lower_is_better_critical(self, engine):
        result = engine._grade_metric("Test", 45.0, INDUSTRY_BENCHMARKS["food_cost_pct"], lower_is_better=True)
        assert result["grade"] == "D"

    def test_higher_is_better_excellent(self, engine):
        result = engine._grade_metric("Test", 12.0, INDUSTRY_BENCHMARKS["net_profit_pct"], lower_is_better=False)
        assert result["grade"] == "A"

    def test_higher_is_better_critical(self, engine):
        result = engine._grade_metric("Test", 1.0, INDUSTRY_BENCHMARKS["net_profit_pct"], lower_is_better=False)
        assert result["grade"] == "D"


# ── Internal Helpers ─────────────────────────────────────────


class TestHelpers:
    def test_trend_dir_up(self, engine):
        assert engine._trend_dir(100, 120) == "up"

    def test_trend_dir_down(self, engine):
        assert engine._trend_dir(100, 80) == "down"

    def test_trend_dir_flat(self, engine):
        assert engine._trend_dir(100, 102) == "flat"

    def test_trend_dir_zero_prev(self, engine):
        assert engine._trend_dir(0, 100) == "flat"

    def test_get_category_total(self, engine):
        expenses = _expenses(food=3000)
        assert engine._get_category_total(expenses, "food_supplies") == 3000

    def test_get_category_total_empty(self, engine):
        assert engine._get_category_total({}, "food_supplies") == 0
        assert engine._get_category_total(None, "food_supplies") == 0
