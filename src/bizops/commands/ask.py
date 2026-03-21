"""AI-powered business questions and insights commands."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

import typer
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel

from bizops.utils.config import load_config
from bizops.utils.display import console, print_error, print_info, print_warning

app = typer.Typer(no_args_is_help=False, invoke_without_command=True)


class InsightPeriod(StrEnum):
    today = "today"
    week = "week"
    month = "month"
    quarter = "quarter"


# ──────────────────────────────────────────────────────────────
#  Data context builders
# ──────────────────────────────────────────────────────────────


def _resolve_date_range(period: InsightPeriod) -> tuple[str, str]:
    """Convert period enum to start/end date strings."""
    today = datetime.now()
    if period == InsightPeriod.today:
        d = today.strftime("%Y-%m-%d")
        return d, d
    elif period == InsightPeriod.week:
        start = today - timedelta(days=today.weekday())
        return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
    elif period == InsightPeriod.month:
        start = today.replace(day=1)
        return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
    elif period == InsightPeriod.quarter:
        q_start_month = ((today.month - 1) // 3) * 3 + 1
        start = today.replace(month=q_start_month, day=1)
        return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
    else:
        start = today.replace(day=1)
        return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")


def build_data_context(
    invoices: list[dict[str, Any]],
    expenses: dict[str, Any],
) -> str:
    """Build a text summary of available business data for the AI prompt.

    Args:
        invoices: List of invoice dicts from storage.
        expenses: Expense/P&L data dict from storage.

    Returns:
        A formatted string summarizing the data.
    """
    lines: list[str] = []

    # Invoice summary
    if invoices:
        lines.append(f"=== INVOICES ({len(invoices)} total) ===")

        # Date range
        dates = [inv.get("date", "") for inv in invoices if inv.get("date")]
        if dates:
            lines.append(f"Date range: {min(dates)} to {max(dates)}")

        # Totals per vendor
        vendor_totals: dict[str, float] = defaultdict(float)
        for inv in invoices:
            vendor = inv.get("vendor", "Unknown")
            amount = inv.get("amount") or 0
            vendor_totals[vendor] += float(amount)

        lines.append("\nTop vendors by spend:")
        for vendor, total in sorted(vendor_totals.items(), key=lambda x: x[1], reverse=True)[:10]:
            lines.append(f"  {vendor}: ${total:,.2f}")

        # Totals per category
        cat_totals: dict[str, float] = defaultdict(float)
        for inv in invoices:
            cat = inv.get("category", inv.get("expense_category", "uncategorized"))
            amount = inv.get("amount") or 0
            cat_totals[cat] += float(amount)

        if cat_totals:
            lines.append("\nSpend by category:")
            for cat, total in sorted(cat_totals.items(), key=lambda x: x[1], reverse=True):
                lines.append(f"  {cat.replace('_', ' ').title()}: ${total:,.2f}")
    else:
        lines.append("=== INVOICES: No invoice data available ===")

    # P&L / Expense summary
    if expenses:
        lines.append("\n=== P&L SUMMARY ===")
        revenue = expenses.get("revenue", {})
        totals = expenses.get("totals", {})

        if revenue:
            lines.append(f"Gross Sales: ${revenue.get('gross_sales', 0):,.2f}")
            lines.append(f"Net Sales: ${revenue.get('net_sales', 0):,.2f}")

        if totals:
            lines.append(f"Total Expenses: ${totals.get('total_expenses', 0):,.2f}")
            lines.append(f"Net Profit: ${totals.get('net_profit', 0):,.2f}")

        expenses_by_cat = expenses.get("expenses_by_category", {})
        if expenses_by_cat:
            lines.append("\nExpenses by category:")
            for cat, items in sorted(expenses_by_cat.items()):
                cat_total = sum(i.get("amount") or 0 for i in items)
                if cat_total > 0:
                    lines.append(
                        f"  {cat.replace('_', ' ').title()}: ${cat_total:,.2f} ({len(items)} items)"
                    )
    else:
        lines.append("\n=== P&L SUMMARY: No expense data available ===")

    return "\n".join(lines)


def build_system_prompt(config, data_context: str) -> str:
    """Build the system prompt with vendor info and data context.

    Args:
        config: BizOpsConfig instance.
        data_context: Pre-built data summary string.

    Returns:
        Complete system prompt for Claude.
    """
    # Vendor list
    vendor_lines = []
    for v in config.vendors:
        vendor_lines.append(f"  - {v.name} (category: {v.category})")
    vendor_section = "\n".join(vendor_lines) if vendor_lines else "  No vendors configured."

    # Category keywords
    keywords = config.category_keywords.model_dump()
    cat_lines = []
    for cat, kws in keywords.items():
        cat_lines.append(f"  {cat.replace('_', ' ').title()}: {', '.join(kws)}")
    cat_section = "\n".join(cat_lines)

    return f"""\
You are a business operations assistant for Desi Delight, an Indian restaurant.
You help the owner understand their finances, spot anomalies, and make better decisions.

Configured vendors:
{vendor_section}

Expense categories and keywords:
{cat_section}

Current business data:
{data_context}

