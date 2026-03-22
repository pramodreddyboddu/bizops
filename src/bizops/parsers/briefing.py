"""Daily owner briefing engine — aggregates all business data into one view.

Pulls from Toast POS, bank statements, labor engine, food cost engine,
ordering engine, and invoices to produce a comprehensive daily briefing.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from bizops.utils.config import BizOpsConfig


class BriefingEngine:
    """Generate comprehensive daily business briefings."""

    def __init__(self, config: BizOpsConfig):
        self.config = config

    def generate_briefing(self, date: str | None = None) -> dict[str, Any]:
        """Generate a full daily briefing.

        Args:
            date: Target date YYYY-MM-DD. Defaults to yesterday.

        Returns:
            Dict with briefing_date, generated_at, and sections
            (sales, cash_position, labor, food_cost, orders_due, invoices, alerts).
        """
        if date is None:
            date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        sales = self._build_sales_section(date)
        cash = self._build_cash_position(date)
        labor = self._build_labor_section(date)
        food_cost = self._build_food_cost_section(date)
        orders_due = self._build_orders_due_section(date)
        invoices = self._build_invoices_section(date)
        alerts = self._build_alerts(sales, cash, labor, food_cost)

        return {
            "briefing_date": date,
            "generated_at": datetime.now().isoformat(),
            "sections": {
                "sales": sales,
                "cash_position": cash,
                "labor": labor,
                "food_cost": food_cost,
                "orders_due": orders_due,
                "invoices": invoices,
                "alerts": alerts,
            },
        }

    def _build_sales_section(self, date: str) -> dict[str, Any]:
        """Build sales section from Toast POS data."""
        from bizops.utils.storage import load_toast_reports

        # Load target date
        reports = load_toast_reports(self.config, date, date)

        gross = sum(r.get("gross_sales", 0) for r in reports)
        net = sum(r.get("net_sales", 0) for r in reports)
        tax = sum(r.get("tax", 0) for r in reports)
        tips = sum(r.get("tips", 0) for r in reports)

        # Week-over-week comparison
        target_dt = datetime.strptime(date, "%Y-%m-%d")
        last_week_date = (target_dt - timedelta(days=7)).strftime("%Y-%m-%d")
        last_week = load_toast_reports(self.config, last_week_date, last_week_date)

        vs_last_week = None
        if last_week:
            lw_gross = sum(r.get("gross_sales", 0) for r in last_week)
            if lw_gross > 0:
                diff = gross - lw_gross
                pct_change = round(diff / lw_gross * 100, 1)
                vs_last_week = {"diff": round(diff, 2), "pct_change": pct_change}

        return {
            "gross_sales": round(gross, 2),
            "net_sales": round(net, 2),
            "tax": round(tax, 2),
            "tips": round(tips, 2),
            "total_orders": len(reports),
            "vs_last_week": vs_last_week,
        }

    def _build_cash_position(self, date: str) -> dict[str, Any]:
        """Build cash position from bank transactions."""
        from bizops.utils.storage import load_bank_transactions

        # Load all bank txns for the month up to target date
        target_dt = datetime.strptime(date, "%Y-%m-%d")
        month_start = target_dt.replace(day=1).strftime("%Y-%m-%d")

        txns = load_bank_transactions(self.config, month_start, date)

        credits = [t for t in txns if t.get("type") == "credit"]
        debits = [t for t in txns if t.get("type") == "debit"]

        mtd_credits = sum(t.get("amount", 0) for t in credits)
        mtd_debits = sum(t.get("amount", 0) for t in debits)  # negative values
        estimated_balance = mtd_credits + mtd_debits

        # Recent transactions (last 5 each, sorted by date desc)
        recent_deposits = sorted(credits, key=lambda t: t.get("date", ""), reverse=True)[:5]
        recent_payments = sorted(debits, key=lambda t: t.get("date", ""), reverse=True)[:5]

        return {
            "estimated_balance": round(estimated_balance, 2),
            "mtd_credits": round(mtd_credits, 2),
            "mtd_debits": round(mtd_debits, 2),
            "recent_deposits": [
                {"date": t.get("date"), "description": t.get("description", ""), "amount": t.get("amount", 0)}
                for t in recent_deposits
            ],
            "recent_payments": [
                {"date": t.get("date"), "description": t.get("description", ""), "amount": t.get("amount", 0)}
                for t in recent_payments
            ],
        }

    def _build_labor_section(self, date: str) -> dict[str, Any]:
        """Build labor section using LaborEngine."""
        from bizops.parsers.labor import LaborEngine
        from bizops.utils.storage import load_bank_transactions, load_toast_reports

        target_dt = datetime.strptime(date, "%Y-%m-%d")
        month_start = target_dt.replace(day=1).strftime("%Y-%m-%d")

        bank_txns = load_bank_transactions(self.config, month_start, date)
        toast = load_toast_reports(self.config, month_start, date)

        engine = LaborEngine(self.config)
        labor = engine.calculate_labor_cost(bank_txns, toast)

        return {
            "total_labor": labor["total_labor"],
            "labor_pct": labor["labor_pct"],
            "status": labor["status"],
            "breakdown": {
                "adp": labor["breakdown"]["adp"]["total"],
                "cash": labor["breakdown"]["cash_payments"]["total"],
            },
        }

    def _build_food_cost_section(self, date: str) -> dict[str, Any]:
        """Build food cost section using FoodCostEngine."""
        from bizops.parsers.food_cost import FoodCostEngine
        from bizops.utils.storage import load_expenses, load_food_cost, load_toast_reports

        target_dt = datetime.strptime(date, "%Y-%m-%d")
        year_month = target_dt.strftime("%Y-%m")

        # Try loading existing food cost data first
        fc_data = load_food_cost(self.config, year_month)

        if not fc_data:
            # Calculate from raw data
            month_start = target_dt.replace(day=1).strftime("%Y-%m-%d")
            expenses = load_expenses(self.config, year_month)
            toast = load_toast_reports(self.config, month_start, date)

            if expenses:
                engine = FoodCostEngine(self.config)
                fc_data = engine.calculate_food_cost(expenses, toast)

        if fc_data:
            return {
                "food_cost_pct": fc_data.get("food_cost_pct", 0),
                "food_cost_total": fc_data.get("food_cost_total", 0),
                "net_sales": fc_data.get("net_sales", 0),
                "status": fc_data.get("status", "no_data"),
            }

        return {
            "food_cost_pct": 0,
            "food_cost_total": 0,
            "net_sales": 0,
            "status": "no_data",
        }

    def _build_orders_due_section(self, date: str) -> dict[str, Any]:
        """Check which vendors need ordering today or tomorrow."""
        target_dt = datetime.strptime(date, "%Y-%m-%d")
        # The briefing date is yesterday, but orders due = today and tomorrow
        today = datetime.now()
        tomorrow = today + timedelta(days=1)
        today_dow = today.weekday()  # 0=Mon
        tomorrow_dow = tomorrow.weekday()

        today_orders = []
        tomorrow_orders = []

        for vendor in self.config.vendors:
            if vendor.order_day < 0:
                continue

            active_products = [p for p in vendor.products if p.active]
            if not active_products:
                continue

            est_total = sum(p.unit_cost * p.par_level for p in active_products)
            entry = {
                "vendor": vendor.name,
                "product_count": len(active_products),
                "est_total": round(est_total, 2),
            }

            if vendor.order_day == today_dow:
                today_orders.append(entry)
            elif vendor.order_day == tomorrow_dow:
                tomorrow_orders.append(entry)

        return {"today": today_orders, "tomorrow": tomorrow_orders}

    def _build_invoices_section(self, date: str) -> dict[str, Any]:
        """Summarize outstanding invoices."""
        from bizops.utils.storage import load_invoices

        target_dt = datetime.strptime(date, "%Y-%m-%d")
        month_start = target_dt.replace(day=1).strftime("%Y-%m-%d")

        invoices = load_invoices(self.config, month_start, date)

        # Count unpaid invoices (transaction_type == "payment" that aren't reconciled)
        unpaid = [
            inv for inv in invoices
            if inv.get("transaction_type") == "payment"
            and not inv.get("reconciled", False)
        ]

        total_outstanding = sum(inv.get("amount", 0) for inv in unpaid)

        # Overdue = unpaid with date > 15 days ago
        overdue_cutoff = (target_dt - timedelta(days=15)).strftime("%Y-%m-%d")
        overdue = [inv for inv in unpaid if inv.get("date", "") < overdue_cutoff]
        overdue_amount = sum(inv.get("amount", 0) for inv in overdue)

        return {
            "total_outstanding": round(total_outstanding, 2),
            "unpaid_count": len(unpaid),
            "overdue_count": len(overdue),
            "overdue_amount": round(overdue_amount, 2),
        }

    def _build_alerts(
        self,
        sales: dict[str, Any],
        cash: dict[str, Any],
        labor: dict[str, Any],
        food_cost: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Aggregate alerts from all sections."""
        alerts = []

        # Food cost alerts
        fc_status = food_cost.get("status", "no_data")
        fc_pct = food_cost.get("food_cost_pct", 0)
        if fc_status == "critical":
            alerts.append({
                "type": "critical",
                "severity": "high",
                "message": f"Food cost at {fc_pct}% — above threshold!",
                "source": "food_cost",
            })
        elif fc_status == "warning":
            alerts.append({
                "type": "warning",
                "severity": "medium",
                "message": f"Food cost at {fc_pct}% — above target.",
                "source": "food_cost",
            })

        # Labor alerts
        labor_status = labor.get("status", "no_data")
        labor_pct = labor.get("labor_pct", 0)
        if labor_status == "critical":
            alerts.append({
                "type": "critical",
                "severity": "high",
                "message": f"Labor cost at {labor_pct}% — above threshold!",
                "source": "labor",
            })
        elif labor_status == "warning":
            alerts.append({
                "type": "warning",
                "severity": "medium",
                "message": f"Labor cost at {labor_pct}% — above target.",
                "source": "labor",
            })

        # Cash flow warning
        balance = cash.get("estimated_balance", 0)
        if balance < 2000 and balance != 0:
            alerts.append({
                "type": "warning",
                "severity": "high",
                "message": f"Low cash balance: ${balance:,.2f} — review upcoming payments.",
                "source": "cash",
            })

        # Sales anomaly — big drop vs last week
        vs = sales.get("vs_last_week")
        if vs and vs.get("pct_change") is not None:
            pct = vs["pct_change"]
            if pct < -30:
                alerts.append({
                    "type": "warning",
                    "severity": "medium",
                    "message": f"Sales dropped {abs(pct):.1f}% vs last week.",
                    "source": "sales",
                })
            elif pct > 30:
                alerts.append({
                    "type": "info",
                    "severity": "low",
                    "message": f"Sales up {pct:.1f}% vs last week — consider stocking up.",
                    "source": "sales",
                })

        return alerts
