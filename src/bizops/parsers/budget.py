"""Budget tracking engine — set budgets, track actual vs plan, alert on overruns.

For restaurant owners who want to control spending without a full accounting system.
Works with expense data from bank statements and invoices.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from bizops.utils.config import BizOpsConfig


class BudgetEngine:
    """Track actual spending vs budgets by category."""

    def __init__(self, config: BizOpsConfig):
        self.config = config
        self._budget_map = {
            b.category: b for b in config.budget.monthly_budgets
        }

    def get_budget_status(
        self,
        expenses: dict[str, Any],
        toast_data: list[dict[str, Any]] | None = None,
        as_of_date: str | None = None,
    ) -> dict[str, Any]:
        """Compare actual spending vs budget for each category.

        Args:
            expenses: Expenses dict with expenses_by_category.
            toast_data: Toast sales for revenue tracking.
            as_of_date: Date string for pace calculation (defaults to today).

        Returns:
            Dict with per-category budget status and overall summary.
        """
        today = datetime.strptime(as_of_date, "%Y-%m-%d") if as_of_date else datetime.now()
        day_of_month = today.day
        days_in_month = (today.replace(month=today.month % 12 + 1, day=1) - timedelta(days=1)).day if today.month < 12 else 31
        month_pct = day_of_month / days_in_month * 100

        categories = []
        total_budgeted = 0.0
        total_actual = 0.0

        exp_by_cat = expenses.get("expenses_by_category", {})

        for cat_name, items in exp_by_cat.items():
            if isinstance(items, list):
                actual = sum(abs(i.get("amount", 0) or 0) for i in items)
            else:
                actual = 0

            budget_entry = self._budget_map.get(cat_name)
            budgeted = budget_entry.amount if budget_entry else 0
            alert_pct = budget_entry.alert_at_pct if budget_entry else 80

            if budgeted > 0:
                used_pct = round(actual / budgeted * 100, 1)
                # Pace: are we spending faster than the month is progressing?
                pace_ratio = used_pct / month_pct if month_pct > 0 else 0
                projected = round(actual / day_of_month * days_in_month, 2) if day_of_month > 0 else actual

                if used_pct >= 100:
                    status = "over_budget"
                elif used_pct >= alert_pct:
                    status = "warning"
                elif pace_ratio > 1.2:
                    status = "ahead_of_pace"
                else:
                    status = "on_track"
            else:
                used_pct = 0
                pace_ratio = 0
                projected = actual
                status = "no_budget"

            total_budgeted += budgeted
            total_actual += actual

            categories.append({
                "category": cat_name,
                "budgeted": round(budgeted, 2),
                "actual": round(actual, 2),
                "remaining": round(max(0, budgeted - actual), 2),
                "used_pct": used_pct,
                "projected_eom": round(projected, 2),
                "status": status,
            })

        # Sort: over_budget first, then by used_pct descending
        status_order = {"over_budget": 0, "warning": 1, "ahead_of_pace": 2, "on_track": 3, "no_budget": 4}
        categories.sort(key=lambda c: (status_order.get(c["status"], 5), -c["used_pct"]))

        # Revenue tracking
        revenue = self._calculate_revenue(toast_data or [])
        revenue_target = self.config.budget.revenue_target
        total_budget = self.config.budget.total_monthly_budget or total_budgeted

        return {
            "month": today.strftime("%Y-%m"),
            "day_of_month": day_of_month,
            "days_in_month": days_in_month,
            "month_progress_pct": round(month_pct, 1),
            "categories": categories,
            "summary": {
                "total_budgeted": round(total_budget, 2),
                "total_actual": round(total_actual, 2),
                "total_remaining": round(max(0, total_budget - total_actual), 2),
                "total_used_pct": round(total_actual / total_budget * 100, 1) if total_budget > 0 else 0,
                "over_budget_count": sum(1 for c in categories if c["status"] == "over_budget"),
                "warning_count": sum(1 for c in categories if c["status"] == "warning"),
            },
            "revenue": {
                "actual": round(revenue, 2),
                "target": revenue_target,
                "pct_of_target": round(revenue / revenue_target * 100, 1) if revenue_target > 0 else 0,
                "projected_eom": round(revenue / day_of_month * days_in_month, 2) if day_of_month > 0 else 0,
            } if revenue_target > 0 else None,
        }

    def get_budget_alerts(
        self,
        expenses: dict[str, Any],
        as_of_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """Generate alerts for budget issues.

        Returns:
            List of alerts sorted by severity.
        """
        status = self.get_budget_status(expenses, as_of_date=as_of_date)
        alerts = []

        for cat in status["categories"]:
            if cat["status"] == "over_budget":
                overage = cat["actual"] - cat["budgeted"]
                alerts.append({
                    "severity": "critical",
                    "category": cat["category"],
                    "message": f"{cat['category']} is ${overage:,.0f} OVER budget ({cat['used_pct']}% used)",
                    "action": f"Review {cat['category']} spending — ${cat['actual']:,.0f} vs ${cat['budgeted']:,.0f} budget",
                })
            elif cat["status"] == "warning":
                alerts.append({
                    "severity": "warning",
                    "category": cat["category"],
                    "message": f"{cat['category']} at {cat['used_pct']}% of budget with month {status['month_progress_pct']:.0f}% done",
                    "action": f"Slow down {cat['category']} spending — ${cat['remaining']:,.0f} left for the month",
                })
            elif cat["status"] == "ahead_of_pace":
                alerts.append({
                    "severity": "info",
                    "category": cat["category"],
                    "message": f"{cat['category']} spending ahead of pace — projected ${cat['projected_eom']:,.0f} vs ${cat['budgeted']:,.0f} budget",
                    "action": f"Monitor {cat['category']} — on track to exceed budget by end of month",
                })

        # Sort by severity
        severity_order = {"critical": 0, "warning": 1, "info": 2}
        alerts.sort(key=lambda a: severity_order.get(a["severity"], 3))

        return alerts

    def set_budget(
        self,
        category: str,
        amount: float,
        alert_at_pct: float = 80.0,
    ) -> dict[str, Any]:
        """Set or update a budget for a category.

        Returns updated budget entry. Config must be saved separately.
        """
        from bizops.utils.config import MonthlyBudget

        # Update existing or create new
        for i, b in enumerate(self.config.budget.monthly_budgets):
            if b.category == category:
                self.config.budget.monthly_budgets[i] = MonthlyBudget(
                    category=category, amount=amount, alert_at_pct=alert_at_pct,
                )
                self._budget_map[category] = self.config.budget.monthly_budgets[i]
                return {"category": category, "amount": amount, "alert_at_pct": alert_at_pct, "updated": True}

        new_budget = MonthlyBudget(category=category, amount=amount, alert_at_pct=alert_at_pct)
        self.config.budget.monthly_budgets.append(new_budget)
        self._budget_map[category] = new_budget
        return {"category": category, "amount": amount, "alert_at_pct": alert_at_pct, "updated": False}

    def get_budget_recommendation(
        self,
        expenses_history: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Recommend budgets based on historical spending.

        Args:
            expenses_history: List of monthly expense dicts.

        Returns:
            List of recommended budgets by category.
        """
        cat_totals: dict[str, list[float]] = defaultdict(list)

        for month_exp in expenses_history:
            for cat, items in month_exp.get("expenses_by_category", {}).items():
                if isinstance(items, list):
                    total = sum(abs(i.get("amount", 0) or 0) for i in items)
                    cat_totals[cat].append(total)

        recommendations = []
        for cat, amounts in cat_totals.items():
            avg = sum(amounts) / len(amounts)
            max_val = max(amounts)

            # Recommend 10% above average, but not more than max
            recommended = round(min(avg * 1.10, max_val * 1.05), 2)

            current_budget = self._budget_map.get(cat)
            current = current_budget.amount if current_budget else 0

            recommendations.append({
                "category": cat,
                "recommended_budget": recommended,
                "current_budget": current,
                "avg_monthly": round(avg, 2),
                "max_monthly": round(max_val, 2),
                "months_analyzed": len(amounts),
                "change": "increase" if recommended > current and current > 0
                          else "decrease" if recommended < current and current > 0
                          else "new" if current == 0
                          else "no_change",
            })

        recommendations.sort(key=lambda r: r["recommended_budget"], reverse=True)
        return recommendations

    def _calculate_revenue(self, toast_data: list[dict[str, Any]]) -> float:
        """Sum net sales from Toast data."""
        return sum(r.get("net_sales", 0) for r in toast_data)
