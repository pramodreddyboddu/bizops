"""Inventory estimation engine — estimate stock from purchases and usage.

For businesses without a formal inventory system:
- Track what was purchased (from invoices)
- Estimate daily usage based on sales volume
- Flag items likely running low
- Recommend reorder timing
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from bizops.utils.config import BizOpsConfig


class InventoryEstimator:
    """Estimate inventory levels from purchase and sales data."""

    def __init__(self, config: BizOpsConfig):
        self.config = config
        # Build product lookup from vendor configs
        self._products: dict[str, dict[str, Any]] = {}
        for vc in config.vendors:
            for p in vc.products:
                self._products[p.name.lower()] = {
                    "name": p.name,
                    "vendor": vc.name,
                    "unit": p.unit,
                    "unit_cost": p.unit_cost,
                    "par_level": p.par_level,
                    "category": p.category,
                }

    def estimate_stock(
        self,
        invoices: list[dict[str, Any]],
        toast_data: list[dict[str, Any]] | None = None,
        as_of_date: str | None = None,
    ) -> dict[str, Any]:
        """Estimate current stock levels based on purchases and estimated usage.

        Args:
            invoices: Invoice records with product line items.
            toast_data: Toast sales for usage estimation.
            as_of_date: Calculate stock as of this date.

        Returns:
            Dict with per-category stock estimates and reorder alerts.
        """
        today = datetime.strptime(as_of_date, "%Y-%m-%d") if as_of_date else datetime.now()

        # Sum purchases by category
        purchases = self._sum_purchases(invoices)

        # Estimate daily usage from sales
        daily_usage = self._estimate_usage(toast_data or [], purchases)

        # Calculate estimated stock
        items = []
        low_stock = []

        for category, purchase_data in purchases.items():
            total_purchased = purchase_data["total_amount"]
            last_purchase = purchase_data["last_date"]
            purchase_count = purchase_data["count"]

            # Days since last purchase
            if last_purchase:
                last_dt = datetime.strptime(last_purchase, "%Y-%m-%d")
                days_since = (today - last_dt).days
            else:
                days_since = 0

            # Daily usage estimate (based on ratio to sales)
            usage_rate = daily_usage.get(category, 0)

            # Estimated remaining value
            estimated_used = usage_rate * days_since
            estimated_remaining = max(0, total_purchased - estimated_used)

            # Days of stock remaining
            days_remaining = round(estimated_remaining / usage_rate, 1) if usage_rate > 0 else 999

            # Status
            if days_remaining <= 2:
                status = "critical"
            elif days_remaining <= 5:
                status = "low"
            elif days_remaining <= 7:
                status = "reorder_soon"
            else:
                status = "adequate"

            item = {
                "category": category,
                "total_purchased": round(total_purchased, 2),
                "estimated_remaining": round(estimated_remaining, 2),
                "days_since_purchase": days_since,
                "est_daily_usage": round(usage_rate, 2),
                "est_days_remaining": days_remaining,
                "purchase_count": purchase_count,
                "status": status,
            }
            items.append(item)

            if status in ("critical", "low", "reorder_soon"):
                low_stock.append(item)

        # Sort: critical first
        status_order = {"critical": 0, "low": 1, "reorder_soon": 2, "adequate": 3}
        items.sort(key=lambda i: (status_order.get(i["status"], 4), i.get("est_days_remaining", 999)))

        return {
            "as_of": today.strftime("%Y-%m-%d"),
            "items": items,
            "low_stock_count": len(low_stock),
            "low_stock": low_stock,
            "total_inventory_value": round(sum(i["estimated_remaining"] for i in items), 2),
        }

    def get_reorder_list(
        self,
        invoices: list[dict[str, Any]],
        toast_data: list[dict[str, Any]] | None = None,
        as_of_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get list of items that need to be reordered.

        Returns:
            List of reorder recommendations with suggested vendors and amounts.
        """
        stock = self.estimate_stock(invoices, toast_data, as_of_date)
        reorders = []

        for item in stock["items"]:
            if item["status"] not in ("critical", "low", "reorder_soon"):
                continue

            # Find the vendor for this category
            vendor = self._find_vendor_for_category(item["category"])

            # Suggest order amount (7 days of stock)
            suggested_amount = round(item["est_daily_usage"] * 7, 2) if item["est_daily_usage"] > 0 else 0

            urgency = "order_today" if item["status"] == "critical" else "order_soon" if item["status"] == "low" else "plan_order"

            reorders.append({
                "category": item["category"],
                "vendor": vendor,
                "urgency": urgency,
                "est_days_left": item["est_days_remaining"],
                "suggested_order_value": suggested_amount,
                "last_purchased_days_ago": item["days_since_purchase"],
            })

        return reorders

    def get_purchase_frequency(
        self,
        invoices: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Analyze purchase patterns — how often and how much per vendor/category.

        Returns:
            List of purchase frequency data by vendor.
        """
        vendor_purchases: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for inv in invoices:
            if inv.get("transaction_type") not in ("payment", None):
                continue
            vendor = inv.get("vendor", "Unknown")
            vendor_purchases[vendor].append({
                "amount": abs(inv.get("amount", 0)),
                "date": inv.get("date", ""),
            })

        patterns = []
        for vendor, purchases in vendor_purchases.items():
            if len(purchases) < 2:
                continue

            amounts = [p["amount"] for p in purchases]
            dates = sorted(p["date"] for p in purchases if p.get("date"))

            # Calculate average days between orders
            if len(dates) >= 2:
                date_objs = [datetime.strptime(d, "%Y-%m-%d") for d in dates]
                gaps = [(date_objs[i + 1] - date_objs[i]).days for i in range(len(date_objs) - 1)]
                avg_gap = sum(gaps) / len(gaps)
            else:
                avg_gap = 0

            patterns.append({
                "vendor": vendor,
                "order_count": len(purchases),
                "avg_order_value": round(sum(amounts) / len(amounts), 2),
                "total_spend": round(sum(amounts), 2),
                "avg_days_between_orders": round(avg_gap, 1),
                "estimated_frequency": self._frequency_label(avg_gap),
            })

        patterns.sort(key=lambda p: p["total_spend"], reverse=True)
        return patterns

    # ── Helpers ────────────────────────────────────────────────

    def _sum_purchases(self, invoices: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Sum purchase amounts by category from invoices."""
        categories: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"total_amount": 0, "last_date": "", "count": 0}
        )

        for inv in invoices:
            if inv.get("transaction_type") not in ("payment", None):
                continue

            vendor = inv.get("vendor", "Unknown")
            amount = abs(inv.get("amount", 0))
            date = inv.get("date", "")

            # Map vendor to category
            category = self._vendor_category(vendor)

            cat_data = categories[category]
            cat_data["total_amount"] += amount
            cat_data["count"] += 1
            if date > cat_data["last_date"]:
                cat_data["last_date"] = date

        return dict(categories)

    def _estimate_usage(
        self,
        toast_data: list[dict[str, Any]],
        purchases: dict[str, dict[str, Any]],
    ) -> dict[str, float]:
        """Estimate daily usage per category based on sales and industry ratios.

        Industry rule of thumb:
        - Food supplies: ~30% of daily sales
        - Produce: ~8% of daily sales
        - Meat: ~12% of daily sales
        - Beverages: ~5% of daily sales
        - Cleaning/supplies: ~2% of daily sales
        """
        if not toast_data:
            # Fallback: assume 30-day usage cycle
            return {
                cat: data["total_amount"] / 30
                for cat, data in purchases.items()
            }

        daily_sales = sum(r.get("net_sales", 0) for r in toast_data) / len(toast_data) if toast_data else 0

        usage_ratios = {
            "food_supplies": 0.30,
            "produce": 0.08,
            "meat": 0.12,
            "beverages": 0.05,
            "cleaning": 0.02,
            "miscellaneous": 0.03,
        }

        usage = {}
        for cat in purchases:
            ratio = usage_ratios.get(cat, 0.05)
            usage[cat] = daily_sales * ratio

        return usage

    def _vendor_category(self, vendor: str) -> str:
        """Get category for a vendor from config."""
        vendor_lower = vendor.lower()
        for vc in self.config.vendors:
            if vc.name.lower() == vendor_lower or any(a.lower() == vendor_lower for a in vc.aliases):
                return vc.category
        return "miscellaneous"

    def _find_vendor_for_category(self, category: str) -> str:
        """Find preferred vendor for a category."""
        for vc in self.config.vendors:
            if vc.category == category:
                return vc.name
        return "Unknown"

    def _frequency_label(self, avg_days: float) -> str:
        """Convert average gap to human label."""
        if avg_days <= 0:
            return "unknown"
        elif avg_days <= 3:
            return "multiple_per_week"
        elif avg_days <= 8:
            return "weekly"
        elif avg_days <= 16:
            return "biweekly"
        elif avg_days <= 35:
            return "monthly"
        else:
            return "infrequent"