Guidelines:
- Be concise and actionable.
- Use dollar amounts when referencing costs.
- If data is missing or incomplete, say so clearly.
- Format responses in markdown for readability.
"""


def _get_agent_client():
    """Create and return an AgentClient, handling errors gracefully."""
    from bizops.connectors.anthropic_client import AgentClient

    try:
        return AgentClient()
    except ValueError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except ImportError as e:
        print_error(str(e))
        raise typer.Exit(1)


def _load_current_data(period: InsightPeriod = InsightPeriod.month):
    """Load invoices and expenses for the given period.

    Returns:
        Tuple of (invoices, expenses, start_date, end_date).
    """
    config = load_config()
    start_date, end_date = _resolve_date_range(period)

    from bizops.utils.storage import load_expenses, load_invoices

    invoices = load_invoices(config, start_date, end_date)
    year_month = start_date[:7]
    expenses = load_expenses(config, year_month)

    return config, invoices, expenses, start_date, end_date


# ──────────────────────────────────────────────────────────────
#  Commands
# ──────────────────────────────────────────────────────────────


@app.callback(invoke_without_command=True)
def ask_question(
    ctx: typer.Context,
    question: str | None = typer.Argument(None, help="A natural language question about your business."),
):
    """
    Ask a natural language question about your business data.

    Examples:
        bizops ask "what did I spend on produce this month?"
        bizops ask "which vendor costs the most?"
    """
    # If a subcommand is being invoked, skip the callback logic
    if ctx.invoked_subcommand is not None:
        return

    if question is None:
        # No question and no subcommand — show help
        console.print(ctx.get_help())
        raise typer.Exit()

    config, invoices, expenses, start_date, end_date = _load_current_data()

    data_context = build_data_context(invoices, expenses)
    system_prompt = build_system_prompt(config, data_context)

    if not invoices and not expenses:
        print_warning("No business data found. Run 'bizops invoices pull' and 'bizops expenses track' first.")

    client = _get_agent_client()

    print_info(f"Asking about data from {start_date} to {end_date}...")

    # Stream the response with Rich Live display
    full_response = ""
    with Live(Markdown(""), console=console, refresh_per_second=8) as live:
        for chunk in client.stream_query(system_prompt, question):
            full_response += chunk
            live.update(Markdown(full_response))

    console.print()


@app.command("insights")
def insights(
    period: InsightPeriod = typer.Option(
        InsightPeriod.month,
        "--period", "-p",
        help="Time period: today, week, month, quarter.",
    ),
    category: str | None = typer.Option(
        None,
        "--category", "-c",
        help="Filter insights to a specific expense category.",
    ),
):
    """
    Get AI-powered insights about your business data.

    Analyzes spending patterns, anomalies, and opportunities.

    Examples:
        bizops ask insights --period month
        bizops ask insights --period quarter --category produce
    """
    config, invoices, expenses, start_date, end_date = _load_current_data(period)

    data_context = build_data_context(invoices, expenses)

    if not invoices and not expenses:
        print_warning("No business data found. Run 'bizops invoices pull' and 'bizops expenses track' first.")
        raise typer.Exit()

    category_filter = ""
    if category:
        category_filter = f"\nFocus specifically on the '{category}' expense category."

    insights_prompt = f"""\
Analyze the business data for Desi Delight restaurant and provide insights in these categories.
Use markdown formatting. For each section, provide 2-3 bullet points maximum.
{category_filter}

## Anomalies & Warnings
Identify any unusual charges, duplicate payments, or amounts significantly different from typical patterns.

## Spending Trends
Note vendor spend patterns, increasing/decreasing categories, and comparisons to expected ranges.

## Missing or Late Items
Flag any expected invoices that seem missing, or gaps in data coverage.

## Cost-Saving Opportunities
Suggest actionable ways to reduce costs based on the data patterns.
"""

    system_prompt = build_system_prompt(config, data_context)
    client = _get_agent_client()

    print_info(f"Analyzing {period.value} data ({start_date} to {end_date})...")

    # Collect the full response
    response = client.query(system_prompt, insights_prompt)

    # Parse sections and display in colored panels
    _display_insights(response)


def _display_insights(response: str) -> None:
    """Parse AI response into sections and display as colored Rich panels."""
    sections = _parse_insight_sections(response)

    # Color mapping for section types
    section_styles = {
        "anomalies": ("red", "Anomalies & Warnings"),
        "warnings": ("red", "Anomalies & Warnings"),
        "trends": ("yellow", "Spending Trends"),
        "spending": ("yellow", "Spending Trends"),
        "missing": ("yellow", "Missing or Late Items"),
        "late": ("yellow", "Missing or Late Items"),
        "opportunities": ("green", "Cost-Saving Opportunities"),
        "saving": ("green", "Cost-Saving Opportunities"),
        "cost": ("green", "Cost-Saving Opportunities"),
    }

    if not sections:
        # If parsing failed, display the full response as a single panel
        console.print(Panel(Markdown(response), title="[bold]Business Insights[/bold]", border_style="blue"))
        return

    for section_key, content in sections.items():
        # Determine color from section key
        color = "blue"
        title = section_key.replace("_", " ").title()
        key_lower = section_key.lower()

        for keyword, (style, label) in section_styles.items():
            if keyword in key_lower:
                color = style
                title = label
                break

        panel = Panel(
            Markdown(content.strip()),
            title=f"[bold]{title}[/bold]",
            border_style=color,
        )
        console.print(panel)
        console.print()


def _parse_insight_sections(response: str) -> dict[str, str]:
    """Parse markdown response into named sections based on ## headers."""
    sections: dict[str, str] = {}
    current_key = ""
    current_lines: list[str] = []

    for line in response.split("\n"):
        if line.startswith("## "):
            # Save previous section
            if current_key:
                sections[current_key] = "\n".join(current_lines)
            # Start new section
            current_key = line[3:].strip().lower().replace(" ", "_").replace("&", "and")
            current_lines = []
        else:
            current_lines.append(line)

    # Save last section
    if current_key:
        sections[current_key] = "\n".join(current_lines)

    return sections
