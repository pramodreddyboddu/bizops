"""P&L trend engine — month-over-month comparisons, benchmarks, and forecasting.

Aggregates existing data sources (expenses, Toast, food cost, labor) to produce
trend analysis, seasonal patterns, and industry benchmark comparisons.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from bizops.utils.config import BizOpsConfig


# Industry benchmarks for small/casual restaurants (% of revenue)
INDUSTRY_BENCHMARKS = {
    "food_cost_pct": {"target": 28.0, "acceptable": 32.0, "high": 38.0},
    "labor_pct": {"target": 25.0, "acceptable": 30.0, "high": 35.0},
    "prime_cost_pct": {"target": 55.0, "acceptable": 60.0, "high": 65.0},
    "rent_pct": {"target": 6.0, "acceptable": 8.0, "high": 10.0},
    "net_profit_pct": {"target": 10.0, "acceptable": 5.0, "low": 3.0},
}


class TrendEngine:
    """Month-over-month P&L analysis, benchmarking, and revenue forecasting."""

    def __init__(self, config: BizOpsConfig):
        self.config = config

    def get_pl_trend(self, months: int = 6) -> dict[str, Any]:
        """Build month-over-month P&L trend.

        Args:
            months: Number of months to analyze.

        Returns:
            Dict with monthly snapshots and summary statistics.
        """
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

            snap = self._build_month_snapshot(year_month, expenses, toast)
            snapshots.append(snap)

        # Add trend directions
        self._add_trends(snapshots)

        # Summary
        valid = [s for s in snapshots if s["net_sales"] > 0]
        avg_revenue = round(sum(s["net_sales"] for s in valid) / len(valid), 2) if valid else 0
        avg_expenses = round(sum(s["total_expenses"] for s in valid) / len(valid), 2) if valid else 0
        avg_margin = round(sum(s["net_profit_pct"] for s in valid) / len(valid), 1) if valid else 0

        return {
            "months_analyzed": months,
            "months_with_data": len(valid),
            "snapshots": snapshots,
            "averages": {
                "avg_monthly_revenue": avg_revenue,
                "avg_monthly_expenses": avg_expenses,
                "avg_net_profit_pct": avg_margin,
            },
        }

    def get_category_trend(self, category: str, months: int = 6) -> dict[str, Any]:
        """Track a specific expense category over time.

        Args:
            category: Expense category name (e.g., "food_supplies", "payroll").
            months: Number of months to analyze.

        Returns:
            Dict with monthly totals and % of revenue for the category.
        """
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
            cat_total = self._get_category_total(expenses, category)
            cat_pct = round(cat_total / net_sales * 100, 1) if net_sales > 0 else 0

            snapshots.append({
                "month": year_month,
                "total": round(cat_total, 2),
                "pct_of_revenue": cat_pct,
                "net_sales": round(net_sales, 2),
            })

        # Add trends
        for i, snap in enumerate(snapshots):
            if i == 0 or snap["total"] == 0:
                snap["trend"] = "flat"
            else:
                prev = snapshots[i - 1]["total"]
                if prev == 0:
                    snap["trend"] = "flat"
                elif snap["total"] > prev * 1.1:
                    snap["trend"] = "up"
                elif snap["total"] < prev * 0.9:
                    snap["trend"] = "down"
                else:
                    snap["trend"] = "flat"

        return {
            "category": category,
            "months_analyzed": months,
            "snapshots": snapshots,
        }

    def get_revenue_forecast(self, forecast_days: int = 30) -> dict[str, Any]:
        """Forecast revenue based on historical Toast POS data.

        Uses weighted average: recent weeks count more than older ones.

        Args:
            forecast_days: Number of days to project.

        Returns:
            Dict with projected daily/weekly/monthly revenue and confidence.
        """
        from bizops.utils.storage import load_toast_reports

        today = datetime.now()
        # Load 90 days of data for seasonal awareness
        start = (today - timedelta(days=90)).strftime("%Y-%m-%d")
        end = today.strftime("%Y-%m-%d")
        reports = load_toast_reports(self.config, start, end)

        if not reports:
            return {
                "forecast_days": forecast_days,
                "projected_daily": 0,
                "projected_total": 0,
                "confidence": "no_data",
                "data_days": 0,
            }

        sorted_reports = sorted(reports, key=lambda r: r.get("date", ""))

        # Weighted average: last 7 days = 50%, last 30 days = 30%, older = 20%
        recent_7 = sorted_reports[-7:] if len(sorted_reports) >= 7 else sorted_reports
        recent_30 = sorted_reports[-30:] if len(sorted_reports) >= 30 else sorted_reports
        all_data = sorted_reports

        avg_7 = sum(r.get("net_sales", 0) for r in recent_7) / len(recent_7) if recent_7 else 0
        avg_30 = sum(r.get("net_sales", 0) for r in recent_30) / len(recent_30) if recent_30 else 0
        avg_all = sum(r.get("net_sales", 0) for r in all_data) / len(all_data) if all_data else 0

        # Weighted blend
        if len(sorted_reports) >= 30:
            projected_daily = avg_7 * 0.5 + avg_30 * 0.3 + avg_all * 0.2
            confidence = "high"
        elif len(sorted_reports) >= 7:
            projected_daily = avg_7 * 0.6 + avg_all * 0.4
            confidence = "medium"
        else:
            projected_daily = avg_all
            confidence = "low"

        # Day-of-week pattern
        dow_sales = self._day_of_week_pattern(sorted_reports)

        return {
            "forecast_days": forecast_days,
            "projected_daily": round(projected_daily, 2),
            "projected_weekly": round(projected_daily * 7, 2),
            "projected_total": round(projected_daily * forecast_days, 2),
            "confidence": confidence,
            "data_days": len(sorted_reports),
            "day_of_week_pattern": dow_sales,
            "recent_7d_avg": round(avg_7, 2),
            "recent_30d_avg": round(avg_30, 2),
        }

    def get_benchmarks(self) -> dict[str, Any]:
        """Compare current metrics against industry benchmarks.

        Returns:
            Dict with each metric, current value, benchmark ranges, and grade.
        """
        from bizops.parsers.food_cost import FoodCostEngine
        from bizops.parsers.labor import LaborEngine
        from bizops.utils.storage import (
            load_bank_transactions,
            load_expenses,
            load_toast_reports,
        )

        today = datetime.now()
        start = today.replace(day=1).strftime("%Y-%m-%d")
        end = today.strftime("%Y-%m-%d")
        year_month = start[:7]

        toast = load_toast_reports(self.config, start, end)
        net_sales = sum(r.get("net_sales", 0) for r in toast)

        results = []

        # Food cost
        expenses = load_expenses(self.config, year_month)
        if expenses:
            fc_engine = FoodCostEngine(self.config)
            fc = fc_engine.calculate_food_cost(expenses, toast)
            results.append(self._grade_metric(
                "Food Cost %", fc["food_cost_pct"], INDUSTRY_BENCHMARKS["food_cost_pct"], lower_is_better=True
            ))

        # Labor cost
        bank_txns = load_bank_transactions(self.config, start, end)
        if bank_txns and toast:
            labor_engine = LaborEngine(self.config)
            labor = labor_engine.calculate_labor_cost(bank_txns, toast)
            results.append(self._grade_metric(
                "Labor Cost %", labor["labor_pct"], INDUSTRY_BENCHMARKS["labor_pct"], lower_is_better=True
            ))

            # Prime cost (food + labor)
            food_pct = fc["food_cost_pct"] if expenses else 0
            prime_pct = round(food_pct + labor["labor_pct"], 1)
            results.append(self._grade_metric(
                "Prime Cost %", prime_pct, INDUSTRY_BENCHMARKS["prime_cost_pct"], lower_is_better=True
            ))

        # Rent (from bank txns)
        rent_total = sum(
            abs(t.get("amount", 0))
            for t in bank_txns
            if t.get("type") == "debit" and t.get("category") == "rent"
        )
        if net_sales > 0 and rent_total > 0:
            rent_pct = round(rent_total / net_sales * 100, 1)
            results.append(self._grade_metric(
                "Rent %", rent_pct, INDUSTRY_BENCHMARKS["rent_pct"], lower_is_better=True
            ))

        # Net profit margin
        if expenses:
            total_expenses = sum(
                sum(i.get("amount", 0) or 0 for i in items) if isinstance(items, list) else 0
                for items in expenses.get("expenses_by_category", {}).values()
            )
            if net_sales > 0:
                profit_pct = round((net_sales - total_expenses) / net_sales * 100, 1)
                results.append(self._grade_metric(
                    "Net Profit %", profit_pct, INDUSTRY_BENCHMARKS["net_profit_pct"], lower_is_better=False
                ))

        # Overall grade
        grades = [r["grade"] for r in results if r["grade"] != "N/A"]
        grade_scores = {"A": 4, "B": 3, "C": 2, "D": 1, "F": 0}
        avg_score = sum(grade_scores.get(g, 0) for g in grades) / len(grades) if grades else 0
        overall = next(
            (g for g, s in sorted(grade_scores.items(), key=lambda x: -x[1]) if avg_score >= s - 0.5),
            "N/A",
        )

        return {
            "period": f"{start} to {end}",
            "net_sales": round(net_sales, 2),
            "metrics": results,
            "overall_grade": overall,
            "benchmarks_source": "Industry averages for small/casual dining",
        }

    # ── Helpers ────────────────────────────────────────────────

    def _build_month_snapshot(
        self,
        year_month: str,
        expenses: dict[str, Any],
        toast: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Build a single month P&L snapshot."""
        net_sales = sum(r.get("net_sales", 0) for r in toast)
        gross_sales = sum(r.get("gross_sales", 0) for r in toast)
        tips = sum(r.get("tips", 0) for r in toast)

        total_expenses = 0.0
        category_breakdown: dict[str, float] = {}
        if expenses:
            for cat, items in expenses.get("expenses_by_category", {}).items():
                if isinstance(items, list):
                    cat_total = sum(i.get("amount", 0) or 0 for i in items)
                else:
                    cat_total = 0
                if cat_total > 0:
                    category_breakdown[cat] = round(cat_total, 2)
                    total_expenses += cat_total

        net_profit = net_sales - total_expenses
        net_profit_pct = round(net_profit / net_sales * 100, 1) if net_sales > 0 else 0

        return {
            "month": year_month,
            "gross_sales": round(gross_sales, 2),
            "net_sales": round(net_sales, 2),
            "tips": round(tips, 2),
            "total_expenses": round(total_expenses, 2),
            "net_profit": round(net_profit, 2),
            "net_profit_pct": net_profit_pct,
            "expense_breakdown": category_breakdown,
            "sales_days": len(toast),
        }

    def _add_trends(self, snapshots: list[dict[str, Any]]) -> None:
        """Add trend direction to each snapshot."""
        for i, snap in enumerate(snapshots):
            if i == 0 or snap["net_sales"] == 0:
                snap["revenue_trend"] = "flat"
                snap["expense_trend"] = "flat"
                snap["profit_trend"] = "flat"
            else:
                prev = snapshots[i - 1]
                snap["revenue_trend"] = self._trend_dir(prev["net_sales"], snap["net_sales"])
                snap["expense_trend"] = self._trend_dir(prev["total_expenses"], snap["total_expenses"])
                snap["profit_trend"] = self._trend_dir(prev["net_profit_pct"], snap["net_profit_pct"])

    def _trend_dir(self, prev: float, current: float) -> str:
        """Determine trend direction."""
        if prev == 0:
            return "flat"
        pct_change = (current - prev) / abs(prev) * 100
        if pct_change > 5:
            return "up"
        elif pct_change < -5:
            return "down"
        return "flat"

    def _get_category_total(self, expenses: dict[str, Any], category: str) -> float:
        """Get total spending for a category from expenses data."""
        if not expenses:
            return 0.0
        items = expenses.get("expenses_by_category", {}).get(category, [])
        if isinstance(items, list):
            return sum(i.get("amount", 0) or 0 for i in items)
        return 0.0

    def _day_of_week_pattern(self, reports: list[dict[str, Any]]) -> dict[str, float]:
        """Calculate average sales by day of week."""
        dow_totals: dict[str, list[float]] = {
            "Monday": [], "Tuesday": [], "Wednesday": [],
            "Thursday": [], "Friday": [], "Saturday": [], "Sunday": [],
        }
        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

        for r in reports:
            date_str = r.get("date", "")
            if not date_str:
                continue
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                day_name = day_names[dt.weekday()]
                dow_totals[day_name].append(r.get("net_sales", 0))
            except (ValueError, IndexError):
                continue

        return {
            day: round(sum(sales) / len(sales), 2) if sales else 0
            for day, sales in dow_totals.items()
        }

    def _grade_metric(
        self,
        name: str,
        value: float,
        benchmark: dict[str, float],
        lower_is_better: bool = True,
    ) -> dict[str, Any]:
        """Grade a metric against industry benchmarks."""
        if lower_is_better:
            if value <= benchmark["target"]:
                grade = "A"
                status = "excellent"
            elif value <= benchmark["acceptable"]:
                grade = "B"
                status = "good"
            elif value <= benchmark["high"]:
                grade = "C"
                status = "needs_attention"
            else:
                grade = "D"
                status = "critical"
        else:
            # Higher is better (e.g., profit margin)
            if value >= benchmark["target"]:
                grade = "A"
                status = "excellent"
            elif value >= benchmark["acceptable"]:
                grade = "B"
                status = "good"
            elif value >= benchmark.get("low", 0):
                grade = "C"
                status = "needs_attention"
            else:
                grade = "D"
                status = "critical"

        return {
            "name": name,
            "value": value,
            "grade": grade,
            "status": status,
            "benchmark": benchmark,
        }
