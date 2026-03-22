"""Waste estimation engine — estimate food waste without inventory counts.

Since Desi Delight has no inventory system, waste is estimated by comparing:
- Actual food purchases (from invoices/expenses)
- Theoretical food usage (based on sales volume and target food cost %)

The gap between actual purchases and theoretical usage gives an estimate of
waste, spoilage, over-portioning, and theft combined.

Industry benchmark: 4-10% waste is normal for restaurants.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from bizops.utils.config import BizOpsConfig

# Industry waste benchmarks
WASTE_BENCHMARKS = {
    "excellent": 4.0,   # under 4% waste
    "good": 7.0,        # 4-7%
    "average": 10.0,    # 7-10%
    "high": 15.0,       # 10-15%
    # above 15% = critical
}


class WasteEngine:
    """Estimate food waste from the gap between purchases and theoretical usage."""

    def __init__(self, config: BizOpsConfig):
        self.config = config

    def estimate_waste(
        self,
        food_purchases: float,
        net_sales: float,
        target_food_cost_pct: float | None = None,
    ) -> dict[str, Any]:
        """Estimate waste from purchases vs theoretical usage.

        Theoretical food cost = net_sales * target_food_cost_pct / 100
        Waste estimate = actual_purchases - theoretical_usage
        Waste % = waste / actual_purchases * 100

        Args:
            food_purchases: Total food purchases for the period.
            net_sales: Total net sales for the period.
            target_food_cost_pct: Expected food cost % (defaults to config).

        Returns:
            Dict with waste estimate, percentages, and status.
        """
        if target_food_cost_pct is None:
            target_food_cost_pct = self.config.food_cost_budget.target_food_cost_pct

        if net_sales <= 0 or food_purchases <= 0:
            return {
                "food_purchases": 0,
                "theoretical_usage": 0,
                "estimated_waste": 0,
                "waste_pct": 0,
                "actual_food_cost_pct": 0,
                "target_food_cost_pct": target_food_cost_pct,
                "status": "no_data",
                "waste_dollars": 0,
            }

        theoretical_usage = net_sales * target_food_cost_pct / 100
        estimated_waste = max(0, food_purchases - theoretical_usage)
        waste_pct = round(estimated_waste / food_purchases * 100, 1) if food_purchases > 0 else 0
        actual_food_cost_pct = round(food_purchases / net_sales * 100, 1)

        status = self._get_waste_status(waste_pct)

        return {
            "food_purchases": round(food_purchases, 2),
            "theoretical_usage": round(theoretical_usage, 2),
            "estimated_waste": round(estimated_waste, 2),
            "waste_pct": waste_pct,
            "actual_food_cost_pct": actual_food_cost_pct,
            "target_food_cost_pct": target_food_cost_pct,
            "status": status,
            "waste_dollars": round(estimated_waste, 2),
        }

    def estimate_waste_from_data(self, period: str = "month") -> dict[str, Any]:
        """Load actual data and estimate waste for a period.

        Args:
            period: "month" or "quarter".

        Returns:
            Waste estimation with category breakdown.
        """
        from bizops.parsers.food_cost import FOOD_CATEGORIES
        from bizops.utils.storage import load_expenses, load_toast_reports

        today = datetime.now()
        if period == "quarter":
            q_start_month = ((today.month - 1) // 3) * 3 + 1
            start_dt = today.replace(month=q_start_month, day=1)
        else:
            start_dt = today.replace(day=1)

        start = start_dt.strftime("%Y-%m-%d")
        end = today.strftime("%Y-%m-%d")
        year_month = start[:7]

        expenses = load_expenses(self.config, year_month)
        toast = load_toast_reports(self.config, start, end)

        net_sales = sum(r.get("net_sales", 0) for r in toast)

        # Sum food purchases by category
        food_purchases = 0.0
        category_breakdown: dict[str, float] = {}
        if expenses:
            for cat in FOOD_CATEGORIES:
                items = expenses.get("expenses_by_category", {}).get(cat, [])
                if isinstance(items, list):
                    cat_total = sum(i.get("amount", 0) or 0 for i in items)
                else:
                    cat_total = 0
                if cat_total > 0:
                    category_breakdown[cat] = round(cat_total, 2)
                    food_purchases += cat_total

        waste = self.estimate_waste(food_purchases, net_sales)
        waste["period"] = {"start": start, "end": end}
        waste["category_breakdown"] = category_breakdown

        return waste

    def get_waste_trend(self, months: int = 6) -> dict[str, Any]:
        """Track waste estimates month-over-month.

        Args:
            months: Number of months to analyze.

        Returns:
            Dict with monthly waste estimates and trend direction.
        """
        from bizops.parsers.food_cost import FOOD_CATEGORIES
        from bizops.utils.storage import load_expenses, load_toast_reports

        snapshots = []
        today = datetime.now()

        for i in range(months - 1, -1, -1):
            target = today.replace(day=1) - timedelta(days=i * 28)
            year_month = target.strftime("%Y-%m")
            start = f"{year_month}-01"
            if target.month == 12:
                end_dt = target.replace(year=target.year + 1, month=1, day=1) - timedelta(days=1)
            else:
                end_dt = target.replace(month=target.month + 1, day=1) - timedelta(days=1)
            end = end_dt.strftime("%Y-%m-%d")

            expenses = load_expenses(self.config, year_month)
            toast = load_toast_reports(self.config, start, end)

            net_sales = sum(r.get("net_sales", 0) for r in toast)
            food_purchases = 0.0
            if expenses:
                for cat in FOOD_CATEGORIES:
                    items = expenses.get("expenses_by_category", {}).get(cat, [])
                    if isinstance(items, list):
                        food_purchases += sum(i.get("amount", 0) or 0 for i in items)

            waste = self.estimate_waste(food_purchases, net_sales)
            snapshots.append({
                "month": year_month,
                "waste_pct": waste["waste_pct"],
                "waste_dollars": waste["waste_dollars"],
                "food_purchases": waste["food_purchases"],
                "status": waste["status"],
            })

        # Add trend direction
        for i, snap in enumerate(snapshots):
            if i == 0 or snap["waste_pct"] == 0:
                snap["trend"] = "flat"
            else:
                prev = snapshots[i - 1]["waste_pct"]
                if prev == 0:
                    snap["trend"] = "flat"
                elif snap["waste_pct"] > prev + 1:
                    snap["trend"] = "up"
                elif snap["waste_pct"] < prev - 1:
                    snap["trend"] = "down"
                else:
                    snap["trend"] = "flat"

        return {
            "months_analyzed": months,
            "snapshots": snapshots,
        }

    def get_waste_reduction_tips(self, waste_data: dict[str, Any]) -> list[dict[str, Any]]:
        """Generate actionable waste reduction recommendations.

        Args:
            waste_data: Output from estimate_waste().

        Returns:
            List of recommendation dicts with priority, action, and impact.
        """
        tips = []
        waste_pct = waste_data.get("waste_pct", 0)
        status = waste_data.get("status", "no_data")
        category_breakdown = waste_data.get("category_breakdown", {})

        if status == "no_data":
            return [{"priority": "info", "action": "Import expense and sales data to start tracking waste.", "impact": "baseline"}]

        if waste_pct > 15:
            tips.append({
                "priority": "critical",
                "action": "Conduct a full inventory audit — waste at {:.0f}% suggests spoilage, over-ordering, or theft.".format(waste_pct),
                "impact": "Could save ${:,.0f}/month".format(waste_data.get("waste_dollars", 0) * 0.5),
            })

        if waste_pct > 10:
            tips.append({
                "priority": "high",
                "action": "Review order quantities against actual usage. Consider reducing par levels by 10-15%.",
                "impact": "Typical savings: 3-5% of food cost",
            })

        # Category-specific tips
        produce = category_breakdown.get("produce", 0)
        meat = category_breakdown.get("meat", 0)
        total = sum(category_breakdown.values()) if category_breakdown else 1

        if produce > 0 and produce / total > 0.3:
            tips.append({
                "priority": "medium",
                "action": "Produce is {:.0f}% of food spend — increase order frequency to reduce spoilage.".format(produce / total * 100),
                "impact": "Fresh produce waste drops 20-30% with more frequent, smaller orders",
            })

        if meat > 0 and meat / total > 0.25:
            tips.append({
                "priority": "medium",
                "action": "Review meat portions and storage — meat is {:.0f}% of food spend.".format(meat / total * 100),
                "impact": "Portion control can reduce meat waste by 10-15%",
            })

        if waste_pct > 7:
            tips.append({
                "priority": "medium",
                "action": "Implement a daily prep sheet to match production to expected sales.",
                "impact": "Reduces over-production waste by 15-25%",
            })

        if waste_pct <= 7 and waste_pct > 0:
            tips.append({
                "priority": "info",
                "action": "Waste at {:.0f}% is within industry norms. Focus on maintaining consistency.".format(waste_pct),
                "impact": "Already performing well — monitor for regression",
            })

        return tips

    # ── Helpers ────────────────────────────────────────────────

    def _get_waste_status(self, waste_pct: float) -> str:
        """Classify waste percentage into status."""
        if waste_pct <= WASTE_BENCHMARKS["excellent"]:
            return "excellent"
        elif waste_pct <= WASTE_BENCHMARKS["good"]:
            return "good"
        elif waste_pct <= WASTE_BENCHMARKS["average"]:
            return "average"
        elif waste_pct <= WASTE_BENCHMARKS["high"]:
            return "high"
        return "critical"
