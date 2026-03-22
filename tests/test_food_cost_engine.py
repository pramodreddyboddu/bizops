"""Tests for food cost analytics engine."""

from __future__ import annotations

import pytest

from bizops.parsers.food_cost import FoodCostEngine, FOOD_CATEGORIES
from bizops.utils.config import BizOpsConfig, FoodCostBudget


@pytest.fixture
def config():
    return BizOpsConfig(
        food_cost_budget=FoodCostBudget(
            target_food_cost_pct=30.0,
            alert_threshold_pct=35.0,
            category_budgets={"produce": 5000.0},
        )
    )


@pytest.fixture
def engine(config):
    return FoodCostEngine(config)


def _make_expenses_data(food_supplies=0, produce=0, meat=0, beverages=0, net_sales=0):
    expenses_by_category = {
        "food_supplies": [{"amount": food_supplies}] if food_supplies else [],
        "produce": [{"amount": produce}] if produce else [],
        "meat": [{"amount": meat}] if meat else [],
        "beverages": [{"amount": beverages}] if beverages else [],
        "utilities": [{"amount": 500}],
        "rent": [{"amount": 2500}],
    }
    return {
        "expenses_by_category": expenses_by_category,
        "revenue": {"net_sales": net_sales, "gross_sales": net_sales * 1.1},
    }


# ──────────────────────────────────────────────────────────────
#  Food cost calculation
# ──────────────────────────────────────────────────────────────


class TestFoodCostCalculation:
    def test_healthy_food_cost(self, engine):
        data = _make_expenses_data(
            food_supplies=1000, produce=1500, meat=800, beverages=200, net_sales=15000
        )
        result = engine.calculate_food_cost(data)

        assert result["food_cost_total"] == 3500.0
        assert result["net_sales"] == 15000.0
        assert result["food_cost_pct"] == 23.3
        assert result["status"] == "healthy"

    def test_warning_food_cost(self, engine):
        data = _make_expenses_data(
            food_supplies=2000, produce=2000, meat=1500, beverages=500, net_sales=18000
        )
        result = engine.calculate_food_cost(data)

        # 6000/18000 = 33.3%
        assert result["food_cost_pct"] == 33.3
        assert result["status"] == "warning"

    def test_critical_food_cost(self, engine):
        data = _make_expenses_data(
            food_supplies=3000, produce=3000, meat=2000, beverages=1000, net_sales=20000
        )
        result = engine.calculate_food_cost(data)

        # 9000/20000 = 45%
        assert result["food_cost_pct"] == 45.0
        assert result["status"] == "critical"

    def test_zero_sales(self, engine):
        data = _make_expenses_data(food_supplies=1000, net_sales=0)
        result = engine.calculate_food_cost(data)

        assert result["food_cost_pct"] == 0.0
        assert result["status"] == "healthy"

    def test_zero_food_expenses(self, engine):
        data = _make_expenses_data(net_sales=10000)
        result = engine.calculate_food_cost(data)

        assert result["food_cost_total"] == 0.0
        assert result["food_cost_pct"] == 0.0

    def test_category_breakdown(self, engine):
        data = _make_expenses_data(
            food_supplies=1000, produce=2000, meat=500, beverages=300, net_sales=10000
        )
        result = engine.calculate_food_cost(data)

        by_cat = result["by_category"]
        assert by_cat["produce"]["total"] == 2000.0
        assert by_cat["produce"]["pct"] == 20.0
        assert by_cat["food_supplies"]["total"] == 1000.0
        assert by_cat["meat"]["total"] == 500.0
        assert by_cat["beverages"]["total"] == 300.0

    def test_non_food_categories_excluded(self, engine):
        data = _make_expenses_data(food_supplies=1000, net_sales=10000)
        result = engine.calculate_food_cost(data)

        # Utilities and rent should NOT be in food cost
        assert result["food_cost_total"] == 1000.0  # Only food_supplies
        assert "utilities" not in result["by_category"]

    def test_uses_toast_data_fallback(self, engine):
        data = {"expenses_by_category": {"food_supplies": [{"amount": 1000}]}, "revenue": {}}
        toast = [{"net_sales": 5000}, {"net_sales": 5000}]

        result = engine.calculate_food_cost(data, toast)
        assert result["net_sales"] == 10000.0

    def test_target_and_threshold_in_result(self, engine):
        data = _make_expenses_data(net_sales=10000)
        result = engine.calculate_food_cost(data)

        assert result["target_pct"] == 30.0
        assert result["alert_threshold_pct"] == 35.0


