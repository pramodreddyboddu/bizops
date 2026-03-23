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


def create_payment_status_table(data: dict[str, Any]) -> Table:
    """Create a Rich table showing vendor payment status."""
    table = Table(title="Vendor Payment Status", show_header=True, header_style="bold blue")
    table.add_column("Vendor", style="cyan", width=20)
    table.add_column("Invoiced", justify="right", width=12)
    table.add_column("Paid", justify="right", width=12)
    table.add_column("Balance Due", justify="right", width=12)
    table.add_column("Overdue", justify="right", width=10)
    table.add_column("Terms", width=8)

    for v in data.get("vendors", []):
        overdue = v.get("overdue_count", 0)
        overdue_str = f"[red]{overdue}[/red]" if overdue > 0 else "[dim]0[/dim]"
        balance = v.get("balance_due", 0)
        balance_color = "red" if balance > 0 else "green"

        table.add_row(
            v.get("vendor", ""),
            f"${v.get('total_invoiced', 0):,.2f}",
            f"${v.get('total_paid', 0):,.2f}",
            f"[{balance_color}]${balance:,.2f}[/{balance_color}]",
            overdue_str,
            v.get("invoices", [{}])[0].get("payment_terms", "cod") if v.get("invoices") else "cod",
        )

    # Summary row
    summary = data.get("summary", {})
    table.add_row(
        "[bold]TOTAL[/bold]",
        f"[bold]${summary.get('total_invoiced', 0):,.2f}[/bold]",
        f"[bold]${summary.get('total_paid', 0):,.2f}[/bold]",
        f"[bold red]${summary.get('total_outstanding', 0):,.2f}[/bold red]",
        f"[bold red]${summary.get('total_overdue', 0):,.2f}[/bold red]",
        "",
    )

    return table


def create_payment_calendar_table(upcoming: list[dict[str, Any]]) -> Table:
    """Create a Rich table showing upcoming payment due dates."""
    table = Table(title="Payment Calendar", show_header=True, header_style="bold yellow")
    table.add_column("Due Date", style="cyan", width=12)
    table.add_column("Vendor", width=20)
    table.add_column("Amount", justify="right", width=12)
    table.add_column("Days", justify="right", width=6)
    table.add_column("Status", width=10)

    for p in upcoming:
        days = p.get("days_until_due", 0)
        if p.get("is_overdue"):
            status = f"[red]OVERDUE[/red]"
            days_str = f"[red]{days}d[/red]"
        elif days <= 3:
            status = "[yellow]SOON[/yellow]"
            days_str = f"[yellow]{days}d[/yellow]"
        else:
            status = "[green]OK[/green]"
            days_str = f"{days}d"

        table.add_row(
            p.get("due_date", ""),
            p.get("vendor", ""),
            f"${p.get('amount', 0):,.2f}",
            days_str,
            status,
        )

    return table


def create_cash_forecast_panel(forecast: dict[str, Any]) -> Panel:
    """Create a Rich panel showing cash flow forecast."""
    lines = []
    lines.append("[bold blue]-- CASH FLOW FORECAST --[/bold blue]")
    lines.append(f"  Current Balance:    [bold]${forecast.get('current_balance', 0):>12,.2f}[/bold]")
    lines.append(f"  Upcoming Payments:  [bold red]-${forecast.get('upcoming_payments', 0):>11,.2f}[/bold red]")
    lines.append(f"  Projected Income:   [bold green]+${forecast.get('projected_income', 0):>11,.2f}[/bold green]")
    lines.append(f"  {'─' * 38}")

    end_balance = forecast.get("projected_end_balance", 0)
    end_color = "green" if end_balance > 0 else "red"
    lines.append(f"  Projected Balance:  [bold {end_color}]${end_balance:>12,.2f}[/bold {end_color}]")
    lines.append("")
    lines.append(f"  Avg Daily Income:   ${forecast.get('avg_daily_income', 0):>12,.2f}")
    lines.append(f"  Forecast Period:    {forecast.get('days_forecast', 14)} days")

    danger = forecast.get("danger_days", [])
    if danger:
        lines.append("")
        lines.append(f"  [bold red]!! {len(danger)} day(s) with low balance (<$2,000)[/bold red]")
        for d in danger[:3]:
            lines.append(f"     {d['date']}: ${d['projected_balance']:,.2f}")

    return Panel(
        "\n".join(lines),
        title=f"[bold]Cash Forecast — {forecast.get('days_forecast', 14)} Days[/bold]",
        border_style="blue",
    )


