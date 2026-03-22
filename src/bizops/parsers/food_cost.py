"""Food cost analytics engine — calculate food cost %, trends, and alerts.

Uses expense data from ExpenseEngine and revenue from Toast POS to compute
food cost percentages, month-over-month trends, and budget alerts.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from bizops.utils.config import BizOpsConfig


# Categories that count toward food cost
FOOD_CATEGORIES = {"food_supplies", "produce", "meat", "beverages"}


class FoodCostEngine:
    """Calculate food cost percentages and trend analysis."""

    def __init__(self, config: BizOpsConfig):
        self.config = config
        self.budget = config.food_cost_budget

    def calculate_food_cost(
        self,
        expenses_data: dict[str, Any],
        toast_data: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Calculate food cost percentage from expense and sales data.

        Args:
            expenses_data: P&L result from ExpenseEngine.categorize_all().
            toast_data: Optional Toast POS daily reports (used if revenue
                        is not already in expenses_data).

        Returns:
            Dict with food_cost_total, net_sales, food_cost_pct,
            by_category breakdown, and status.
        """
        expenses_by_cat = expenses_data.get("expenses_by_category", {})

        # Sum food-related expenses
        food_totals: dict[str, float] = {}
        food_cost_total = 0.0
        for cat in FOOD_CATEGORIES:
            items = expenses_by_cat.get(cat, [])
            if isinstance(items, list):
                cat_total = sum(i.get("amount", 0) or 0 for i in items)
            else:
                cat_total = float(items) if items else 0.0
            food_totals[cat] = round(cat_total, 2)
            food_cost_total += cat_total

        food_cost_total = round(food_cost_total, 2)

        # Get net sales from revenue data or toast reports
        revenue = expenses_data.get("revenue", {})
        net_sales = revenue.get("net_sales", 0.0)
        if not net_sales and toast_data:
            net_sales = sum(r.get("net_sales", 0) for r in toast_data)
        net_sales = round(net_sales, 2)

        # Calculate percentage
        food_cost_pct = (food_cost_total / net_sales * 100) if net_sales > 0 else 0.0
        food_cost_pct = round(food_cost_pct, 1)

        # Determine status
        status = "healthy"
        if food_cost_pct >= self.budget.alert_threshold_pct:
            status = "critical"
        elif food_cost_pct >= self.budget.target_food_cost_pct:
            status = "warning"

        # Per-category percentage
        by_category = {}
        for cat, total in food_totals.items():
            pct = (total / net_sales * 100) if net_sales > 0 else 0.0
            by_category[cat] = {
                "total": total,
                "pct": round(pct, 1),
            }

        return {
            "food_cost_total": food_cost_total,
            "net_sales": net_sales,
            "food_cost_pct": food_cost_pct,
            "by_category": by_category,
            "status": status,
            "target_pct": self.budget.target_food_cost_pct,
            "alert_threshold_pct": self.budget.alert_threshold_pct,
        }

    def month_over_month(self, months: int = 3) -> list[dict[str, Any]]:
        """Load expense and toast data for the last N months and compute trends.

        Returns:
            List of monthly snapshots, each with month, food_cost_pct,
            food_cost_total, net_sales, and trend direction.
        """
        from bizops.utils.storage import load_expenses, load_toast_reports

        snapshots = []
        today = datetime.now()

        for i in range(months - 1, -1, -1):
            # Calculate month
            target = today.replace(day=1) - timedelta(days=i * 28)
            year_month = target.strftime("%Y-%m")
            start = f"{year_month}-01"
            # End of month
            if target.month == 12:
                end_dt = target.replace(year=target.year + 1, month=1, day=1) - timedelta(days=1)
            else:
                end_dt = target.replace(month=target.month + 1, day=1) - timedelta(days=1)
            end = end_dt.strftime("%Y-%m-%d")

            expenses = load_expenses(self.config, year_month)
            toast = load_toast_reports(self.config, start, end)

            if expenses:
                fc = self.calculate_food_cost(expenses, toast)
                snapshots.append({
                    "month": year_month,
                    "food_cost_pct": fc["food_cost_pct"],
                    "food_cost_total": fc["food_cost_total"],
                    "net_sales": fc["net_sales"],
                    "status": fc["status"],
                })
            else:
                snapshots.append({
                    "month": year_month,
                    "food_cost_pct": 0.0,
                    "food_cost_total": 0.0,
                    "net_sales": 0.0,
                    "status": "no_data",
                })

        # Add trend direction
        for i, snap in enumerate(snapshots):
            if i == 0 or snap["food_cost_pct"] == 0:
                snap["trend"] = "flat"
            else:
                prev = snapshots[i - 1]["food_cost_pct"]
                if prev == 0:
                    snap["trend"] = "flat"
                elif snap["food_cost_pct"] > prev:
                    snap["trend"] = "up"
                elif snap["food_cost_pct"] < prev:
                    snap["trend"] = "down"
                else:
                    snap["trend"] = "flat"

        return snapshots

    def check_alerts(self, food_cost_data: dict[str, Any]) -> list[dict[str, Any]]:
        """Check current food cost data against budget thresholds.

        Returns:
            List of alert dicts with category, current, threshold, and message.
        """
        alerts = []

        # Overall food cost alert
        pct = food_cost_data.get("food_cost_pct", 0)
        if pct >= self.budget.alert_threshold_pct:
            alerts.append({
                "type": "critical",
                "category": "overall",
                "current": pct,
                "threshold": self.budget.alert_threshold_pct,
                "message": f"Food cost at {pct}% — above {self.budget.alert_threshold_pct}% threshold!",
            })
        elif pct >= self.budget.target_food_cost_pct:
            alerts.append({
                "type": "warning",
                "category": "overall",
                "current": pct,
                "threshold": self.budget.target_food_cost_pct,
                "message": f"Food cost at {pct}% — above {self.budget.target_food_cost_pct}% target.",
            })

        # Per-category budget alerts
        by_cat = food_cost_data.get("by_category", {})
        for cat, budget_limit in self.budget.category_budgets.items():
            cat_data = by_cat.get(cat, {})
            cat_total = cat_data.get("total", 0) if isinstance(cat_data, dict) else 0
            if cat_total > budget_limit:
                overage = round(cat_total - budget_limit, 2)
                label = cat.replace("_", " ").title()
                alerts.append({
                    "type": "over_budget",
                    "category": cat,
                    "current": cat_total,
                    "threshold": budget_limit,
                    "overage": overage,
                    "message": f"{label} spending ${cat_total:,.2f} exceeds ${budget_limit:,.2f} budget by ${overage:,.2f}",
                })

        return alerts

    def calculate_sales_velocity(
        self,
        toast_reports: list[dict[str, Any]],
        recent_days: int = 7,
    ) -> dict[str, Any]:
        """Compute average daily sales and trend direction.

        Args:
            toast_reports: Toast POS daily reports sorted by date.
            recent_days: Number of recent days for short-term average.

        Returns:
            Dict with avg_daily_sales, avg_weekly_sales, velocity_ratio,
            trend_direction, and days_analyzed.
        """
        if not toast_reports:
            return {
                "avg_daily_sales": 0.0,
                "avg_weekly_sales": 0.0,
                "velocity_ratio": 1.0,
                "trend_direction": "flat",
                "days_analyzed": 0,
            }

        # Sort by date
        sorted_reports = sorted(toast_reports, key=lambda r: r.get("date", ""))

        # Overall average
        all_sales = [r.get("net_sales", 0) for r in sorted_reports]
        overall_avg = sum(all_sales) / len(all_sales) if all_sales else 0

        # Recent average
        recent = sorted_reports[-recent_days:] if len(sorted_reports) >= recent_days else sorted_reports
        recent_sales = [r.get("net_sales", 0) for r in recent]
        recent_avg = sum(recent_sales) / len(recent_sales) if recent_sales else 0

        # Velocity ratio: how recent sales compare to overall
        velocity_ratio = (recent_avg / overall_avg) if overall_avg > 0 else 1.0

        # Trend direction
        if velocity_ratio > 1.05:
            trend = "up"
        elif velocity_ratio < 0.95:
            trend = "down"
        else:
            trend = "flat"

        return {
            "avg_daily_sales": round(recent_avg, 2),
            "avg_weekly_sales": round(recent_avg * 7, 2),
            "velocity_ratio": round(velocity_ratio, 3),
            "trend_direction": trend,
            "days_analyzed": len(sorted_reports),
        }
