"""Business health score engine — one number that tells you how your business is doing.

Combines food cost, labor cost, waste, sales trends, cash position, and payment
discipline into a single 0-100 score with letter grade (A-F).

Designed as the ultimate SaaS hook — owners check their score daily.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from bizops.utils.config import BizOpsConfig


# Score weights (must sum to 100)
SCORE_WEIGHTS = {
    "food_cost": 20,       # food cost % vs target
    "labor_cost": 20,      # labor cost % vs target
    "profit_margin": 20,   # net profit %
    "sales_trend": 15,     # revenue growth/stability
    "cash_position": 15,   # cash balance health
    "payment_discipline": 10,  # % of invoices paid on time
}

# Letter grade thresholds
GRADE_THRESHOLDS = {
    90: "A",
    80: "B",
    70: "C",
    60: "D",
    0: "F",
}


class HealthScoreEngine:
    """Calculate a single 0-100 business health score."""

    def __init__(self, config: BizOpsConfig):
        self.config = config

    def calculate_score(self) -> dict[str, Any]:
        """Calculate the overall business health score.

        Returns:
            Dict with overall score, letter grade, component scores,
            and improvement suggestions.
        """
        components = {}

        components["food_cost"] = self._score_food_cost()
        components["labor_cost"] = self._score_labor_cost()
        components["profit_margin"] = self._score_profit_margin()
        components["sales_trend"] = self._score_sales_trend()
        components["cash_position"] = self._score_cash_position()
        components["payment_discipline"] = self._score_payment_discipline()

        # Calculate weighted overall score
        overall = 0.0
        scored_weight = 0
        for key, weight in SCORE_WEIGHTS.items():
            comp = components[key]
            if comp["status"] != "no_data":
                overall += comp["score"] * weight / 100
                scored_weight += weight

        # Normalize if not all components have data
        if scored_weight > 0 and scored_weight < 100:
            overall = overall * 100 / scored_weight

        overall = round(overall, 1)
        grade = self._get_grade(overall)

        # Generate improvement suggestions
        suggestions = self._generate_suggestions(components)

        return {
            "overall_score": overall,
            "grade": grade,
            "components": components,
            "suggestions": suggestions,
            "scored_at": datetime.now().isoformat(),
            "data_coverage": f"{scored_weight}%",
        }

    def _score_food_cost(self) -> dict[str, Any]:
        """Score food cost % (0-100, lower food cost = higher score)."""
        from bizops.parsers.food_cost import FoodCostEngine
        from bizops.utils.storage import load_expenses, load_toast_reports

        today = datetime.now()
        start = today.replace(day=1).strftime("%Y-%m-%d")
        end = today.strftime("%Y-%m-%d")
        year_month = start[:7]

        expenses = load_expenses(self.config, year_month)
        toast = load_toast_reports(self.config, start, end)

        if not expenses and not toast:
            return {"score": 0, "value": 0, "status": "no_data", "detail": "No data"}

        engine = FoodCostEngine(self.config)
        fc = engine.calculate_food_cost(expenses or {}, toast)
        pct = fc["food_cost_pct"]

        # Score: 100 at 25%, 80 at 30%, 60 at 35%, 0 at 50%+
        score = max(0, min(100, 100 - (pct - 25) * 4))

        return {
            "score": round(score, 1),
            "value": pct,
            "unit": "%",
            "status": fc["status"],
            "detail": f"Food cost at {pct}% of revenue",
        }

    def _score_labor_cost(self) -> dict[str, Any]:
        """Score labor cost % (0-100, lower = better)."""
        from bizops.parsers.labor import LaborEngine
        from bizops.utils.storage import load_bank_transactions, load_toast_reports

        today = datetime.now()
        start = today.replace(day=1).strftime("%Y-%m-%d")
        end = today.strftime("%Y-%m-%d")

        bank = load_bank_transactions(self.config, start, end)
        toast = load_toast_reports(self.config, start, end)

        if not bank and not toast:
            return {"score": 0, "value": 0, "status": "no_data", "detail": "No data"}

        engine = LaborEngine(self.config)
        labor = engine.calculate_labor_cost(bank, toast)
        pct = labor["labor_pct"]

        # Score: 100 at 20%, 80 at 28%, 60 at 33%, 0 at 45%+
        score = max(0, min(100, 100 - (pct - 20) * 4))

        return {
            "score": round(score, 1),
            "value": pct,
            "unit": "%",
            "status": labor["status"],
            "detail": f"Labor cost at {pct}% of revenue",
        }

    def _score_profit_margin(self) -> dict[str, Any]:
        """Score net profit margin (0-100, higher = better)."""
        from bizops.utils.storage import load_expenses, load_toast_reports

        today = datetime.now()
        start = today.replace(day=1).strftime("%Y-%m-%d")
        end = today.strftime("%Y-%m-%d")
        year_month = start[:7]

        expenses = load_expenses(self.config, year_month)
        toast = load_toast_reports(self.config, start, end)

        net_sales = sum(r.get("net_sales", 0) for r in toast)
        if not expenses or net_sales <= 0:
            return {"score": 0, "value": 0, "status": "no_data", "detail": "No data"}

        total_expenses = sum(
            sum(i.get("amount", 0) or 0 for i in items) if isinstance(items, list) else 0
            for items in expenses.get("expenses_by_category", {}).values()
        )

        margin_pct = round((net_sales - total_expenses) / net_sales * 100, 1)

        # Score: 100 at 15%+, 80 at 10%, 50 at 5%, 0 at 0% or negative
        score = max(0, min(100, margin_pct * 6.67))

        return {
            "score": round(score, 1),
            "value": margin_pct,
            "unit": "%",
            "status": "healthy" if margin_pct >= 10 else "warning" if margin_pct >= 5 else "critical",
            "detail": f"Net profit margin at {margin_pct}%",
        }

    def _score_sales_trend(self) -> dict[str, Any]:
        """Score sales trend (growth = good, decline = bad)."""
        from bizops.utils.storage import load_toast_reports

        today = datetime.now()

        # Current month
        current_start = today.replace(day=1).strftime("%Y-%m-%d")
        current_end = today.strftime("%Y-%m-%d")
        current_toast = load_toast_reports(self.config, current_start, current_end)

        # Previous month
        prev_end = (today.replace(day=1) - timedelta(days=1))
        prev_start = prev_end.replace(day=1).strftime("%Y-%m-%d")
        prev_toast = load_toast_reports(self.config, prev_start, prev_end.strftime("%Y-%m-%d"))

        if not current_toast:
            return {"score": 0, "value": 0, "status": "no_data", "detail": "No data"}

        current_daily = sum(r.get("net_sales", 0) for r in current_toast) / len(current_toast)

        if not prev_toast:
            # No comparison, give neutral score
            return {
                "score": 70,
                "value": round(current_daily, 2),
                "unit": "$/day",
                "status": "no_comparison",
                "detail": f"Avg daily sales ${current_daily:,.0f} (no prior month to compare)",
            }

        prev_daily = sum(r.get("net_sales", 0) for r in prev_toast) / len(prev_toast)
        if prev_daily <= 0:
            return {"score": 70, "value": 0, "status": "no_comparison", "detail": "No comparison data"}

        growth_pct = round((current_daily - prev_daily) / prev_daily * 100, 1)

        # Score: 100 at +10%, 80 at +5%, 70 at flat, 50 at -5%, 0 at -20%
        score = max(0, min(100, 70 + growth_pct * 3))

        status = "growing" if growth_pct > 2 else "declining" if growth_pct < -2 else "stable"

        return {
            "score": round(score, 1),
            "value": growth_pct,
            "unit": "% vs last month",
            "status": status,
            "detail": f"Sales {'up' if growth_pct > 0 else 'down'} {abs(growth_pct)}% vs last month",
        }

    def _score_cash_position(self) -> dict[str, Any]:
        """Score cash position (healthy balance = good)."""
        from bizops.utils.storage import load_bank_transactions

        today = datetime.now()
        start = today.replace(day=1).strftime("%Y-%m-%d")
        end = today.strftime("%Y-%m-%d")

        txns = load_bank_transactions(self.config, start, end)
        if not txns:
            return {"score": 0, "value": 0, "status": "no_data", "detail": "No data"}

        balance = sum(t.get("amount", 0) for t in txns)

        # Score: 100 at $20k+, 80 at $10k, 50 at $5k, 20 at $2k, 0 at $0
        if balance >= 20000:
            score = 100
        elif balance >= 5000:
            score = 50 + (balance - 5000) / 15000 * 50
        elif balance >= 0:
            score = balance / 5000 * 50
        else:
            score = 0

        status = "healthy" if balance >= 10000 else "warning" if balance >= 2000 else "critical"

        return {
            "score": round(score, 1),
            "value": round(balance, 2),
            "unit": "$",
            "status": status,
            "detail": f"Estimated balance ${balance:,.0f}",
        }

    def _score_payment_discipline(self) -> dict[str, Any]:
        """Score how well invoices are paid on time."""
        from bizops.parsers.payments import PaymentEngine
        from bizops.utils.storage import load_bank_transactions, load_invoices

        today = datetime.now()
        start = today.replace(day=1).strftime("%Y-%m-%d")
        end = today.strftime("%Y-%m-%d")

        invoices = load_invoices(self.config, start, end)
        bank = load_bank_transactions(self.config, start, end)

        if not invoices:
            return {"score": 0, "value": 0, "status": "no_data", "detail": "No data"}

        engine = PaymentEngine(self.config)
        status_data = engine.get_payment_status(invoices, bank, end)
        summary = status_data.get("summary", {})

        total = summary.get("total_invoiced", 0)
        paid = summary.get("total_paid", 0)
        overdue = summary.get("total_overdue", 0)

        if total <= 0:
            return {"score": 0, "value": 0, "status": "no_data", "detail": "No invoices"}

        paid_pct = round(paid / total * 100, 1)
        overdue_pct = round(overdue / total * 100, 1) if total > 0 else 0

        # Score: 100 if all paid, penalty for overdue
        score = max(0, min(100, paid_pct - overdue_pct * 2))

        status = "excellent" if overdue_pct == 0 else "warning" if overdue_pct < 20 else "critical"

        return {
            "score": round(score, 1),
            "value": paid_pct,
            "unit": "% paid",
            "status": status,
            "detail": f"{paid_pct}% paid on time, {overdue_pct}% overdue",
        }

    def _get_grade(self, score: float) -> str:
        """Convert numeric score to letter grade."""
        for threshold, grade in sorted(GRADE_THRESHOLDS.items(), reverse=True):
            if score >= threshold:
                return grade
        return "F"

    def _generate_suggestions(self, components: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        """Generate top improvement suggestions based on lowest-scoring areas."""
        suggestions = []

        # Sort by score ascending (worst first), exclude no_data
        scored = [
            (key, comp) for key, comp in components.items()
            if comp["status"] != "no_data"
        ]
        scored.sort(key=lambda x: x[1]["score"])

        for key, comp in scored[:3]:
            weight = SCORE_WEIGHTS.get(key, 0)
            potential = round((100 - comp["score"]) * weight / 100, 1)

            label = key.replace("_", " ").title()

            if key == "food_cost" and comp["score"] < 70:
                suggestions.append({
                    "area": label,
                    "current_score": comp["score"],
                    "potential_points": potential,
                    "action": f"Reduce food cost from {comp['value']}% — review portions, waste, and vendor pricing.",
                })
            elif key == "labor_cost" and comp["score"] < 70:
                suggestions.append({
                    "area": label,
                    "current_score": comp["score"],
                    "potential_points": potential,
                    "action": f"Optimize labor from {comp['value']}% — review scheduling and overtime.",
                })
            elif key == "profit_margin" and comp["score"] < 70:
                suggestions.append({
                    "area": label,
                    "current_score": comp["score"],
                    "potential_points": potential,
                    "action": f"Improve margin from {comp['value']}% — focus on high-margin items and cost control.",
                })
            elif key == "sales_trend" and comp["score"] < 60:
                suggestions.append({
                    "area": label,
                    "current_score": comp["score"],
                    "potential_points": potential,
                    "action": "Sales declining — consider promotions, menu updates, or marketing.",
                })
            elif key == "cash_position" and comp["score"] < 60:
                suggestions.append({
                    "area": label,
                    "current_score": comp["score"],
                    "potential_points": potential,
                    "action": f"Low cash (${comp['value']:,.0f}) — collect overdue payments and review expenses.",
                })
            elif key == "payment_discipline" and comp["score"] < 70:
                suggestions.append({
                    "area": label,
                    "current_score": comp["score"],
                    "potential_points": potential,
                    "action": "Pay vendors on time to maintain relationships and avoid late fees.",
                })

        return suggestions