def create_alerts_panel(alerts: list[dict[str, Any]]) -> Panel:
    """Create a Rich panel showing smart alerts sorted by severity."""
    if not alerts:
        return Panel(
            "[dim]No alerts — everything looks good.[/dim]",
            title="[bold]Smart Alerts[/bold]",
            border_style="green",
        )

    severity_icons = {
        "critical": "[bold red]!![/bold red]",
        "warning": "[yellow]![/yellow]",
        "info": "[dim]i[/dim]",
    }
    severity_colors = {
        "critical": "red",
        "warning": "yellow",
        "info": "dim",
    }

    lines = []
    current_severity = None
    for a in alerts:
        sev = a.get("severity", "info")
        if sev != current_severity:
            if current_severity is not None:
                lines.append("")
            label = sev.upper()
            color = severity_colors.get(sev, "white")
            lines.append(f"[bold {color}]-- {label} --[/bold {color}]")
            current_severity = sev

        icon = severity_icons.get(sev, "")
        source = a.get("source", "")
        source_tag = f" [dim]({source})[/dim]" if source else ""
        lines.append(f"  {icon} {a.get('message', '')}{source_tag}")

    # Summary line
    crit_count = sum(1 for a in alerts if a.get("severity") == "critical")
    warn_count = sum(1 for a in alerts if a.get("severity") == "warning")
    info_count = sum(1 for a in alerts if a.get("severity") == "info")
    lines.append("")
    lines.append(f"[dim]{len(alerts)} total: {crit_count} critical, {warn_count} warning, {info_count} info[/dim]")

    border = "red" if crit_count > 0 else "yellow" if warn_count > 0 else "green"
    return Panel("\n".join(lines), title="[bold]Smart Alerts[/bold]", border_style=border)


def create_budget_status_table(data: dict[str, Any]) -> Table:
    """Create a Rich table showing budget vs actual by category."""
    title = f"Budget Status — {data.get('month', '')} (Day {data.get('day_of_month', '?')}/{data.get('days_in_month', '?')})"
    table = Table(title=title, show_header=True, header_style="bold cyan")
    table.add_column("Category", style="cyan", width=16)
    table.add_column("Budget", justify="right", width=10)
    table.add_column("Actual", justify="right", width=10)
    table.add_column("Remaining", justify="right", width=10)
    table.add_column("Used %", justify="right", width=8)
    table.add_column("Projected", justify="right", width=10)
    table.add_column("Status", width=14)

    status_display = {
        "over_budget": "[bold red]OVER BUDGET[/bold red]",
        "warning": "[yellow]WARNING[/yellow]",
        "ahead_of_pace": "[yellow]FAST PACE[/yellow]",
        "on_track": "[green]ON TRACK[/green]",
        "no_budget": "[dim]NO BUDGET[/dim]",
    }

    for cat in data.get("categories", []):
        used_color = "red" if cat["used_pct"] > 100 else "yellow" if cat["used_pct"] > 80 else "green"
        table.add_row(
            cat["category"],
            f"${cat['budgeted']:,.0f}" if cat["budgeted"] > 0 else "--",
            f"${cat['actual']:,.0f}",
            f"${cat['remaining']:,.0f}" if cat["budgeted"] > 0 else "--",
            f"[{used_color}]{cat['used_pct']}%[/{used_color}]" if cat["budgeted"] > 0 else "--",
            f"${cat['projected_eom']:,.0f}",
            status_display.get(cat["status"], "--"),
        )

    # Summary row
    summary = data.get("summary", {})
    if summary.get("total_budgeted", 0) > 0:
        total_color = "red" if summary["total_used_pct"] > 100 else "yellow" if summary["total_used_pct"] > 80 else "green"
        table.add_section()
        table.add_row(
            "[bold]TOTAL[/bold]",
            f"[bold]${summary['total_budgeted']:,.0f}[/bold]",
            f"[bold]${summary['total_actual']:,.0f}[/bold]",
            f"[bold]${summary['total_remaining']:,.0f}[/bold]",
            f"[bold {total_color}]{summary['total_used_pct']}%[/bold {total_color}]",
            "",
            "",
        )

    return table


