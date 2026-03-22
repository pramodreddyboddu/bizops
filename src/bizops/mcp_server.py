"""BizOps MCP Server — expose business data to AI tools via Model Context Protocol.

Run with:
    python -m bizops.mcp_server
    # or via the MCP config in your Claude Desktop / IDE settings
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from mcp.server.fastmcp import FastMCP

from bizops.utils.config import ExpenseCategory, load_config
from bizops.utils.storage import (
    load_bank_transactions,
    load_expenses,
    load_food_cost,
    load_invoices,
    load_orders,
    load_reconciliation,
    load_toast_reports,
)

# ──────────────────────────────────────────────────────────────
#  Server setup
# ──────────────────────────────────────────────────────────────

mcp = FastMCP(
    "bizops",
    instructions="Business operations data for Desi Delight restaurant — invoices, expenses, P&L, and Toast POS data.",
)


def _resolve_dates(period: str) -> tuple[str, str]:
    """Convert a period name to start/end date strings."""
    today = datetime.now()
    if period == "today":
        d = today.strftime("%Y-%m-%d")
        return d, d
    elif period == "week":
        start = today - timedelta(days=today.weekday())
        return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
    elif period == "quarter":
        q_start_month = ((today.month - 1) // 3) * 3 + 1
        start = today.replace(month=q_start_month, day=1)
        return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
    else:  # default: month
        start = today.replace(day=1)
        return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")


# ──────────────────────────────────────────────────────────────
#  Tools
# ──────────────────────────────────────────────────────────────


@mcp.tool()
def get_invoices(
    period: str = "month",
    vendor: str | None = None,
) -> str:
    """Get invoices for a time period, optionally filtered by vendor.

    Args:
        period: Time period — "today", "week", "month", or "quarter".
        vendor: Optional vendor name filter (case-insensitive partial match).

    Returns:
        JSON string with invoice list and summary stats.
    """
    config = load_config()
    start, end = _resolve_dates(period)
    invoices = load_invoices(config, start, end)

    if vendor:
        vendor_lower = vendor.lower()
        invoices = [
            inv for inv in invoices
            if vendor_lower in (inv.get("vendor") or "").lower()
        ]

    # Build summary
    total = sum(inv.get("amount") or 0 for inv in invoices)
    vendor_totals: dict[str, float] = defaultdict(float)
    for inv in invoices:
        v = inv.get("vendor", "Unknown")
        vendor_totals[v] += float(inv.get("amount") or 0)

    return json.dumps({
        "period": {"start": start, "end": end},
        "count": len(invoices),
        "total_amount": round(total, 2),
        "by_vendor": {k: round(v, 2) for k, v in sorted(vendor_totals.items(), key=lambda x: x[1], reverse=True)},
        "invoices": invoices[:50],  # Limit to avoid huge responses
    }, default=str, indent=2)


@mcp.tool()
def get_expenses(period: str = "month") -> str:
    """Get categorized expense data and P&L summary.

    Args:
        period: Time period — "today", "week", "month", or "quarter".

    Returns:
        JSON string with P&L data including revenue, expenses by category, and totals.
    """
    config = load_config()
    start, end = _resolve_dates(period)
    year_month = start[:7]

    expenses = load_expenses(config, year_month)

    if not expenses:
        return json.dumps({
            "period": {"start": start, "end": end},
            "message": "No expense data found. Run 'bizops expenses track' first.",
        }, indent=2)

    # Simplify the response — show category totals instead of full invoice lists
    category_summary: dict[str, dict[str, Any]] = {}
    for cat, items in expenses.get("expenses_by_category", {}).items():
        cat_total = sum(i.get("amount") or 0 for i in items)
        if cat_total > 0 or items:
            category_summary[cat] = {
                "total": round(cat_total, 2),
                "count": len(items),
                "top_vendors": _top_vendors(items, 5),
            }

    return json.dumps({
        "period": expenses.get("period", {"start": start, "end": end}),
        "revenue": expenses.get("revenue", {}),
        "totals": expenses.get("totals", {}),
        "expenses_by_category": category_summary,
    }, default=str, indent=2)


@mcp.tool()
def get_toast_sales(period: str = "month") -> str:
    """Get Toast POS daily sales data.

    Args:
        period: Time period — "today", "week", "month", or "quarter".

    Returns:
        JSON string with daily sales breakdown and period totals.
    """
    config = load_config()
    start, end = _resolve_dates(period)
    reports = load_toast_reports(config, start, end)

    if not reports:
        return json.dumps({
            "period": {"start": start, "end": end},
            "message": "No Toast POS data found.",
            "days": 0,
        }, indent=2)

    gross = sum(r.get("gross_sales", 0) for r in reports)
    net = sum(r.get("net_sales", 0) for r in reports)
    tax = sum(r.get("tax", 0) for r in reports)
    tips = sum(r.get("tips", 0) for r in reports)
    orders = sum(r.get("total_orders", 0) for r in reports)

    daily = sorted(
        [
            {
                "date": r.get("date", ""),
                "gross_sales": r.get("gross_sales", 0),
                "net_sales": r.get("net_sales", 0),
                "orders": r.get("total_orders", 0),
            }
            for r in reports
        ],
        key=lambda d: d.get("date", ""),
    )

    return json.dumps({
        "period": {"start": start, "end": end},
        "days": len(reports),
        "totals": {
            "gross_sales": round(gross, 2),
            "net_sales": round(net, 2),
            "tax": round(tax, 2),
            "tips": round(tips, 2),
            "total_orders": orders,
        },
        "daily": daily,
    }, default=str, indent=2)


@mcp.tool()
def get_vendor_summary(period: str = "month") -> str:
    """Get a summary of spending by vendor.

    Args:
        period: Time period — "today", "week", "month", or "quarter".

    Returns:
        JSON string with vendor spend rankings and details.
    """
    config = load_config()
    start, end = _resolve_dates(period)
    invoices = load_invoices(config, start, end)

    vendor_data: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"total": 0.0, "count": 0, "dates": []}
    )

    for inv in invoices:
        v = inv.get("vendor", "Unknown")
        amount = float(inv.get("amount") or 0)
        vendor_data[v]["total"] += amount
        vendor_data[v]["count"] += 1
        if inv.get("date"):
            vendor_data[v]["dates"].append(inv["date"])

    # Sort by total spend descending
    ranked = []
    for v, data in sorted(vendor_data.items(), key=lambda x: x[1]["total"], reverse=True):
        ranked.append({
            "vendor": v,
            "total_spend": round(data["total"], 2),
            "invoice_count": data["count"],
            "first_date": min(data["dates"]) if data["dates"] else None,
            "last_date": max(data["dates"]) if data["dates"] else None,
        })

    total_spend = sum(r["total_spend"] for r in ranked)

    return json.dumps({
        "period": {"start": start, "end": end},
        "total_vendors": len(ranked),
        "total_spend": round(total_spend, 2),
        "vendors": ranked,
    }, default=str, indent=2)


@mcp.tool()
def get_pl_summary(period: str = "month") -> str:
    """Get a simplified Profit & Loss summary.

    Args:
        period: Time period — "today", "week", "month", or "quarter".

    Returns:
        JSON string with revenue, expense totals, and net profit.
    """
    config = load_config()
    start, end = _resolve_dates(period)
    year_month = start[:7]

    expenses = load_expenses(config, year_month)

    if not expenses:
        return json.dumps({
            "period": {"start": start, "end": end},
            "message": "No P&L data found. Run 'bizops expenses track' first.",
        }, indent=2)

    revenue = expenses.get("revenue", {})
    totals = expenses.get("totals", {})

    # Category breakdown
    category_totals: dict[str, float] = {}
    for cat, items in expenses.get("expenses_by_category", {}).items():
        cat_total = sum(i.get("amount") or 0 for i in items)
        if cat_total > 0:
            category_totals[cat.replace("_", " ").title()] = round(cat_total, 2)

    return json.dumps({
        "period": expenses.get("period", {"start": start, "end": end}),
        "revenue": {
            "gross_sales": revenue.get("gross_sales", 0),
            "net_sales": revenue.get("net_sales", 0),
            "tax_collected": revenue.get("tax", 0),
            "tips": revenue.get("tips", 0),
        },
        "expenses": category_totals,
        "total_expenses": totals.get("total_expenses", 0),
        "net_profit": totals.get("net_profit", 0),
    }, default=str, indent=2)


@mcp.tool()
def list_expense_categories() -> str:
    """List all available expense categories with their keyword triggers.

    Returns:
        JSON string with categories and associated keywords.
    """
    config = load_config()
    keywords = config.category_keywords.model_dump()

    categories = []
    for cat in ExpenseCategory:
        categories.append({
            "name": cat.value,
            "label": cat.value.replace("_", " ").title(),
            "keywords": keywords.get(cat.value, []),
        })

    return json.dumps({"categories": categories}, indent=2)


@mcp.tool()
def list_vendors() -> str:
    """List all configured vendors with their categories and email patterns.

    Returns:
        JSON string with vendor configurations.
    """
    config = load_config()
    vendors = []
    for v in config.vendors:
        vendors.append({
            "name": v.name,
            "category": v.category,
            "email_patterns": v.email_patterns,
            "aliases": v.aliases,
        })

    return json.dumps({
        "total_vendors": len(vendors),
        "vendors": vendors,
    }, indent=2)


@mcp.tool()
def get_bank_transactions(
    period: str = "month",
    type_filter: str | None = None,
    category: str | None = None,
) -> str:
    """Get bank transactions, optionally filtered by type or category.

    Args:
        period: Time period — "today", "week", "month", or "quarter".
        type_filter: Optional filter — "credit", "debit", or None for all.
        category: Optional category filter (case-insensitive partial match).

    Returns:
        JSON string with bank transactions and summary.
    """
    config = load_config()
    start, end = _resolve_dates(period)
    txns = load_bank_transactions(config, start, end)

    if type_filter:
        txns = [t for t in txns if t.get("type") == type_filter]

    if category:
        cat_lower = category.lower()
        txns = [t for t in txns if cat_lower in (t.get("category") or "").lower()]

    total_debits = sum(t.get("amount", 0) for t in txns if t.get("type") == "debit")
    total_credits = sum(t.get("amount", 0) for t in txns if t.get("type") == "credit")

    return json.dumps({
        "period": {"start": start, "end": end},
        "count": len(txns),
        "total_debits": round(total_debits, 2),
        "total_credits": round(total_credits, 2),
        "net_flow": round(total_debits + total_credits, 2),
        "transactions": txns[:100],
    }, default=str, indent=2)


@mcp.tool()
def get_reconciliation(period: str = "month") -> str:
    """Get reconciliation results — matched and unmatched transactions.

    Args:
        period: Time period — "today", "week", "month", or "quarter".

    Returns:
        JSON with match rate, unmatched bank items (hidden expenses), and unmatched invoices.
    """
    config = load_config()
    start, end = _resolve_dates(period)
    year_month = start[:7]

    result = load_reconciliation(config, year_month)

    if not result:
        return json.dumps({
            "period": {"start": start, "end": end},
            "message": "No reconciliation data found. Run 'bizops bank reconcile' first.",
        }, indent=2)

    summary = result.get("summary", {})
    unmatched_bank = result.get("unmatched_bank", [])

    # Summarize hidden expenses by category
    hidden_by_cat: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"total": 0.0, "count": 0}
    )
    for txn in unmatched_bank:
        if txn.get("type") == "debit":
            cat = txn.get("category", "uncategorized")
            hidden_by_cat[cat]["total"] += abs(txn.get("amount", 0))
            hidden_by_cat[cat]["count"] += 1

    return json.dumps({
        "period": {"start": start, "end": end},
        "summary": summary,
        "hidden_expenses": {
            k: {"total": round(v["total"], 2), "count": v["count"]}
            for k, v in sorted(hidden_by_cat.items(), key=lambda x: -x[1]["total"])
        },
        "unmatched_invoice_count": len(result.get("unmatched_invoices", [])),
    }, default=str, indent=2)


@mcp.tool()
def get_cash_flow(period: str = "month") -> str:
    """Get complete cash flow from bank data — every dollar in and out, categorized.

    Args:
        period: Time period — "today", "week", "month", or "quarter".

    Returns:
        JSON with income and expense categories, totals, and net cash flow.
    """
    from bizops.parsers.reconciliation import ReconciliationEngine

    config = load_config()
    start, end = _resolve_dates(period)
    txns = load_bank_transactions(config, start, end)

    if not txns:
        return json.dumps({
            "period": {"start": start, "end": end},
            "message": "No bank data found. Run 'bizops bank import' first.",
        }, indent=2)

    engine = ReconciliationEngine(config)
    cash_flow = engine.get_cash_flow(txns)

    # Simplify for response — remove individual transactions
    income_summary = {
        k: {"total": round(v["total"], 2), "count": v["count"]}
        for k, v in cash_flow.get("income", {}).items()
    }
    expense_summary = {
        k: {"total": round(abs(v["total"]), 2), "count": v["count"]}
        for k, v in cash_flow.get("expenses", {}).items()
    }

    return json.dumps({
        "period": {"start": start, "end": end},
        "income": income_summary,
        "expenses": expense_summary,
        "total_income": round(cash_flow.get("total_income", 0), 2),
        "total_expenses": round(abs(cash_flow.get("total_expenses", 0)), 2),
        "net_cash_flow": round(cash_flow.get("net_cash_flow", 0), 2),
        "transaction_count": cash_flow.get("transaction_count", 0),
    }, default=str, indent=2)


@mcp.tool()
def get_food_cost(period: str = "month") -> str:
    """Get food cost percentage and category breakdown.

    Args:
        period: Time period — "today", "week", "month", or "quarter".

    Returns:
        JSON with food cost %, net sales, food expenses, per-category breakdown, and status.
    """
    from bizops.parsers.food_cost import FoodCostEngine

    config = load_config()
    start, end = _resolve_dates(period)
    year_month = start[:7]

    # Try loading saved food cost data
    fc_data = load_food_cost(config, year_month)
    if fc_data:
        return json.dumps({
            "period": {"start": start, "end": end},
            **fc_data,
        }, default=str, indent=2)

    # Calculate from expense + toast data
    expenses = load_expenses(config, year_month)
    toast = load_toast_reports(config, start, end)

    if not expenses and not toast:
        return json.dumps({
            "period": {"start": start, "end": end},
            "message": "No data found. Run 'bizops expenses track' first.",
        }, indent=2)

    engine = FoodCostEngine(config)
    fc_data = engine.calculate_food_cost(expenses or {}, toast)

    return json.dumps({
        "period": {"start": start, "end": end},
        **fc_data,
    }, default=str, indent=2)


@mcp.tool()
def get_food_cost_trend(months: int = 3) -> str:
    """Get month-over-month food cost trend.

    Args:
        months: Number of months to compare (default 3).

    Returns:
        JSON with monthly snapshots including food cost %, trend direction.
    """
    from bizops.parsers.food_cost import FoodCostEngine

    config = load_config()
    engine = FoodCostEngine(config)
    snapshots = engine.month_over_month(months)

    return json.dumps({
        "months_analyzed": months,
        "snapshots": snapshots,
    }, default=str, indent=2)


@mcp.tool()
def get_order_recommendation(vendor: str | None = None) -> str:
    """Get recommended purchase orders based on sales and par levels.

    Args:
        vendor: Specific vendor name, or None for all vendors.

    Returns:
        JSON with recommended orders, quantities, totals, and budget impact.
    """
    from bizops.parsers.ordering import OrderingEngine

    config = load_config()
    start, end = _resolve_dates("month")
    toast = load_toast_reports(config, start, end)

    engine = OrderingEngine(config)

    if vendor:
        order = engine.generate_order(vendor, toast)
        return json.dumps(order, default=str, indent=2)

    orders = engine.generate_all_orders(toast)
    if not orders:
        return json.dumps({
            "message": "No vendors have products with par levels. Use 'bizops orders add-product' to set up.",
        }, indent=2)

    return json.dumps({
        "order_count": len(orders),
        "grand_total": round(sum(o.get("order_total", 0) for o in orders), 2),
        "orders": orders,
    }, default=str, indent=2)


@mcp.tool()
def get_ordering_budget() -> str:
    """Get available budget for ordering based on sales projections.

    Returns:
        JSON with projected sales, food budget, spending to date, and remaining budget.
    """
    from bizops.parsers.ordering import OrderingEngine

    config = load_config()
    start, end = _resolve_dates("month")
    toast = load_toast_reports(config, start, end)

    engine = OrderingEngine(config)
    budget = engine.get_available_budget(toast)

    return json.dumps(budget, default=str, indent=2)


@mcp.tool()
def get_product_catalog(vendor: str | None = None) -> str:
    """Get product catalog for a vendor or all vendors.

    Args:
        vendor: Specific vendor name, or None for all vendors with products.

    Returns:
        JSON with vendor product catalogs.
    """
    config = load_config()

    if vendor:
        vendor_lower = vendor.lower()
        for vc in config.vendors:
            if vc.name.lower() == vendor_lower:
                return json.dumps({
                    "vendor": vc.name,
                    "products": [p.model_dump() for p in vc.products],
                    "product_count": len(vc.products),
                }, default=str, indent=2)
        return json.dumps({"error": f"Vendor '{vendor}' not found."}, indent=2)

    catalogs = []
    for vc in config.vendors:
        if vc.products:
            catalogs.append({
                "vendor": vc.name,
                "products": [p.model_dump() for p in vc.products],
                "product_count": len(vc.products),
            })

    return json.dumps({
        "vendor_count": len(catalogs),
        "catalogs": catalogs,
    }, default=str, indent=2)


@mcp.tool()
def get_daily_briefing(date: str | None = None) -> str:
    """Get a comprehensive daily business briefing — THE go-to tool for general business questions.

    Use this when the owner asks "how's my business?", "what should I know today?",
    "morning update", "daily briefing", or any general business status question.

    Returns yesterday's sales, cash position, labor cost, food cost,
    pending orders, unpaid invoices, and alerts — all in one response.

    Args:
        date: Specific date (YYYY-MM-DD). Defaults to yesterday.

    Returns:
        JSON with complete daily briefing including all key metrics and alerts.
    """
    from bizops.parsers.briefing import BriefingEngine
    from bizops.utils.storage import save_briefing

    config = load_config()
    engine = BriefingEngine(config)
    data = engine.generate_briefing(date)

    save_briefing(config, data, data["briefing_date"])

    return json.dumps(data, default=str, indent=2)


@mcp.tool()
def get_labor_cost(period: str = "month") -> str:
    """Get labor cost percentage, breakdown by source (ADP vs cash), and alerts.

    Args:
        period: Time period — "today", "week", "month", or "quarter".

    Returns:
        JSON with total labor, labor %, breakdown (ADP, cash, other), status, and alerts.
    """
    from bizops.parsers.labor import LaborEngine

    config = load_config()
    start, end = _resolve_dates(period)

    bank_txns = load_bank_transactions(config, start, end)
    toast = load_toast_reports(config, start, end)

    engine = LaborEngine(config)
    labor_data = engine.calculate_labor_cost(bank_txns, toast)
    alerts = engine.check_labor_alerts(labor_data)

    return json.dumps({
        "period": {"start": start, "end": end},
        **labor_data,
        "alerts": alerts,
    }, default=str, indent=2)


@mcp.tool()
def get_labor_trend(months: int = 3) -> str:
    """Get month-over-month labor cost trend.

    Args:
        months: Number of months to compare (default 3).

    Returns:
        JSON with monthly snapshots including labor cost %, trend direction.
    """
    from bizops.parsers.labor import LaborEngine

    config = load_config()
    engine = LaborEngine(config)
    snapshots = engine.get_labor_trend(months)

    return json.dumps({
        "months_analyzed": months,
        "snapshots": snapshots,
    }, default=str, indent=2)


@mcp.tool()
def get_payment_status(period: str = "month") -> str:
    """Get vendor payment status — who's paid, pending, and overdue.

    Use this when the owner asks about bills, payments, who they owe,
    what's overdue, or vendor payment history.

    Args:
        period: Time period — "month" or "quarter".

    Returns:
        JSON with per-vendor payment status, totals, and overdue amounts.
    """
    from bizops.parsers.payments import PaymentEngine

    config = load_config()
    start, end = _resolve_dates(period)

    invoices = load_invoices(config, start, end)
    bank_txns = load_bank_transactions(config, start, end)

    engine = PaymentEngine(config)
    result = engine.get_payment_status(invoices, bank_txns)

    return json.dumps(result, default=str, indent=2)


@mcp.tool()
def get_cash_forecast(days_ahead: int = 14) -> str:
    """Forecast cash position — can I afford upcoming payments?

    Projects balance forward based on upcoming vendor payments and
    estimated daily income from Toast POS.

    Args:
        days_ahead: Number of days to forecast (default 14).

    Returns:
        JSON with current balance, upcoming payments, projected income,
        end balance, and danger days (low cash warnings).
    """
    from bizops.parsers.payments import PaymentEngine

    config = load_config()
    start, end = _resolve_dates("month")

    invoices = load_invoices(config, start, end)
    bank_txns = load_bank_transactions(config, start, end)
    toast = load_toast_reports(config, start, end)

    engine = PaymentEngine(config)
    forecast = engine.get_cash_forecast(invoices, bank_txns, toast, days_ahead)

    return json.dumps(forecast, default=str, indent=2)


@mcp.tool()
def get_pl_trend(months: int = 6) -> str:
    """Get month-over-month Profit & Loss trend — revenue, expenses, profit margin.

    Use this when the owner asks "how are we trending?", "compare months",
    "revenue trend", "are we making more money?", or any P&L comparison question.

    Args:
        months: Number of months to analyze (default 6).

    Returns:
        JSON with monthly snapshots (revenue, expenses, profit, margin) and averages.
    """
    from bizops.parsers.trends import TrendEngine

    config = load_config()
    engine = TrendEngine(config)
    data = engine.get_pl_trend(months)

    return json.dumps(data, default=str, indent=2)


@mcp.tool()
def get_revenue_forecast(days: int = 30) -> str:
    """Forecast revenue based on historical Toast POS data and seasonal patterns.

    Use this when the owner asks "what will we make this month?", "revenue projection",
    "sales forecast", or any forward-looking revenue question.

    Args:
        days: Number of days to forecast (default 30).

    Returns:
        JSON with projected daily/weekly/total revenue, confidence level,
        and day-of-week sales patterns.
    """
    from bizops.parsers.trends import TrendEngine

    config = load_config()
    engine = TrendEngine(config)
    data = engine.get_revenue_forecast(days)

    return json.dumps(data, default=str, indent=2)


@mcp.tool()
def get_benchmarks() -> str:
    """Compare current business metrics against industry benchmarks.

    Use this when the owner asks "how am I doing?", "am I on track?",
    "industry comparison", "business health check", or wants a report card.

    Grades food cost %, labor %, prime cost %, rent %, and profit margin
    against small/casual restaurant industry averages.

    Returns:
        JSON with metric grades (A-D), current values, benchmark ranges,
        and overall business grade.
    """
    from bizops.parsers.trends import TrendEngine

    config = load_config()
    engine = TrendEngine(config)
    data = engine.get_benchmarks()

    return json.dumps(data, default=str, indent=2)


@mcp.tool()
def get_waste_estimate(period: str = "month") -> str:
    """Estimate food waste from the gap between purchases and theoretical usage.

    Use this when the owner asks "how much food are we wasting?", "waste report",
    "food shrinkage", or wants to reduce food costs. Also provides category breakdown.

    Industry benchmarks: under 4% = excellent, 4-7% = good, 7-10% = average, 10%+ = high.

    Args:
        period: Time period — "month" or "quarter".

    Returns:
        JSON with waste estimate, percentages, category breakdown, and status.
    """
    from bizops.parsers.waste import WasteEngine

    config = load_config()
    engine = WasteEngine(config)
    data = engine.estimate_waste_from_data(period)
    tips = engine.get_waste_reduction_tips(data)
    data["recommendations"] = tips

    return json.dumps(data, default=str, indent=2)


@mcp.tool()
def get_waste_trend(months: int = 6) -> str:
    """Track food waste estimates month-over-month.

    Args:
        months: Number of months to analyze (default 6).

    Returns:
        JSON with monthly waste %, dollars, and trend direction.
    """
    from bizops.parsers.waste import WasteEngine

    config = load_config()
    engine = WasteEngine(config)
    data = engine.get_waste_trend(months)

    return json.dumps(data, default=str, indent=2)


@mcp.tool()
def get_alerts(period: str = "month") -> str:
    """Scan all business data for anomalies and proactive warnings.

    Use this when the owner asks "anything I should worry about?", "any red flags?",
    "check for problems", or wants a health check on spending, sales, or operations.

    Checks: spending spikes by category, vendor cost jumps, sales anomalies,
    missed vendor orders, prime cost ratio (food+labor), and large transactions.

    Args:
        period: Time period — "month" or "quarter".

    Returns:
        JSON with alerts sorted by severity (critical first), each with type, message, and source.
    """
    from bizops.parsers.alerts import AlertEngine

    config = load_config()
    start, end = _resolve_dates(period)

    bank_txns = load_bank_transactions(config, start, end)
    toast = load_toast_reports(config, start, end)
    invoices = load_invoices(config, start, end)

    # Previous period for comparison
    from datetime import datetime as _dt
    s = _dt.strptime(start, "%Y-%m-%d")
    e = _dt.strptime(end, "%Y-%m-%d")
    duration = (e - s).days
    prev_end = s - timedelta(days=1)
    prev_start = prev_end - timedelta(days=duration)

    prev_bank = load_bank_transactions(config, prev_start.strftime("%Y-%m-%d"), prev_end.strftime("%Y-%m-%d"))
    prev_toast = load_toast_reports(config, prev_start.strftime("%Y-%m-%d"), prev_end.strftime("%Y-%m-%d"))

    engine = AlertEngine(config)
    alerts = engine.scan_all(bank_txns, toast, invoices, prev_bank, prev_toast)

    crit = sum(1 for a in alerts if a.get("severity") == "critical")
    warn = sum(1 for a in alerts if a.get("severity") == "warning")
    info = sum(1 for a in alerts if a.get("severity") == "info")

    return json.dumps({
        "period": {"start": start, "end": end},
        "alert_count": len(alerts),
        "summary": {"critical": crit, "warning": warn, "info": info},
        "alerts": alerts,
    }, default=str, indent=2)


# ──────────────────────────────────────────────────────────────
#  Resources
# ──────────────────────────────────────────────────────────────


@mcp.resource("bizops://config")
def get_config_resource() -> str:
    """Current BizOps configuration."""
    config = load_config()
    return json.dumps({
        "output_dir": str(config.output_dir),
        "gmail_credentials": str(config.gmail_credentials_path),
        "vendor_count": len(config.vendors),
        "vendors": [v.name for v in config.vendors],
        "expense_categories": [c.value for c in ExpenseCategory],
    }, indent=2)


@mcp.resource("bizops://status")
def get_status_resource() -> str:
    """Current data availability status."""
    config = load_config()
    today = datetime.now()
    start = today.replace(day=1).strftime("%Y-%m-%d")
    end = today.strftime("%Y-%m-%d")
    year_month = start[:7]

    invoices = load_invoices(config, start, end)
    toast = load_toast_reports(config, start, end)
    expenses = load_expenses(config, year_month)

    bank_txns = load_bank_transactions(config, start, end)
    reconciliation = load_reconciliation(config, year_month)

    return json.dumps({
        "current_month": year_month,
        "invoices_count": len(invoices),
        "toast_reports_count": len(toast),
        "has_expense_data": bool(expenses),
        "bank_transactions_count": len(bank_txns),
        "has_reconciliation_data": bool(reconciliation),
        "data_directory": str(config.output_dir / "data"),
    }, indent=2)


# ──────────────────────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────────────────────


def _top_vendors(items: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    """Get the top vendors by spend from a list of invoice items."""
    vendor_totals: dict[str, float] = defaultdict(float)
    for item in items:
        v = item.get("vendor", "Unknown")
        vendor_totals[v] += float(item.get("amount") or 0)

    return [
        {"vendor": v, "total": round(t, 2)}
        for v, t in sorted(vendor_totals.items(), key=lambda x: x[1], reverse=True)[:limit]
    ]


# ──────────────────────────────────────────────────────────────
#  Entry point
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
