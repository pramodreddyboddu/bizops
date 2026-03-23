"""Tests for BudgetEngine — budget tracking, alerts, recommendations."""

from __future__ import annotations

import pytest

from bizops.parsers.budget import BudgetEngine
from bizops.utils.config import BizOpsConfig, BudgetConfig, MonthlyBudget, VendorConfig


@pytest.fixture
def config():
    return BizOpsConfig(
        budget=BudgetConfig(
            monthly_budgets=[
                MonthlyBudget(category="food_supplies", amount=5000, alert_at_pct=80),
                MonthlyBudget(category="payroll", amount=8000, alert_at_pct=85),
                MonthlyBudget(category="rent", amount=3000),
                MonthlyBudget(category="utilities", amount=1000),
            ],
            total_monthly_budget=17000,
            revenue_target=30000,
        ),
    )


@pytest.fixture
def engine(config):
    return BudgetEngine(config)


def _expenses(**kwargs):
    """Build expenses dict. Pass category=amount pairs."""
    data = {"expenses_by_category": {}}
    for cat, amount in kwargs.items():
        data["expenses_by_category"][cat] = [{"amount": amount, "vendor": "Test"}]
    return data


# ── Budget Status ────────────────────────────────────────────


class TestBudgetStatus:
    def test_on_track(self, engine):
        expenses = _expenses(food_supplies=2000, payroll=3000, rent=3000)
        data = engine.get_budget_status(expenses, as_of_date="2026-03-15")

        food = next(c for c in data["categories"] if c["category"] == "food_supplies")
        assert food["status"] == "on_track"
        assert food["used_pct"] == 40.0
        assert food["remaining"] == 3000.0

    def test_over_budget(self, engine):
        expenses = _expenses(food_supplies=6000)
        data = engine.get_budget_status(expenses, as_of_date="2026-03-20")

        food = next(c for c in data["categories"] if c["category"] == "food_supplies")
        assert food["status"] == "over_budget"
        assert food["used_pct"] == 120.0

    def test_warning_threshold(self, engine):
        expenses = _expenses(food_supplies=4200)  # 84% of 5000, above 80% alert
        data = engine.get_budget_status(expenses, as_of_date="2026-03-20")

        food = next(c for c in data["categories"] if c["category"] == "food_supplies")
        assert food["status"] == "warning"

    def test_ahead_of_pace(self, engine):
        # 50% spent but only 33% through the month (day 10 of 31)
        expenses = _expenses(food_supplies=2500)
        data = engine.get_budget_status(expenses, as_of_date="2026-03-10")

        food = next(c for c in data["categories"] if c["category"] == "food_supplies")
        assert food["status"] in ("ahead_of_pace", "warning")

    def test_no_budget_category(self, engine):
        expenses = _expenses(marketing=500)  # no budget set for marketing
        data = engine.get_budget_status(expenses, as_of_date="2026-03-15")

        marketing = next(c for c in data["categories"] if c["category"] == "marketing")
        assert marketing["status"] == "no_budget"

    def test_summary_totals(self, engine):
        expenses = _expenses(food_supplies=3000, payroll=5000, rent=3000, utilities=500)
        data = engine.get_budget_status(expenses, as_of_date="2026-03-20")

        summary = data["summary"]
        assert summary["total_budgeted"] == 17000
        assert summary["total_actual"] == 11500

    def test_month_progress(self, engine):
        expenses = _expenses(food_supplies=1000)
        data = engine.get_budget_status(expenses, as_of_date="2026-03-15")

        assert data["day_of_month"] == 15
        assert data["days_in_month"] == 31

    def test_projected_eom(self, engine):
        # Day 10: $2000 spent → projected ~$6200 for 31 days
        expenses = _expenses(food_supplies=2000)
        data = engine.get_budget_status(expenses, as_of_date="2026-03-10")

        food = next(c for c in data["categories"] if c["category"] == "food_supplies")
        assert food["projected_eom"] > 5000  # should project high

    def test_empty_expenses(self, engine):
        data = engine.get_budget_status({}, as_of_date="2026-03-15")
        assert data["summary"]["total_actual"] == 0

    def test_revenue_tracking(self, engine):
        toast = [{"net_sales": 500, "date": f"2026-03-{d:02d}"} for d in range(1, 16)]
        expenses = _expenses(food_supplies=2000)
        data = engine.get_budget_status(expenses, toast, as_of_date="2026-03-15")

        assert data["revenue"] is not None
        assert data["revenue"]["actual"] == 7500  # 15 * 500
        assert data["revenue"]["target"] == 30000

    def test_sorted_worst_first(self, engine):
        expenses = _expenses(food_supplies=6000, payroll=2000, rent=1000)
        data = engine.get_budget_status(expenses, as_of_date="2026-03-20")

        # Over budget should be first
        assert data["categories"][0]["category"] == "food_supplies"
        assert data["categories"][0]["status"] == "over_budget"