def create_health_score_panel(data: dict[str, Any]) -> Panel:
    """Create a Rich panel showing the business health score."""
    score = data.get("overall_score", 0)
    grade = data.get("grade", "F")

    grade_colors = {"A": "green", "B": "cyan", "C": "yellow", "D": "red", "F": "bold red"}
    color = grade_colors.get(grade, "white")

    lines = []
    lines.append(f"[bold {color}]  HEALTH SCORE: {score}/100 ({grade})[/bold {color}]")
    lines.append("")

    # Component scores
    components = data.get("components", {})
    for key in ["food_cost", "labor_cost", "profit_margin", "sales_trend", "cash_position", "payment_discipline"]:
        comp = components.get(key, {})
        if comp.get("status") == "no_data":
            bar = "[dim]no data[/dim]"
        else:
            comp_score = comp.get("score", 0)
            filled = int(comp_score / 5)
            empty = 20 - filled
            comp_color = "green" if comp_score >= 70 else "yellow" if comp_score >= 50 else "red"
            bar = f"[{comp_color}]{'█' * filled}{'░' * empty}[/{comp_color}] {comp_score:.0f}"

        label = key.replace("_", " ").title()
        detail = comp.get("detail", "")
        lines.append(f"  {label:<22} {bar}")
        if detail:
            lines.append(f"  {'':22} [dim]{detail}[/dim]")

    # Suggestions
    suggestions = data.get("suggestions", [])
    if suggestions:
        lines.append("")
        lines.append("[bold yellow]  TOP IMPROVEMENTS:[/bold yellow]")
        for s in suggestions:
            lines.append(f"    +{s['potential_points']:.0f}pts  {s['action']}")

    border = color.split()[-1]
    return Panel("\n".join(lines), title="[bold]Business Health Score[/bold]", border_style=border)


def create_vendor_spending_table(data: dict[str, Any]) -> Table:
    """Create a Rich table showing vendor spending analysis."""
    table = Table(title="Vendor Spending Analysis", show_header=True, header_style="bold cyan")
    table.add_column("#", style="dim", width=4)
    table.add_column("Vendor", style="cyan", width=20)
    table.add_column("Total Spend", justify="right", width=12)
    table.add_column("Invoices", justify="right", width=8)
    table.add_column("Avg/Invoice", justify="right", width=12)
    table.add_column("Range", justify="right", width=16)
    table.add_column("Trend", width=12)

    trend_display = {
        "increasing": "[red]^ UP[/red]",
        "decreasing": "[green]v DOWN[/green]",
        "stable": "[dim]- FLAT[/dim]",
        "insufficient_data": "[dim]--[/dim]",
    }

    for i, v in enumerate(data.get("vendors", []), 1):
        rng = f"${v['min_invoice']:,.0f}-${v['max_invoice']:,.0f}" if v["invoice_count"] > 1 else "--"
        table.add_row(
            str(i),
            v["vendor"],
            f"${v['total_spend']:,.2f}",
            str(v["invoice_count"]),
            f"${v['avg_per_invoice']:,.2f}",
            rng,
            trend_display.get(v.get("price_trend", ""), "--"),
        )

    return table


def create_negotiation_panel(targets: list[dict[str, Any]]) -> Panel:
    """Create a Rich panel showing negotiation targets."""
    if not targets:
        return Panel(
            "[dim]No negotiation opportunities detected.[/dim]",
            title="[bold]Negotiation Targets[/bold]",
            border_style="green",
        )

    priority_icons = {"high": "[red]!![/red]", "medium": "[yellow]![/yellow]", "low": "[dim]i[/dim]"}
    lines = []

    for t in targets:
        icon = priority_icons.get(t["priority"], "")
        lines.append(f"{icon} [bold]{t['vendor']}[/bold] (${t['total_spend']:,.0f} spend)")
        for reason in t.get("reasons", []):
            lines.append(f"    - {reason}")
        if t.get("est_monthly_savings", 0) > 0:
            lines.append(f"    [green]Est. savings: ${t['est_monthly_savings']:,.0f}/mo[/green]")
        lines.append("")

    total_savings = sum(t.get("est_monthly_savings", 0) for t in targets)
    if total_savings > 0:
        lines.append(f"[bold green]Total potential savings: ${total_savings:,.0f}/month[/bold green]")

    return Panel("\n".join(lines), title="[bold]Negotiation Targets[/bold]", border_style="yellow")


