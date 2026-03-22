"""Rich display helpers for consistent CLI output."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

console = Console()


def print_success(message: str) -> None:
    """Print a success message."""
    console.print(f"[bold green]✓[/bold green] {message}")


def print_error(message: str) -> None:
    """Print an error message."""
    console.print(f"[bold red]✗[/bold red] {message}")


def print_warning(message: str) -> None:
    """Print a warning message."""
    console.print(f"[bold yellow]⚠[/bold yellow] {message}")


def print_info(message: str) -> None:
    """Print an info message."""
    console.print(f"[bold blue]ℹ[/bold blue] {message}")


def create_invoice_table(invoices: list[dict[str, Any]], title: str = "Invoices") -> Table:
    """Create a Rich table for invoice display."""
    table = Table(title=title, show_header=True, header_style="bold cyan")
    table.add_column("#", style="dim", width=4)
    table.add_column("Date", style="green", width=12)
    table.add_column("Vendor", style="cyan", width=20)
    table.add_column("Amount", justify="right", style="bold", width=12)
    table.add_column("Status", width=10)
    table.add_column("Category", style="dim", width=15)

    for i, inv in enumerate(invoices, 1):
        status = inv.get("status", "unknown")
        status_style = {
            "paid": "[green]Paid[/green]",
            "unpaid": "[red]Unpaid[/red]",
            "partial": "[yellow]Partial[/yellow]",
            "unknown": "[dim]Unknown[/dim]",
        }.get(status, f"[dim]{status}[/dim]")

        amount = inv.get("amount")
        amount_str = f"${amount:,.2f}" if isinstance(amount, (int, float, Decimal)) else str(amount or "—")

        table.add_row(
            str(i),
            inv.get("date", "—"),
            inv.get("vendor", "Unknown"),
            amount_str,
            status_style,
            inv.get("category", "—"),
        )

    return table


def create_summary_panel(
    title: str,
    stats: dict[str, str | int | float],
) -> Panel:
    """Create a summary panel with key stats."""
    lines = []
    for key, value in stats.items():
        if isinstance(value, float):
            lines.append(f"[cyan]{key}:[/cyan] [bold]${value:,.2f}[/bold]")
        else:
            lines.append(f"[cyan]{key}:[/cyan] [bold]{value}[/bold]")

    content = "\n".join(lines)
    return Panel(content, title=f"[bold]{title}[/bold]", border_style="green")


def create_expense_table(
    expenses: list[dict[str, Any]],
    title: str = "Expenses by Category",
) -> Table:
    """Create a Rich table for categorized expense display."""
    table = Table(title=title, show_header=True, header_style="bold red")
    table.add_column("#", style="dim", width=4)
    table.add_column("Date", style="green", width=12)
    table.add_column("Vendor", style="cyan", width=22)
    table.add_column("Amount", justify="right", style="bold", width=12)
    table.add_column("Category", width=16)
    table.add_column("Subject", style="dim", width=40)

    for i, exp in enumerate(expenses, 1):
        amount = exp.get("amount")
        amount_str = f"${amount:,.2f}" if isinstance(amount, (int, float, Decimal)) else str(amount or "—")
        table.add_row(
            str(i),
            exp.get("date", "—"),
            exp.get("vendor", "Unknown"),
            amount_str,
            exp.get("expense_category", exp.get("category", "—")),
            (exp.get("subject") or "")[:40],
        )

    return table


def create_pl_panel(pl_data: dict[str, Any]) -> Panel:
    """Create a Rich panel showing P&L summary."""
    revenue = pl_data.get("revenue", {})
    totals = pl_data.get("totals", {})
    expenses_by_cat = pl_data.get("expenses_by_category", {})

    lines = []
    # Revenue
    lines.append("[bold green]── REVENUE ──[/bold green]")
    gross = revenue.get("gross_sales", 0) or 0
    net = revenue.get("net_sales", 0) or 0
    tax = revenue.get("tax", 0) or 0
    tips = revenue.get("tips", 0) or 0
    lines.append(f"  Gross Sales:    [bold]${gross:>12,.2f}[/bold]")
    lines.append(f"  Net Sales:      [bold]${net:>12,.2f}[/bold]")
    lines.append(f"  Tax Collected:  [bold]${tax:>12,.2f}[/bold]")
    lines.append(f"  Tips:           [bold]${tips:>12,.2f}[/bold]")
    lines.append("")

    # Expenses
    lines.append("[bold red]── EXPENSES ──[/bold red]")
    total_expenses = 0
    for cat, items in sorted(expenses_by_cat.items()):
        cat_total = sum(i.get("amount") or 0 for i in items)
        if cat_total > 0:
            total_expenses += cat_total
            label = cat.replace("_", " ").title()
            lines.append(f"  {label:<18} [bold]${cat_total:>12,.2f}[/bold]  ({len(items)} items)")
    lines.append(f"  {'─' * 34}")
    lines.append(f"  {'Total Expenses':<18} [bold red]${total_expenses:>12,.2f}[/bold red]")
    lines.append("")

    # Net Profit
    net_profit = totals.get("net_profit", 0) or 0
    profit_color = "green" if net_profit >= 0 else "red"
    lines.append(f"[bold {profit_color}]── NET PROFIT: ${net_profit:>12,.2f} ──[/bold {profit_color}]")

    content = "\n".join(lines)
    period = pl_data.get("period", {})
    period_str = f"{period.get('start', '?')} to {period.get('end', '?')}"
    return Panel(content, title=f"[bold]P&L Summary ({period_str})[/bold]", border_style="green")


def create_bank_txn_table(
    transactions: list[dict[str, Any]],
    title: str = "Bank Transactions",
) -> Table:
    """Create a Rich table for bank transaction display."""
    table = Table(title=title, show_header=True, header_style="bold blue")
    table.add_column("#", style="dim", width=4)
    table.add_column("Date", style="green", width=12)
    table.add_column("Description", style="cyan", width=35)
    table.add_column("Amount", justify="right", width=12)
    table.add_column("Type", width=8)
    table.add_column("Category", style="dim", width=15)
    table.add_column("Matched", width=8)

    for i, txn in enumerate(transactions, 1):
        amount = txn.get("amount", 0)
        amount_color = "green" if amount > 0 else "red"
        amount_str = f"[{amount_color}]${abs(amount):,.2f}[/{amount_color}]"

        txn_type = txn.get("type", "")
        type_style = "[green]Credit[/green]" if txn_type == "credit" else "[red]Debit[/red]"

        reconciled = txn.get("reconciled", False)
        match_icon = "[green]Y[/green]" if reconciled else "[dim]-[/dim]"

        cat = (txn.get("category") or "uncategorized").replace("_", " ").title()

        table.add_row(
            str(i),
            txn.get("date", "-"),
            (txn.get("description") or "")[:35],
            amount_str,
            type_style,
            cat,
            match_icon,
        )

    return table


def create_reconciliation_panel(result: dict[str, Any]) -> Panel:
    """Create a Rich panel showing reconciliation summary."""
    summary = result.get("summary", {})
    lines = []
    lines.append("[bold blue]-- RECONCILIATION SUMMARY --[/bold blue]")
    lines.append(f"  Bank Transactions:  [bold]{summary.get('total_bank_txns', 0):>6}[/bold]")
    lines.append(f"  Invoices:           [bold]{summary.get('total_invoices', 0):>6}[/bold]")
    lines.append(f"  Matched:            [bold green]{summary.get('matched_count', 0):>6}[/bold green]")
    lines.append(f"  Match Rate:         [bold]{summary.get('match_rate', 0):>5.1f}%[/bold]")
    lines.append("")
    lines.append(f"  Unmatched Bank:     [bold yellow]{summary.get('unmatched_bank_count', 0):>6}[/bold yellow]")
    lines.append(f"  Unmatched Invoices: [bold yellow]{summary.get('unmatched_invoice_count', 0):>6}[/bold yellow]")
    lines.append("")

    debits = summary.get("total_bank_debits", 0)
    credits = summary.get("total_bank_credits", 0)
    net = summary.get("net_bank_flow", 0)
    net_color = "green" if net >= 0 else "red"

    lines.append(f"  Total Debits:       [bold red]${abs(debits):>12,.2f}[/bold red]")
    lines.append(f"  Total Credits:      [bold green]${credits:>12,.2f}[/bold green]")
    lines.append(f"  Net Flow:           [bold {net_color}]${net:>12,.2f}[/bold {net_color}]")

    return Panel("\n".join(lines), title="[bold]Reconciliation[/bold]", border_style="blue")


def create_cash_flow_table(cash_flow: dict[str, Any]) -> Panel:
    """Create a Rich panel showing complete cash flow breakdown."""
    lines = []

    # Income
    lines.append("[bold green]-- MONEY IN --[/bold green]")
    income = cash_flow.get("income", {})
    if income:
        for cat, data in sorted(income.items(), key=lambda x: x[1]["total"], reverse=True):
            label = cat.replace("_", " ").title()
            lines.append(f"  {label:<20} [bold green]${data['total']:>12,.2f}[/bold green]  ({data['count']} txns)")
    else:
        lines.append("  [dim]No credits found[/dim]")
    total_in = cash_flow.get("total_income", 0)
    lines.append(f"  {'─' * 38}")
    lines.append(f"  {'Total In':<20} [bold green]${total_in:>12,.2f}[/bold green]")
    lines.append("")

    # Expenses
    lines.append("[bold red]-- MONEY OUT --[/bold red]")
    expenses = cash_flow.get("expenses", {})
    if expenses:
        for cat, data in sorted(expenses.items(), key=lambda x: x[1]["total"]):
            label = cat.replace("_", " ").title()
            lines.append(f"  {label:<20} [bold red]${abs(data['total']):>12,.2f}[/bold red]  ({data['count']} txns)")
    else:
        lines.append("  [dim]No debits found[/dim]")
    total_out = cash_flow.get("total_expenses", 0)
    lines.append(f"  {'─' * 38}")
    lines.append(f"  {'Total Out':<20} [bold red]${abs(total_out):>12,.2f}[/bold red]")
    lines.append("")

    # Net
    net = cash_flow.get("net_cash_flow", 0)
    net_color = "green" if net >= 0 else "red"
    lines.append(f"[bold {net_color}]-- NET CASH FLOW: ${net:>12,.2f} --[/bold {net_color}]")

    return Panel("\n".join(lines), title="[bold]Complete Cash Flow (Bank)[/bold]", border_style="blue")


def create_food_cost_panel(data: dict[str, Any]) -> Panel:
    """Create a Rich panel showing food cost % with color coding."""
    pct = data.get("food_cost_pct", 0)
    status = data.get("status", "healthy")
    color = {"healthy": "green", "warning": "yellow", "critical": "red"}.get(status, "white")

    lines = []
    lines.append(f"[bold {color}]Food Cost: {pct}%[/bold {color}]")
    lines.append(f"  Target: {data.get('target_pct', 30)}%  |  Alert: {data.get('alert_threshold_pct', 35)}%")
    lines.append("")
    lines.append(f"  Net Sales:       [bold]${data.get('net_sales', 0):>12,.2f}[/bold]")
    lines.append(f"  Food Expenses:   [bold {color}]${data.get('food_cost_total', 0):>12,.2f}[/bold {color}]")
    lines.append("")

    by_cat = data.get("by_category", {})
    if by_cat:
        lines.append("[dim]  Breakdown:[/dim]")
        for cat, info in sorted(by_cat.items(), key=lambda x: x[1].get("total", 0), reverse=True):
            if info.get("total", 0) > 0:
                label = cat.replace("_", " ").title()
                lines.append(
                    f"    {label:<18} ${info['total']:>10,.2f}  ({info.get('pct', 0)}%)"
                )

    return Panel("\n".join(lines), title="[bold]Food Cost Analysis[/bold]", border_style=color)


def create_food_cost_trend_table(snapshots: list[dict[str, Any]]) -> Table:
    """Create a Rich table for month-over-month food cost trends."""
    table = Table(title="Food Cost Trend", show_header=True, header_style="bold cyan")
    table.add_column("Month", style="cyan", width=10)
    table.add_column("Net Sales", justify="right", width=14)
    table.add_column("Food Cost", justify="right", width=14)
    table.add_column("Food Cost %", justify="right", width=12)
    table.add_column("Trend", width=8)
    table.add_column("Status", width=10)

    arrows = {"up": "[red]^[/red]", "down": "[green]v[/green]", "flat": "[dim]-[/dim]"}
    status_styles = {
        "healthy": "[green]OK[/green]",
        "warning": "[yellow]WARN[/yellow]",
        "critical": "[red]HIGH[/red]",
        "no_data": "[dim]--[/dim]",
    }

    for snap in snapshots:
        table.add_row(
            snap["month"],
            f"${snap['net_sales']:,.2f}" if snap["net_sales"] else "--",
            f"${snap['food_cost_total']:,.2f}" if snap["food_cost_total"] else "--",
            f"{snap['food_cost_pct']}%" if snap["food_cost_pct"] else "--",
            arrows.get(snap.get("trend", "flat"), "-"),
            status_styles.get(snap.get("status", "no_data"), "--"),
        )

    return table


def create_order_table(order: dict[str, Any]) -> Table:
    """Create a Rich table for a purchase order."""
    vendor = order.get("vendor", "Unknown")
    table = Table(
        title=f"Purchase Order — {vendor}",
        show_header=True,
        header_style="bold green",
    )
    table.add_column("#", style="dim", width=4)
    table.add_column("Product", style="cyan", width=25)
    table.add_column("Qty", justify="right", width=8)
    table.add_column("Unit", width=8)
    table.add_column("Unit Cost", justify="right", width=10)
    table.add_column("Line Total", justify="right", width=12)

    for i, item in enumerate(order.get("items", []), 1):
        table.add_row(
            str(i),
            item.get("product_name", ""),
            f"{item.get('quantity', 0):g}",
            item.get("unit", ""),
            f"${item.get('unit_cost', 0):,.2f}",
            f"${item.get('line_total', 0):,.2f}",
        )

    # Footer row
    table.add_row("", "", "", "", "[bold]TOTAL:", f"[bold]${order.get('order_total', 0):,.2f}[/bold]")

    return table


def create_product_catalog_table(vendor_name: str, products: list[Any]) -> Table:
    """Create a Rich table for a vendor's product catalog."""
    table = Table(
        title=f"Product Catalog — {vendor_name}",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("#", style="dim", width=4)
    table.add_column("Product", style="cyan", width=25)
    table.add_column("Unit", width=8)
    table.add_column("Cost", justify="right", width=10)
    table.add_column("Par Level", justify="right", width=10)
    table.add_column("Order Multiple", justify="right", width=14)
    table.add_column("Category", style="dim", width=14)

    for i, p in enumerate(products, 1):
        name = p.name if hasattr(p, "name") else p.get("name", "")
        unit = p.unit if hasattr(p, "unit") else p.get("unit", "")
        cost = p.unit_cost if hasattr(p, "unit_cost") else p.get("unit_cost", 0)
        par = p.par_level if hasattr(p, "par_level") else p.get("par_level", 0)
        mult = p.order_multiple if hasattr(p, "order_multiple") else p.get("order_multiple", 1)
        cat = p.category if hasattr(p, "category") else p.get("category", "")

        table.add_row(
            str(i),
            name,
            unit,
            f"${cost:,.2f}",
            f"{par:g}",
            f"{mult:g}",
            cat.replace("_", " ").title(),
        )

    return table


def create_budget_panel(budget: dict[str, Any]) -> Panel:
    """Create a Rich panel showing available ordering budget."""
    lines = []
    lines.append("[bold green]-- ORDERING BUDGET --[/bold green]")
    lines.append(f"  Avg Daily Sales:       [bold]${budget.get('avg_daily_sales', 0):>10,.2f}[/bold]")
    lines.append(f"  Projected Monthly:     [bold]${budget.get('projected_monthly_sales', 0):>10,.2f}[/bold]")
    lines.append(f"  Food Cost Target:      [bold]{budget.get('target_pct', 30)}%[/bold]")
    lines.append(f"  Food Budget:           [bold]${budget.get('food_budget', 0):>10,.2f}[/bold]")
    lines.append("")
    lines.append(f"  Already Spent:         [bold red]${budget.get('already_spent', 0):>10,.2f}[/bold red]")
    lines.append(f"  [bold]Budget Remaining:    [green]${budget.get('budget_remaining', 0):>10,.2f}[/green][/bold]")
    lines.append("")
    day = budget.get("day_of_month", 1)
    days = budget.get("days_in_month", 30)
    pct_through = round(day / days * 100) if days else 0
    lines.append(f"  Day {day} of {days} ({pct_through}% through month)")

    return Panel("\n".join(lines), title="[bold]Ordering Budget[/bold]", border_style="green")


def create_labor_panel(data: dict[str, Any]) -> Panel:
    """Create a Rich panel showing labor cost % with color coding and breakdown."""
    pct = data.get("labor_pct", 0)
    status = data.get("status", "healthy")
    color = {"healthy": "green", "warning": "yellow", "critical": "red"}.get(status, "white")

    lines = []
    lines.append(f"[bold {color}]Labor Cost: {pct}%[/bold {color}]")
    lines.append(f"  Target: {data.get('target_pct', 30)}%  |  Alert: {data.get('alert_threshold_pct', 35)}%")
    lines.append("")
    lines.append(f"  Net Sales:       [bold]${data.get('net_sales', 0):>12,.2f}[/bold]")
    lines.append(f"  Total Labor:     [bold {color}]${data.get('total_labor', 0):>12,.2f}[/bold {color}]")
    lines.append("")

    breakdown = data.get("breakdown", {})
    if breakdown:
        lines.append("[dim]  Breakdown:[/dim]")
        adp = breakdown.get("adp", {})
        cash = breakdown.get("cash_payments", {})
        other = breakdown.get("other", {})
        if adp.get("total", 0) > 0:
            lines.append(f"    ADP Payroll       ${adp['total']:>10,.2f}  ({adp.get('count', 0)} txns)")
        if cash.get("total", 0) > 0:
            lines.append(f"    Cash/Zelle        ${cash['total']:>10,.2f}  ({cash.get('count', 0)} txns)")
        if other.get("total", 0) > 0:
            lines.append(f"    Other Payroll     ${other['total']:>10,.2f}  ({other.get('count', 0)} txns)")

    return Panel("\n".join(lines), title="[bold]Labor Cost Analysis[/bold]", border_style=color)


def create_labor_trend_table(snapshots: list[dict[str, Any]]) -> Table:
    """Create a Rich table for month-over-month labor cost trends."""
    table = Table(title="Labor Cost Trend", show_header=True, header_style="bold cyan")
    table.add_column("Month", style="cyan", width=10)
    table.add_column("Net Sales", justify="right", width=14)
    table.add_column("Labor Cost", justify="right", width=14)
    table.add_column("Labor %", justify="right", width=10)
    table.add_column("Trend", width=8)
    table.add_column("Status", width=10)

    arrows = {"up": "[red]^[/red]", "down": "[green]v[/green]", "flat": "[dim]-[/dim]"}
    status_styles = {
        "healthy": "[green]OK[/green]",
        "warning": "[yellow]WARN[/yellow]",
        "critical": "[red]HIGH[/red]",
        "no_data": "[dim]--[/dim]",
    }

    for snap in snapshots:
        table.add_row(
            snap["month"],
            f"${snap['net_sales']:,.2f}" if snap["net_sales"] else "--",
            f"${snap['total_labor']:,.2f}" if snap["total_labor"] else "--",
            f"{snap['labor_pct']}%" if snap["labor_pct"] else "--",
            arrows.get(snap.get("trend", "flat"), "-"),
            status_styles.get(snap.get("status", "no_data"), "--"),
        )

    return table


def create_briefing_panel(data: dict[str, Any]) -> Panel:
    """Create a Rich panel showing the daily owner briefing."""
    sections = data.get("sections", {})
    briefing_date = data.get("briefing_date", "Unknown")
    lines = []

    # Sales section
    sales = sections.get("sales", {})
    lines.append("[bold green]-- YESTERDAY'S SALES --[/bold green]")
    net = sales.get("net_sales", 0)
    gross = sales.get("gross_sales", 0)
    tips = sales.get("tips", 0)
    lines.append(f"  Gross: [bold]${gross:>10,.2f}[/bold]  |  Net: [bold]${net:>10,.2f}[/bold]  |  Tips: [bold]${tips:>8,.2f}[/bold]")
    vs = sales.get("vs_last_week")
    if vs and vs.get("pct_change") is not None:
        pct = vs["pct_change"]
        arrow = "^" if pct > 0 else "v" if pct < 0 else "-"
        color = "green" if pct > 0 else "red" if pct < 0 else "dim"
        lines.append(f"  vs Last Week: [{color}]{arrow} {abs(pct):.1f}%[/{color}]")
    lines.append("")

    # Cash position
    cash = sections.get("cash_position", {})
    lines.append("[bold blue]-- CASH POSITION --[/bold blue]")
    balance = cash.get("estimated_balance", 0)
    balance_color = "green" if balance > 0 else "red"
    lines.append(f"  Est. Balance: [bold {balance_color}]${balance:>12,.2f}[/bold {balance_color}]")
    lines.append(f"  MTD In:  [green]${cash.get('mtd_credits', 0):>10,.2f}[/green]  |  MTD Out: [red]${abs(cash.get('mtd_debits', 0)):>10,.2f}[/red]")
    lines.append("")

    # Labor & Food Cost side by side
    labor = sections.get("labor", {})
    food = sections.get("food_cost", {})
    labor_pct = labor.get("labor_pct", 0)
    labor_status = labor.get("status", "no_data")
    food_pct = food.get("food_cost_pct", 0)
    food_status = food.get("status", "no_data")

    labor_color = {"healthy": "green", "warning": "yellow", "critical": "red"}.get(labor_status, "dim")
    food_color = {"healthy": "green", "warning": "yellow", "critical": "red"}.get(food_status, "dim")

    lines.append("[bold cyan]-- KEY METRICS --[/bold cyan]")
    lines.append(f"  Labor: [{labor_color}]{labor_pct}%[/{labor_color}]  |  Food: [{food_color}]{food_pct}%[/{food_color}]")
    if labor.get("breakdown"):
        bd = labor["breakdown"]
        parts = []
        if bd.get("adp", 0):
            parts.append(f"ADP ${bd['adp']:,.0f}")
        if bd.get("cash", 0):
            parts.append(f"Cash ${bd['cash']:,.0f}")
        if parts:
            lines.append(f"  Labor breakdown: {' | '.join(parts)}")
    lines.append("")

    # Orders due
    orders = sections.get("orders_due", {})
    today_orders = orders.get("today", [])
    tomorrow_orders = orders.get("tomorrow", [])
    if today_orders or tomorrow_orders:
        lines.append("[bold yellow]-- ORDERS DUE --[/bold yellow]")
        for o in today_orders:
            lines.append(f"  [bold]TODAY:[/bold] {o['vendor']} — {o.get('product_count', 0)} items ~${o.get('est_total', 0):,.0f}")
        for o in tomorrow_orders:
            lines.append(f"  Tomorrow: {o['vendor']} — {o.get('product_count', 0)} items ~${o.get('est_total', 0):,.0f}")
        lines.append("")

    # Invoices
    inv = sections.get("invoices", {})
    unpaid = inv.get("unpaid_count", 0)
    overdue = inv.get("overdue_count", 0)
    if unpaid > 0 or overdue > 0:
        lines.append("[bold magenta]-- INVOICES --[/bold magenta]")
        if unpaid:
            lines.append(f"  {unpaid} unpaid (${inv.get('total_outstanding', 0):,.2f})")
        if overdue:
            lines.append(f"  [red]{overdue} overdue (${inv.get('overdue_amount', 0):,.2f})[/red]")
        lines.append("")

    # Alerts
    alert_list = sections.get("alerts", [])
    if alert_list:
        lines.append("[bold red]-- ALERTS --[/bold red]")
        for a in alert_list:
            severity = a.get("severity", "low")
            icon = {"high": "[red]!![/red]", "medium": "[yellow]![/yellow]", "low": "[dim]i[/dim]"}.get(severity, "")
            lines.append(f"  {icon} {a.get('message', '')}")

    return Panel(
        "\n".join(lines),
        title=f"[bold]Daily Briefing — {briefing_date}[/bold]",
        border_style="green",
    )


def get_spinner() -> Progress:
    """Get a consistent spinner for async operations."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
    )
