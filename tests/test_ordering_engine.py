"""Tests for smart ordering engine."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from bizops.parsers.ordering import OrderingEngine
from bizops.utils.config import (
    BizOpsConfig,
    FoodCostBudget,
    OrderTemplate,
    ProductItem,
    VendorConfig,
)


@pytest.fixture
def config():
    return BizOpsConfig(
        vendors=[
            VendorConfig(
                name="Om Produce",
                email_patterns=["omproduce.com"],
                category="produce",
                aliases=["Om"],
                products=[
                    ProductItem(name="Cilantro", unit="bunch", unit_cost=0.75, par_level=50, order_multiple=10, category="produce"),
                    ProductItem(name="Onions", unit="lb", unit_cost=0.50, par_level=100, order_multiple=25, category="produce"),
                    ProductItem(name="Tomatoes", unit="lb", unit_cost=1.25, par_level=80, order_multiple=20, category="produce"),
                ],
                order_day=1,
                lead_time_days=1,
            ),
            VendorConfig(
                name="Yaman Halal",
                email_patterns=["yaman"],
                category="meat",
                products=[
                    ProductItem(name="Chicken Breast", unit="lb", unit_cost=3.50, par_level=50, order_multiple=10, category="meat"),
                    ProductItem(name="Ground Lamb", unit="lb", unit_cost=8.00, par_level=30, order_multiple=5, category="meat"),
                ],
            ),
            VendorConfig(
                name="Empty Vendor",
                email_patterns=["empty"],
                category="food_supplies",
                products=[],  # No products
            ),
            VendorConfig(
                name="Inactive Products",
                email_patterns=["inactive"],
                category="food_supplies",
                products=[
                    ProductItem(name="Old Item", unit="each", unit_cost=5.0, par_level=10, active=False),
                ],
            ),
        ],
        food_cost_budget=FoodCostBudget(target_food_cost_pct=30.0),
    )


@pytest.fixture
def engine(config):
    return OrderingEngine(config)


@pytest.fixture
def toast_reports():
    return [
        {"net_sales": 1000, "date": f"2026-03-{i:02d}"} for i in range(1, 15)
    ]


# ──────────────────────────────────────────────────────────────
#  Order generation
# ──────────────────────────────────────────────────────────────


class TestOrderGeneration:
    def test_generate_basic_order(self, engine, toast_reports):
        order = engine.generate_order("Om Produce", toast_reports, budget_override=10000)

        assert order["vendor"] == "Om Produce"
        assert order["item_count"] == 3
        assert order["order_total"] > 0
        assert order["status"] == "draft"
        assert "generated_at" in order

    def test_order_items_have_correct_fields(self, engine, toast_reports):
        order = engine.generate_order("Om Produce", toast_reports, budget_override=10000)

        item = order["items"][0]
        assert "product_name" in item
        assert "quantity" in item
        assert "unit" in item
        assert "unit_cost" in item
        assert "line_total" in item

    def test_order_multiple_rounding(self, engine, toast_reports):
        order = engine.generate_order("Om Produce", toast_reports, budget_override=10000)

        for item in order["items"]:
            if item["product_name"] == "Cilantro":
                # Par level 50, order multiple 10 — should be multiple of 10
                assert item["quantity"] % 10 == 0
            elif item["product_name"] == "Onions":
                # Par level 100, order multiple 25
                assert item["quantity"] % 25 == 0

    def test_vendor_not_found(self, engine, toast_reports):
        order = engine.generate_order("Nonexistent Vendor", toast_reports)
        assert "error" in order

    def test_vendor_no_products(self, engine, toast_reports):
        order = engine.generate_order("Empty Vendor", toast_reports)
        assert "error" in order

    def test_vendor_inactive_products(self, engine, toast_reports):
        order = engine.generate_order("Inactive Products", toast_reports)
        assert "error" in order

    def test_budget_warning(self, engine, toast_reports):
        order = engine.generate_order("Om Produce", toast_reports, budget_override=10.0)
        assert order["budget_warning"] is not None
        assert "exceeds" in order["budget_warning"]

    def test_no_budget_warning_when_sufficient(self, engine, toast_reports):
        order = engine.generate_order("Om Produce", toast_reports, budget_override=50000)
        assert order["budget_warning"] is None

    def test_vendor_alias_lookup(self, engine, toast_reports):
        order = engine.generate_order("Om", toast_reports, budget_override=10000)
        assert order["vendor"] == "Om"
        assert "error" not in order

    def test_line_totals(self, engine, toast_reports):
        order = engine.generate_order("Om Produce", toast_reports, budget_override=10000)

        for item in order["items"]:
            expected = round(item["quantity"] * item["unit_cost"], 2)
            assert item["line_total"] == expected

    def test_order_total_sum(self, engine, toast_reports):
        order = engine.generate_order("Om Produce", toast_reports, budget_override=10000)

        expected_total = round(sum(i["line_total"] for i in order["items"]), 2)
        assert order["order_total"] == expected_total


# ──────────────────────────────────────────────────────────────
#  Sales velocity scaling
# ──────────────────────────────────────────────────────────────


class TestVelocityScaling:
    def test_flat_velocity_preserves_par(self, engine):
        # Flat sales → ratio ~1.0 → quantities near par levels
        reports = [{"net_sales": 1000, "date": f"2026-03-{i:02d}"} for i in range(1, 15)]
        order = engine.generate_order("Om Produce", reports, budget_override=50000)

        cilantro = next(i for i in order["items"] if i["product_name"] == "Cilantro")
        assert cilantro["quantity"] == 50  # par_level=50, ratio~1.0, multiple=10

    def test_high_velocity_scales_up(self, engine):
        # Early slow, recent fast → ratio > 1
        reports = [{"net_sales": 500, "date": f"2026-03-{i:02d}"} for i in range(1, 8)]
        reports += [{"net_sales": 2000, "date": f"2026-03-{i:02d}"} for i in range(8, 15)]

        order = engine.generate_order("Om Produce", reports, budget_override=50000)

        cilantro = next(i for i in order["items"] if i["product_name"] == "Cilantro")
        assert cilantro["quantity"] >= 50  # Should be scaled up
        assert cilantro["velocity_adjusted"] is True

    def test_low_velocity_scales_down(self, engine):
        # Early fast, recent slow → ratio < 1
        reports = [{"net_sales": 2000, "date": f"2026-03-{i:02d}"} for i in range(1, 8)]
        reports += [{"net_sales": 500, "date": f"2026-03-{i:02d}"} for i in range(8, 15)]

        order = engine.generate_order("Om Produce", reports, budget_override=50000)

        cilantro = next(i for i in order["items"] if i["product_name"] == "Cilantro")
        # Scaled down but still rounded to order_multiple=10
        assert cilantro["quantity"] % 10 == 0

    def test_no_toast_data_defaults(self, engine):
        order = engine.generate_order("Om Produce", [], budget_override=50000)
        assert order["sales_velocity"]["velocity_ratio"] == 1.0


# ──────────────────────────────────────────────────────────────
#  Generate all orders
# ──────────────────────────────────────────────────────────────


class TestGenerateAll:
    def test_generates_for_vendors_with_products(self, engine, toast_reports):
        with patch.object(engine, "get_available_budget", return_value={"budget_remaining": 50000}):
            orders = engine.generate_all_orders(toast_reports)

        # Om Produce and Yaman Halal have active products, Empty and Inactive do not
        assert len(orders) == 2
        vendors = {o["vendor"] for o in orders}
        assert "Om Produce" in vendors
        assert "Yaman Halal" in vendors

    def test_empty_config(self):
        config = BizOpsConfig()
        engine = OrderingEngine(config)
        orders = engine.generate_all_orders([])
        assert orders == []


# ──────────────────────────────────────────────────────────────
#  Budget
# ──────────────────────────────────────────────────────────────


class TestBudget:
    def test_budget_structure(self, engine, toast_reports):
        with patch("bizops.parsers.ordering.OrderingEngine._get_food_spending_this_month", return_value=5000):
            budget = engine.get_available_budget(toast_reports)

        assert "projected_monthly_sales" in budget
        assert "food_budget" in budget
        assert "already_spent" in budget
        assert "budget_remaining" in budget
        assert "target_pct" in budget
        assert budget["target_pct"] == 30.0

    def test_budget_remaining_non_negative(self, engine, toast_reports):
        with patch("bizops.parsers.ordering.OrderingEngine._get_food_spending_this_month", return_value=999999):
            budget = engine.get_available_budget(toast_reports)

        assert budget["budget_remaining"] >= 0

    def test_budget_with_no_sales(self, engine):
        with patch("bizops.parsers.ordering.OrderingEngine._get_food_spending_this_month", return_value=0):
            budget = engine.get_available_budget([])

        assert budget["projected_monthly_sales"] == 0
        assert budget["food_budget"] == 0


# ──────────────────────────────────────────────────────────────
#  Templates
# ──────────────────────────────────────────────────────────────


class TestTemplates:
    def test_apply_template(self, engine):
        template = OrderTemplate(
            vendor_name="Om Produce",
            items=[
                {"product_name": "Cilantro", "quantity": 50},
                {"product_name": "Onions", "quantity": 100},
            ],
            frequency="weekly",
            day_of_week=1,
        )

        order = engine.apply_template(template)

        assert order["vendor"] == "Om Produce"
        assert order["item_count"] == 2
        assert order["status"] == "draft"

        cilantro = next(i for i in order["items"] if i["product_name"] == "Cilantro")
        assert cilantro["quantity"] == 50
        assert cilantro["unit_cost"] == 0.75
        assert cilantro["line_total"] == 37.50
        assert cilantro["in_catalog"] is True

    def test_template_product_not_in_catalog(self, engine):
        template = OrderTemplate(
            vendor_name="Om Produce",
            items=[{"product_name": "Unknown Item", "quantity": 10}],
        )

        order = engine.apply_template(template)

        item = order["items"][0]
        assert item["in_catalog"] is False
        assert item["unit_cost"] == 0.0

    def test_template_vendor_not_found(self, engine):
        template = OrderTemplate(vendor_name="Ghost Vendor", items=[])
        result = engine.apply_template(template)
        assert "error" in result


# ──────────────────────────────────────────────────────────────
#  Reorder suggestions
# ──────────────────────────────────────────────────────────────


class TestReorderSuggestions:
    def test_suggestions_for_active_vendors(self, engine):
        suggestions = engine.get_reorder_suggestions()

        assert len(suggestions) == 2  # Om Produce and Yaman Halal
        vendors = {s["vendor"] for s in suggestions}
        assert "Om Produce" in vendors
        assert "Yaman Halal" in vendors

    def test_suggestion_structure(self, engine):
        suggestions = engine.get_reorder_suggestions()

        om = next(s for s in suggestions if s["vendor"] == "Om Produce")
        assert om["product_count"] == 3
        assert om["est_total"] > 0
        assert len(om["products"]) == 3
        assert om["products"][0]["name"] == "Cilantro"

    def test_no_suggestions_for_empty_config(self):
        config = BizOpsConfig()
        engine = OrderingEngine(config)
        assert engine.get_reorder_suggestions() == []