def create_waste_panel(data: dict[str, Any]) -> Panel:
    """Create a Rich panel showing waste estimation results."""
    waste_pct = data.get("waste_pct", 0)
    status = data.get("status", "no_data")
    status_colors = {
        "excellent": "green", "good": "cyan", "average": "yellow",
        "high": "red", "critical": "bold red", "no_data": "dim",
    }
    color = status_colors.get(status, "white")

    lines = []
    lines.append(f"[bold {color}]Estimated Waste: {waste_pct}% ({status.upper()})[/bold {color}]")
    lines.append("")
    lines.append(f"  Food Purchases:      [bold]${data.get('food_purchases', 0):>10,.2f}[/bold]")
    lines.append(f"  Theoretical Usage:   [bold]${data.get('theoretical_usage', 0):>10,.2f}[/bold]")
    lines.append(f"  [bold {color}]Estimated Waste:     ${data.get('estimated_waste', 0):>10,.2f}[/bold {color}]")
    lines.append("")
    lines.append(f"  Actual Food Cost:    {data.get('actual_food_cost_pct', 0)}%")
    lines.append(f"  Target Food Cost:    {data.get('target_food_cost_pct', 30)}%")

    breakdown = data.get("category_breakdown", {})
    if breakdown:
        lines.append("")
        lines.append("[dim]  Purchase Breakdown:[/dim]")
        for cat, total in sorted(breakdown.items(), key=lambda x: -x[1]):
            label = cat.replace("_", " ").title()
            lines.append(f"    {label:<18} ${total:>10,.2f}")

    return Panel("\n".join(lines), title="[bold]Waste Estimation[/bold]", border_style=color.split()[-1])


def create_waste_trend_table(data: dict[str, Any]) -> Table:
    """Create a Rich table for month-over-month waste trends."""
    table = Table(title="Waste Trend", show_header=True, header_style="bold cyan")
    table.add_column("Month", style="cyan", width=10)
    table.add_column("Waste %", justify="right", width=10)
    table.add_column("Waste $", justify="right", width=12)
    table.add_column("Purchases", justify="right", width=12)
    table.add_column("Trend", width=8)
    table.add_column("Status", width=10)

    arrows = {"up": "[red]^[/red]", "down": "[green]v[/green]", "flat": "[dim]-[/dim]"}
    status_styles = {
        "excellent": "[green]OK[/green]",
        "good": "[cyan]GOOD[/cyan]",
        "average": "[yellow]AVG[/yellow]",
        "high": "[red]HIGH[/red]",
        "critical": "[bold red]!!![/bold red]",
        "no_data": "[dim]--[/dim]",
    }

    for snap in data.get("snapshots", []):
        table.add_row(
            snap["month"],
            f"{snap['waste_pct']}%" if snap["waste_pct"] else "[dim]--[/dim]",
            f"${snap['waste_dollars']:,.0f}" if snap["waste_dollars"] else "[dim]--[/dim]",
            f"${snap['food_purchases']:,.0f}" if snap["food_purchases"] else "[dim]--[/dim]",
            arrows.get(snap.get("trend", "flat"), "-"),
            status_styles.get(snap.get("status", "no_data"), "--"),
        )

    return table


