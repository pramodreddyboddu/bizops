"""Tests for the WasteEngine — food waste estimation and reduction tips."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from bizops.parsers.waste import WASTE_BENCHMARKS, WasteEngine
from bizops.utils.config import BizOpsConfig

STORAGE = "bizops.utils.storage"


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def config():
    return BizOpsConfig()


@pytest.fixture
def engine(config):
    return WasteEngine(config)


def _expenses(food=3000, produce=1000, meat=800):
    """Build mock expenses data."""
    data = {"expenses_by_category": {}}
    if food:
        data["expenses_by_category"]["food_supplies"] = [
            {"vendor": "Sysco", "amount": food, "date": "2026-03-10"},
        ]
    if produce:
        data["expenses_by_category"]["produce"] = [
            {"vendor": "Om Produce", "amount": produce, "date": "2026-03-12"},
        ]
    if meat:
        data["expenses_by_category"]["meat"] = [
            {"vendor": "Yaman", "amount": meat, "date": "2026-03-14"},
        ]
    return data


def _toast(net_sales=10000, days=20):
    daily = net_sales / days if days else 0
    return [
        {"date": f"2026-03-{d:02d}", "net_sales": daily, "gross_sales": daily * 1.1}
        for d in range(1, days + 1)
    ]


# ── Waste Estimation ─────────────────────────────────────────


class TestEstimateWaste:
    def test_basic_waste(self, engine):
        # $3500 purchased, $3000 theoretical (10000 * 30%)
        result = engine.estimate_waste(3500, 10000, target_food_cost_pct=30)

        assert result["food_purchases"] == 3500
        assert result["theoretical_usage"] == 3000
        assert result["estimated_waste"] == 500
        assert result["waste_pct"] == 14.3  # 500/3500*100
        assert result["actual_food_cost_pct"] == 35.0

    def test_no_waste(self, engine):
        # Purchases exactly match theoretical
        result = engine.estimate_waste(3000, 10000, target_food_cost_pct=30)

        assert result["estimated_waste"] == 0
        assert result["waste_pct"] == 0

    def test_under_theoretical(self, engine):
        # Purchases LESS than theoretical — waste clamped to 0
        result = engine.estimate_waste(2500, 10000, target_food_cost_pct=30)

        assert result["estimated_waste"] == 0
        assert result["waste_pct"] == 0

    def test_no_data(self, engine):
        result = engine.estimate_waste(0, 0)
        assert result["status"] == "no_data"
        assert result["waste_pct"] == 0

    def test_no_sales(self, engine):
        result = engine.estimate_waste(1000, 0)
        assert result["status"] == "no_data"

    def test_default_target(self, engine):
        # Uses config default (30%)
        result = engine.estimate_waste(3500, 10000)
        assert result["target_food_cost_pct"] == 30.0

    def test_status_excellent(self, engine):
        # waste_pct = 3% (under 4%)
        result = engine.estimate_waste(3090, 10000, target_food_cost_pct=30)
        assert result["status"] == "excellent"

    def test_status_good(self, engine):
        # waste_pct ~6.5%
        result = engine.estimate_waste(3210, 10000, target_food_cost_pct=30)
        assert result["status"] == "good"

    def test_status_average(self, engine):
        # waste_pct ~9%
        result = engine.estimate_waste(3300, 10000, target_food_cost_pct=30)
        assert result["status"] == "average"

    def test_status_high(self, engine):
        # waste_pct ~14%
        result = engine.estimate_waste(3500, 10000, target_food_cost_pct=30)
        assert result["status"] == "high"

    def test_status_critical(self, engine):
        # waste_pct ~25%
        result = engine.estimate_waste(4000, 10000, target_food_cost_pct=30)
        assert result["status"] == "critical"


# ── Waste from Data ──────────────────────────────────────────


class TestEstimateFromData:
    def test_loads_data(self, engine):
        with patch(f"{STORAGE}.load_expenses", return_value=_expenses(food=3000, produce=1000, meat=800)), \
             patch(f"{STORAGE}.load_toast_reports", return_value=_toast(net_sales=10000)):
            data = engine.estimate_waste_from_data("month")

        assert data["food_purchases"] == 4800  # 3000 + 1000 + 800
        assert data["theoretical_usage"] == 3000  # 10000 * 30%
        assert data["estimated_waste"] == 1800
        assert "category_breakdown" in data
        assert data["category_breakdown"]["food_supplies"] == 3000

    def test_no_data(self, engine):
        with patch(f"{STORAGE}.load_expenses", return_value={}), \
             patch(f"{STORAGE}.load_toast_reports", return_value=[]):
            data = engine.estimate_waste_from_data("month")

        assert data["status"] == "no_data"

    def test_period_included(self, engine):
        with patch(f"{STORAGE}.load_expenses", return_value=_expenses()), \
             patch(f"{STORAGE}.load_toast_reports", return_value=_toast()):
            data = engine.estimate_waste_from_data("month")

        assert "period" in data


# ── Waste Trend ──────────────────────────────────────────────


class TestWasteTrend:
    def test_structure(self, engine):
        with patch(f"{STORAGE}.load_expenses", return_value=_expenses()), \
             patch(f"{STORAGE}.load_toast_reports", return_value=_toast()):
            data = engine.get_waste_trend(months=3)

        assert data["months_analyzed"] == 3
        assert len(data["snapshots"]) == 3
        for snap in data["snapshots"]:
            assert "month" in snap
            assert "waste_pct" in snap
            assert "waste_dollars" in snap
            assert "trend" in snap

    def test_trend_direction(self, engine):
        call_count = {"n": 0}
        def mock_expenses(config, ym):
            call_count["n"] += 1
            if call_count["n"] <= 1:
                return _expenses(food=3100)  # low waste
            return _expenses(food=4000)  # high waste

        with patch(f"{STORAGE}.load_expenses", side_effect=mock_expenses), \
             patch(f"{STORAGE}.load_toast_reports", return_value=_toast()):
            data = engine.get_waste_trend(months=2)

        # Second month has more waste → trend up
        assert data["snapshots"][1]["trend"] == "up"

    def test_no_data_trend(self, engine):
        with patch(f"{STORAGE}.load_expenses", return_value={}), \
             patch(f"{STORAGE}.load_toast_reports", return_value=[]):
            data = engine.get_waste_trend(months=3)

        for snap in data["snapshots"]:
            assert snap["waste_pct"] == 0


# ── Waste Reduction Tips ─────────────────────────────────────


class TestWasteReductionTips:
    def test_critical_waste(self, engine):
        data = {"waste_pct": 20, "status": "critical", "waste_dollars": 5000, "category_breakdown": {}}
        tips = engine.get_waste_reduction_tips(data)

        assert len(tips) > 0
        priorities = [t["priority"] for t in tips]
        assert "critical" in priorities

    def test_high_waste(self, engine):
        data = {"waste_pct": 12, "status": "high", "waste_dollars": 2000, "category_breakdown": {}}
        tips = engine.get_waste_reduction_tips(data)

        assert len(tips) > 0
        priorities = [t["priority"] for t in tips]
        assert "high" in priorities

    def test_good_waste(self, engine):
        data = {"waste_pct": 5, "status": "good", "waste_dollars": 500, "category_breakdown": {"food_supplies": 3000}}
        tips = engine.get_waste_reduction_tips(data)

        assert any(t["priority"] == "info" for t in tips)

    def test_no_data(self, engine):
        data = {"waste_pct": 0, "status": "no_data", "category_breakdown": {}}
        tips = engine.get_waste_reduction_tips(data)

        assert len(tips) == 1
        assert tips[0]["priority"] == "info"

    def test_produce_heavy(self, engine):
        data = {
            "waste_pct": 12, "status": "high", "waste_dollars": 2000,
            "category_breakdown": {"produce": 4000, "food_supplies": 2000, "meat": 1000},
        }
        tips = engine.get_waste_reduction_tips(data)

        produce_tips = [t for t in tips if "Produce" in t["action"] or "produce" in t["action"]]
        assert len(produce_tips) >= 1

    def test_meat_heavy(self, engine):
        data = {
            "waste_pct": 12, "status": "high", "waste_dollars": 2000,
            "category_breakdown": {"meat": 3000, "food_supplies": 2000, "produce": 500},
        }
        tips = engine.get_waste_reduction_tips(data)

        meat_tips = [t for t in tips if "meat" in t["action"].lower()]
        assert len(meat_tips) >= 1


# ── Status Helper ────────────────────────────────────────────


class TestWasteStatus:
    def test_excellent(self, engine):
        assert engine._get_waste_status(3.0) == "excellent"

    def test_good(self, engine):
        assert engine._get_waste_status(5.0) == "good"

    def test_average(self, engine):
        assert engine._get_waste_status(8.0) == "average"

    def test_high(self, engine):
        assert engine._get_waste_status(12.0) == "high"

    def test_critical(self, engine):
        assert engine._get_waste_status(20.0) == "critical"