# ── Budget Alerts ────────────────────────────────────────────


class TestBudgetAlerts:
    def test_over_budget_alert(self, engine):
        expenses = _expenses(food_supplies=6000)
        alerts = engine.get_budget_alerts(expenses, as_of_date="2026-03-20")

        assert len(alerts) >= 1
        assert alerts[0]["severity"] == "critical"
        assert "food_supplies" in alerts[0]["message"]

    def test_warning_alert(self, engine):
        expenses = _expenses(food_supplies=4200)
        alerts = engine.get_budget_alerts(expenses, as_of_date="2026-03-28")

        assert any(a["severity"] == "warning" for a in alerts)

    def test_no_alerts_on_track(self, engine):
        expenses = _expenses(food_supplies=2000, payroll=3000)
        alerts = engine.get_budget_alerts(expenses, as_of_date="2026-03-15")

        assert len(alerts) == 0

    def test_sorted_by_severity(self, engine):
        expenses = _expenses(food_supplies=6000, payroll=7000)
        alerts = engine.get_budget_alerts(expenses, as_of_date="2026-03-28")

        severities = [a["severity"] for a in alerts]
        severity_order = {"critical": 0, "warning": 1, "info": 2}
        for i in range(len(severities) - 1):
            assert severity_order[severities[i]] <= severity_order[severities[i + 1]]


# ── Set Budget ───────────────────────────────────────────────


class TestSetBudget:
    def test_create_new(self, engine):
        result = engine.set_budget("marketing", 2000, 75)

        assert result["updated"] is False
        assert result["amount"] == 2000
        assert len(engine.config.budget.monthly_budgets) == 5  # was 4

    def test_update_existing(self, engine):
        result = engine.set_budget("food_supplies", 6000, 90)

        assert result["updated"] is True
        food = next(b for b in engine.config.budget.monthly_budgets if b.category == "food_supplies")
        assert food.amount == 6000
        assert food.alert_at_pct == 90


# ── Recommendations ──────────────────────────────────────────


class TestBudgetRecommendation:
    def test_basic_recommendation(self, engine):
        history = [
            _expenses(food_supplies=4000, payroll=7000),
            _expenses(food_supplies=5000, payroll=7500),
            _expenses(food_supplies=4500, payroll=8000),
        ]

        recs = engine.get_budget_recommendation(history)

        assert len(recs) >= 2
        food_rec = next(r for r in recs if r["category"] == "food_supplies")
        assert food_rec["avg_monthly"] == 4500.0
        assert food_rec["months_analyzed"] == 3

    def test_recommend_above_average(self, engine):
        history = [
            _expenses(food_supplies=4000),
            _expenses(food_supplies=5000),
            _expenses(food_supplies=4500),
        ]

        recs = engine.get_budget_recommendation(history)
        food_rec = next(r for r in recs if r["category"] == "food_supplies")
        assert food_rec["recommended_budget"] >= food_rec["avg_monthly"]

    def test_empty_history(self, engine):
        recs = engine.get_budget_recommendation([])
        assert len(recs) == 0

    def test_change_detection(self, engine):
        # Current food budget is $5000
        history = [
            _expenses(food_supplies=6000),
            _expenses(food_supplies=7000),
            _expenses(food_supplies=6500),
        ]

        recs = engine.get_budget_recommendation(history)
        food_rec = next(r for r in recs if r["category"] == "food_supplies")
        assert food_rec["change"] == "increase"  # recommending > 5000

    def test_sorted_by_amount(self, engine):
        history = [
            _expenses(food_supplies=5000, utilities=200, payroll=8000),
        ]

        recs = engine.get_budget_recommendation(history)
        amounts = [r["recommended_budget"] for r in recs]
        assert amounts == sorted(amounts, reverse=True)
