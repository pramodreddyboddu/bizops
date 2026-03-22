"""Smart ordering engine — generate purchase orders based on sales and budget.

Uses Toast POS sales velocity, vendor product catalogs (par levels),
and available budget to recommend what to order and how much.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from bizops.utils.config import BizOpsConfig, OrderTemplate, VendorConfig
from bizops.parsers.food_cost import FOOD_CATEGORIES, FoodCostEngine


class OrderingEngine:
    """Generate purchase orders based on sales velocity, par levels, and budget."""

    def __init__(self, config: BizOpsConfig):
        self.config = config
        self.food_cost_engine = FoodCostEngine(config)

    def generate_order(
        self,
        vendor_name: str,
        toast_reports: list[dict[str, Any]] | None = None,
        budget_override: float | None = None,
    ) -> dict[str, Any]:
        """Generate a recommended purchase order for a vendor.

        Args:
            vendor_name: Vendor to generate order for.
            toast_reports: Toast POS data for sales velocity.
            budget_override: Override available budget (for testing).

        Returns:
            Order dict with vendor, items, total, budget info, generated_at.
        """
        vendor = self._find_vendor(vendor_name)
        if not vendor:
            return {"error": f"Vendor '{vendor_name}' not found in config."}

        products = [p for p in vendor.products if p.active and p.par_level > 0]
        if not products:
            return {
                "error": f"No products with par levels configured for '{vendor_name}'.",
                "vendor": vendor_name,
            }

        # Get sales velocity
        velocity = self.food_cost_engine.calculate_sales_velocity(
            toast_reports or []
        )
        ratio = velocity["velocity_ratio"]

        # Get available budget
        if budget_override is not None:
            budget_remaining = budget_override
        else:
            budget_info = self.get_available_budget(toast_reports)
            budget_remaining = budget_info["budget_remaining"]

        # Generate order items
        items = []
        order_total = 0.0

        for product in products:
            # Scale quantity by sales velocity
            base_qty = product.par_level
            scaled_qty = base_qty * ratio

            # Round up to order multiple
            if product.order_multiple > 0:
                scaled_qty = (
                    math.ceil(scaled_qty / product.order_multiple)
                    * product.order_multiple
                )
            else:
                scaled_qty = math.ceil(scaled_qty)

            line_total = round(scaled_qty * product.unit_cost, 2)

            items.append({
                "product_name": product.name,
                "sku": product.sku,
                "quantity": scaled_qty,
                "unit": product.unit,
                "unit_cost": product.unit_cost,
                "line_total": line_total,
                "category": product.category,
                "par_level": product.par_level,
                "velocity_adjusted": ratio != 1.0,
            })
            order_total += line_total

        order_total = round(order_total, 2)

        # Budget warning
        budget_warning = None
        if budget_remaining > 0 and order_total > budget_remaining:
            budget_warning = (
                f"Order total ${order_total:,.2f} exceeds remaining budget "
                f"${budget_remaining:,.2f} by ${order_total - budget_remaining:,.2f}"
            )

        return {
            "vendor": vendor_name,
            "items": items,
            "item_count": len(items),
            "order_total": order_total,
            "budget_remaining": round(budget_remaining, 2),
            "budget_warning": budget_warning,
            "sales_velocity": velocity,
            "generated_at": datetime.now().isoformat(),
            "status": "draft",
        }

    def generate_all_orders(
        self,
        toast_reports: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Generate orders for all vendors with products configured."""
        orders = []
        for vendor in self.config.vendors:
            if any(p.active and p.par_level > 0 for p in vendor.products):
                order = self.generate_order(vendor.name, toast_reports)
                if "error" not in order:
                    orders.append(order)
        return orders

    def get_available_budget(
        self,
        toast_reports: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Calculate available ordering budget based on sales projections.

        Budget = (target_food_cost_pct / 100 * projected_monthly_sales)
                 - already_spent_on_food_this_month

        Returns:
            Dict with projected_monthly_sales, food_budget, already_spent,
            budget_remaining, and target_pct.
        """
        toast_reports = toast_reports or []

        # Calculate projected monthly sales
        velocity = self.food_cost_engine.calculate_sales_velocity(toast_reports)
        avg_daily = velocity["avg_daily_sales"]
        today = datetime.now()

        # Days in current month
        if today.month == 12:
            days_in_month = (today.replace(year=today.year + 1, month=1, day=1)
                           - today.replace(day=1)).days
        else:
            days_in_month = (today.replace(month=today.month + 1, day=1)
                           - today.replace(day=1)).days

        projected_monthly_sales = round(avg_daily * days_in_month, 2)

        # Food budget from target
        target_pct = self.config.food_cost_budget.target_food_cost_pct
        food_budget = round(projected_monthly_sales * target_pct / 100, 2)

        # Already spent on food this month (from storage if available)
        already_spent = self._get_food_spending_this_month()

        budget_remaining = round(food_budget - already_spent, 2)

        return {
            "projected_monthly_sales": projected_monthly_sales,
            "food_budget": food_budget,
            "already_spent": round(already_spent, 2),
            "budget_remaining": max(budget_remaining, 0),
            "target_pct": target_pct,
            "days_in_month": days_in_month,
            "day_of_month": today.day,
            "avg_daily_sales": avg_daily,
        }

    def apply_template(
        self,
        template: OrderTemplate,
        toast_reports: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Generate an order from a recurring template.

        Looks up current prices from the vendor's product catalog.
        """
        vendor = self._find_vendor(template.vendor_name)
        if not vendor:
            return {"error": f"Vendor '{template.vendor_name}' not found."}

        # Build product lookup
        product_map = {p.name.lower(): p for p in vendor.products if p.active}

        items = []
        order_total = 0.0

        for item in template.items:
            name = item.get("product_name", "")
            qty = item.get("quantity", 0)
            product = product_map.get(name.lower())

            if product:
                unit_cost = product.unit_cost
                unit = product.unit
            else:
                unit_cost = 0.0
                unit = "each"

            line_total = round(qty * unit_cost, 2)
            items.append({
                "product_name": name,
                "quantity": qty,
                "unit": unit,
                "unit_cost": unit_cost,
                "line_total": line_total,
                "in_catalog": product is not None,
            })
            order_total += line_total

        return {
            "vendor": template.vendor_name,
            "items": items,
            "item_count": len(items),
            "order_total": round(order_total, 2),
            "template_frequency": template.frequency,
            "generated_at": datetime.now().isoformat(),
            "status": "draft",
        }

    def get_reorder_suggestions(
        self,
        toast_reports: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Scan all vendors for products that may need reordering.

        Based on par levels and the number of vendors with products configured.
        """
        suggestions = []
        for vendor in self.config.vendors:
            products_needing_order = [
                p for p in vendor.products
                if p.active and p.par_level > 0
            ]
            if products_needing_order:
                suggestions.append({
                    "vendor": vendor.name,
                    "product_count": len(products_needing_order),
                    "products": [
                        {
                            "name": p.name,
                            "par_level": p.par_level,
                            "unit": p.unit,
                            "unit_cost": p.unit_cost,
                            "est_cost": round(p.par_level * p.unit_cost, 2),
                        }
                        for p in products_needing_order
                    ],
                    "est_total": round(
                        sum(p.par_level * p.unit_cost for p in products_needing_order), 2
                    ),
                    "order_day": vendor.order_day,
                    "lead_time_days": vendor.lead_time_days,
                })
        return suggestions

    # ──────────────────────────────────────────────────────────
    #  Internal helpers
    # ──────────────────────────────────────────────────────────

    def _find_vendor(self, name: str) -> VendorConfig | None:
        """Find a vendor by name (case-insensitive)."""
        name_lower = name.lower()
        for v in self.config.vendors:
            if v.name.lower() == name_lower:
                return v
            if any(a.lower() == name_lower for a in v.aliases):
                return v
        return None

    def _get_food_spending_this_month(self) -> float:
        """Get total food-category spending for current month from storage."""
        from bizops.utils.storage import load_expenses

        year_month = datetime.now().strftime("%Y-%m")
        expenses = load_expenses(self.config, year_month)
        if not expenses:
            return 0.0

        expenses_by_cat = expenses.get("expenses_by_category", {})
        total = 0.0
        for cat in FOOD_CATEGORIES:
            items = expenses_by_cat.get(cat, [])
            if isinstance(items, list):
                total += sum(i.get("amount", 0) or 0 for i in items)
            elif isinstance(items, (int, float)):
                total += float(items)

        return total
