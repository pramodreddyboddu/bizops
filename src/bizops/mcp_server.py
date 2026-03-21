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
from bizops.utils.storage import load_expenses, load_invoices, load_toast_reports

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

    return json.dumps({
        "current_month": year_month,
        "invoices_count": len(invoices),
        "toast_reports_count": len(toast),
        "has_expense_data": bool(expenses),
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
