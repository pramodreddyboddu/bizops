"""Vendor price intelligence CLI commands."""

from __future__ import annotations

from enum import StrEnum

import typer
from rich.console import Console

from bizops.utils.config import load_config
from bizops.utils.display import (
    create_negotiation_panel,
    create_vendor_spending_table,
    get_spinner,
    print_info,
)

console = Console()
app = typer.Typer(no_args_is_help=True)


class TimeRange(StrEnum):
    month = "month"
    quarter = "quarter"


def _resolve_dates(period: TimeRange) -> tuple[str, str]:
    from datetime import datetime
    today = datetime.now()
    if period == TimeRange.quarter:
        q_start_month = ((today.month - 1) // 3) * 3 + 1
        start = today.replace(month=q_start_month, day=1)
        return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
    else:
        start = today.replace(day=1)
        return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")


def _prev_dates(start: str, end: str) -> tuple[str, str]:
    from datetime import datetime, timedelta
    s = datetime.strptime(start, "%Y-%m-%d")
    e = datetime.strptime(end, "%Y-%m-%d")
    duration = (e - s).days
    prev_end = s - timedelta(days=1)
    prev_start = prev_end - timedelta(days=duration)
    return prev_start.strftime("%Y-%m-%d"), prev_end.strftime("%Y-%m-%d")


@app.command("spending")
def vendor_spending(
    period: TimeRange = typer.Option(TimeRange.month, "--period", "-p"),
) -> None:
    """Analyze spending by vendor — totals, averages, and price trends."""
    from bizops.parsers.vendor_prices import VendorPriceEngine
    from bizops.utils.storage import load_bank_transactions, load_invoices

    config = load_config()
    start, end = _resolve_dates(period)

    with get_spinner() as spinner:
        spinner.add_task("Analyzing vendor spending...", total=None)
        invoices = load_invoices(config, start, end)
        bank_txns = load_bank_transactions(config, start, end)
        engine = VendorPriceEngine(config)
        data = engine.get_vendor_spending(invoices, bank_txns)

    console.print(create_vendor_spending_table(data))

    if not data["vendors"]:
        print_info("No invoice data found for this period.")


@app.command("changes")
def price_changes(
    period: TimeRange = typer.Option(TimeRange.month, "--period", "-p"),
    threshold: float = typer.Option(10.0, "--threshold", "-t", help="% change to flag"),
) -> None:
    """Detect vendors with significant price changes vs prior period."""
    from rich.table import Table

    from bizops.parsers.vendor_prices import VendorPriceEngine
    from bizops.utils.storage import load_invoices

    config = load_config()
    start, end = _resolve_dates(period)
    prev_start, prev_end = _prev_dates(start, end)

    with get_spinner() as spinner:
        spinner.add_task("Detecting price changes...", total=None)
        current = load_invoices(config, start, end)
        prev = load_invoices(config, prev_start, prev_end)
        engine = VendorPriceEngine(config)
        changes = engine.detect_price_changes(current, prev, threshold)

    if not changes:
        print_info(f"No price changes above {threshold}% detected.")
        return

    table = Table(title="Price Changes Detected", show_header=True, header_style="bold yellow")
    table.add_column("Vendor", style="cyan", width=20)
    table.add_column("Previous Avg", justify="right", width=12)
    table.add_column("Current Avg", justify="right", width=12)
    table.add_column("Change", justify="right", width=10)
    table.add_column("Impact", width=10)

    for c in changes:
        color = "red" if c["direction"] == "up" else "green"
        arrow = "^" if c["direction"] == "up" else "v"
        table.add_row(
            c["vendor"],
            f"${c['previous_avg']:,.2f}",
            f"${c['current_avg']:,.2f}",
            f"[{color}]{arrow} {abs(c['pct_change'])}%[/{color}]",
            f"[{color}]{c['impact'].upper()}[/{color}]",
        )

    console.print(table)


@app.command("negotiate")
def negotiation_targets(
    period: TimeRange = typer.Option(TimeRange.month, "--period", "-p"),
) -> None:
    """Identify vendors where negotiation could save money."""
    from bizops.parsers.vendor_prices import VendorPriceEngine
    from bizops.utils.storage import load_invoices

    config = load_config()
    start, end = _resolve_dates(period)
    prev_start, prev_end = _prev_dates(start, end)

    with get_spinner() as spinner:
        spinner.add_task("Finding negotiation opportunities...", total=None)
        current = load_invoices(config, start, end)
        prev = load_invoices(config, prev_start, prev_end)
        engine = VendorPriceEngine(config)
        targets = engine.get_negotiation_targets(current, prev)

    console.print(create_negotiation_panel(targets))


@app.callback()
def main():
    """Vendor price intelligence — spending analysis, price changes, and negotiation targets."""
    pass