# ──────────────────────────────────────────────────────────────
#  Alerts
# ──────────────────────────────────────────────────────────────


class TestAlerts:
    def test_no_alerts_when_healthy(self, engine):
        fc_data = {
            "food_cost_pct": 25.0,
            "by_category": {"produce": {"total": 2000}},
        }
        alerts = engine.check_alerts(fc_data)
        assert len(alerts) == 0

    def test_warning_alert(self, engine):
        fc_data = {
            "food_cost_pct": 32.0,
            "by_category": {},
        }
        alerts = engine.check_alerts(fc_data)
        assert len(alerts) == 1
        assert alerts[0]["type"] == "warning"

    def test_critical_alert(self, engine):
        fc_data = {
            "food_cost_pct": 40.0,
            "by_category": {},
        }
        alerts = engine.check_alerts(fc_data)
        assert len(alerts) == 1
        assert alerts[0]["type"] == "critical"

    def test_category_budget_alert(self, engine):
        fc_data = {
            "food_cost_pct": 25.0,
            "by_category": {"produce": {"total": 6000}},
        }
        alerts = engine.check_alerts(fc_data)
        assert len(alerts) == 1
        assert alerts[0]["type"] == "over_budget"
        assert alerts[0]["category"] == "produce"
        assert alerts[0]["overage"] == 1000.0

    def test_multiple_alerts(self, engine):
        fc_data = {
            "food_cost_pct": 40.0,
            "by_category": {"produce": {"total": 6000}},
        }
        alerts = engine.check_alerts(fc_data)
        assert len(alerts) == 2  # critical + over_budget


# ──────────────────────────────────────────────────────────────
#  Sales velocity
# ──────────────────────────────────────────────────────────────


class TestSalesVelocity:
    def test_flat_sales(self, engine):
        reports = [{"net_sales": 1000, "date": f"2026-03-{i:02d}"} for i in range(1, 15)]
        v = engine.calculate_sales_velocity(reports)

        assert v["avg_daily_sales"] == 1000.0
        assert v["velocity_ratio"] == 1.0
        assert v["trend_direction"] == "flat"
        assert v["days_analyzed"] == 14

    def test_increasing_sales(self, engine):
        reports = [{"net_sales": 500, "date": f"2026-03-{i:02d}"} for i in range(1, 8)]
        reports += [{"net_sales": 1500, "date": f"2026-03-{i:02d}"} for i in range(8, 15)]
        v = engine.calculate_sales_velocity(reports, recent_days=7)

        assert v["trend_direction"] == "up"
        assert v["velocity_ratio"] > 1.0

    def test_decreasing_sales(self, engine):
        reports = [{"net_sales": 1500, "date": f"2026-03-{i:02d}"} for i in range(1, 8)]
        reports += [{"net_sales": 500, "date": f"2026-03-{i:02d}"} for i in range(8, 15)]
        v = engine.calculate_sales_velocity(reports, recent_days=7)

        assert v["trend_direction"] == "down"
        assert v["velocity_ratio"] < 1.0

    def test_empty_reports(self, engine):
        v = engine.calculate_sales_velocity([])

        assert v["avg_daily_sales"] == 0.0
        assert v["velocity_ratio"] == 1.0
        assert v["days_analyzed"] == 0

    def test_weekly_sales_calculated(self, engine):
        reports = [{"net_sales": 1000, "date": f"2026-03-{i:02d}"} for i in range(1, 8)]
        v = engine.calculate_sales_velocity(reports)

        assert v["avg_weekly_sales"] == 7000.0

    def test_few_reports(self, engine):
        reports = [{"net_sales": 2000, "date": "2026-03-01"}]
        v = engine.calculate_sales_velocity(reports, recent_days=7)

        assert v["avg_daily_sales"] == 2000.0
        assert v["days_analyzed"] == 1


# ──────────────────────────────────────────────────────────────
#  Food categories constant
# ──────────────────────────────────────────────────────────────


class TestFoodCategories:
    def test_food_categories_set(self):
        assert "food_supplies" in FOOD_CATEGORIES
        assert "produce" in FOOD_CATEGORIES
        assert "meat" in FOOD_CATEGORIES
        assert "beverages" in FOOD_CATEGORIES
        assert "utilities" not in FOOD_CATEGORIES
        assert "rent" not in FOOD_CATEGORIES
