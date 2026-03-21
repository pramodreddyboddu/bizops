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


def get_spinner() -> Progress:
    """Get a consistent spinner for async operations."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
    )