def create_pl_trend_table(data: dict[str, Any]) -> Table:
    """Create a Rich table for month-over-month P&L trends."""
    table = Table(title="P&L Trend", show_header=True, header_style="bold cyan")
    table.add_column("Month", style="cyan", width=10)
    table.add_column("Revenue", justify="right", width=12)
    table.add_column("Expenses", justify="right", width=12)
    table.add_column("Net Profit", justify="right", width=12)
    table.add_column("Margin", justify="right", width=8)
    table.add_column("Trend", width=8)

    arrows = {"up": "[green]^[/green]", "down": "[red]v[/red]", "flat": "[dim]-[/dim]"}

    for snap in data.get("snapshots", []):
        profit = snap.get("net_profit", 0)
        margin = snap.get("net_profit_pct", 0)
        profit_color = "green" if profit >= 0 else "red"

        table.add_row(
            snap["month"],
            f"${snap['net_sales']:,.0f}" if snap["net_sales"] else "[dim]--[/dim]",
            f"${snap['total_expenses']:,.0f}" if snap["total_expenses"] else "[dim]--[/dim]",
            f"[{profit_color}]${profit:,.0f}[/{profit_color}]" if snap["net_sales"] else "[dim]--[/dim]",
            f"{margin}%" if snap["net_sales"] else "[dim]--[/dim]",
            arrows.get(snap.get("profit_trend", "flat"), "-"),
        )

    # Averages row
    avgs = data.get("averages", {})
    if avgs.get("avg_monthly_revenue", 0):
        table.add_row(
            "[bold]AVG[/bold]",
            f"[bold]${avgs['avg_monthly_revenue']:,.0f}[/bold]",
            f"[bold]${avgs['avg_monthly_expenses']:,.0f}[/bold]",
            "",
            f"[bold]{avgs['avg_net_profit_pct']}%[/bold]",
            "",
        )

    return table


def create_benchmark_panel(data: dict[str, Any]) -> Panel:
    """Create a Rich panel showing business metrics vs industry benchmarks."""
    lines = []
    grade_colors = {"A": "green", "B": "cyan", "C": "yellow", "D": "red", "F": "red"}

    overall = data.get("overall_grade", "N/A")
    overall_color = grade_colors.get(overall, "white")
    lines.append(f"[bold {overall_color}]Overall Grade: {overall}[/bold {overall_color}]")
    lines.append(f"[dim]{data.get('benchmarks_source', '')}[/dim]")
    lines.append("")

    for m in data.get("metrics", []):
        grade = m.get("grade", "N/A")
        color = grade_colors.get(grade, "white")
        benchmark = m.get("benchmark", {})
        target = benchmark.get("target", 0)
        lines.append(
            f"  [{color}]{grade}[/{color}]  {m['name']:<16} "
            f"[bold]{m['value']}%[/bold]  "
            f"[dim](target: {target}%)[/dim]"
        )

    border = overall_color
    return Panel("\n".join(lines), title="[bold]Business Benchmarks[/bold]", border_style=border)


def create_forecast_panel(data: dict[str, Any]) -> Panel:
    """Create a Rich panel showing revenue forecast."""
    lines = []
    confidence = data.get("confidence", "no_data")
    conf_color = {"high": "green", "medium": "yellow", "low": "red", "no_data": "dim"}.get(confidence, "white")

    lines.append(f"[bold blue]-- REVENUE FORECAST --[/bold blue]")
    lines.append(f"  Projected Daily:   [bold]${data.get('projected_daily', 0):>10,.2f}[/bold]")
    lines.append(f"  Projected Weekly:  [bold]${data.get('projected_weekly', 0):>10,.2f}[/bold]")
    lines.append(f"  Projected Total:   [bold]${data.get('projected_total', 0):>10,.2f}[/bold] ({data.get('forecast_days', 0)} days)")
    lines.append(f"  Confidence:        [{conf_color}]{confidence.upper()}[/{conf_color}] ({data.get('data_days', 0)} days of data)")
    lines.append("")

    # Day of week pattern
    dow = data.get("day_of_week_pattern", {})
    if any(v > 0 for v in dow.values()):
        lines.append("[dim]  Day of Week Averages:[/dim]")
        best_day = max(dow, key=dow.get) if dow else ""
        for day, avg in dow.items():
            if avg > 0:
                marker = " [green]*[/green]" if day == best_day else ""
                lines.append(f"    {day:<10} ${avg:>8,.2f}{marker}")

    return Panel(
        "\n".join(lines),
        title=f"[bold]Revenue Forecast — {data.get('forecast_days', 30)} Days[/bold]",
        border_style="blue",
    )


def get_spinner() -> Progress:
    """Get a consistent spinner for async operations."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
    )
