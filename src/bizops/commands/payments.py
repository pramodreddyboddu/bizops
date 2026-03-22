"""Vendor payment tracking CLI commands."""

from __future__ import annotations

from enum import StrEnum

import typer
from rich.console import Console

from bizops.utils.config import load_config
from bizops.utils.display import (
    create_cash_forecast_panel,
    create_payment_calendar_table,
    create_payment_status_table,
    get_spinner,
    print_info,
    print_warning,
)

console = Console()
app = typer.Typer(no_args_is_help=True)


class TimeRange(StrEnum):
    month = "month"
    quarter = "quarter"


def _resolve_date_range(period: TimeRange) -> tuple[str, str]:
    """Convert time range to start/end date strings."""
    from datetime import datetime

    today = datetime.now()
    if period == TimeRange.quarter:
        q_start_month = ((today.month - 1) // 3) * 3 + 1
        start = today.replace(month=q_start_month, day=1)
        return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
    else:  # month
        start = today.replace(day=1)
        return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")


@app.command("status")
def payment_status(
    period: TimeRange = typer.Option(TimeRange.month, "--period", "-p"),
) -> None:
    """Show payment status for all vendors — who's paid, pending, overdue."""
    from bizops.parsers.payments import PaymentEngine
    from bizops.utils.storage import load_bank_transactions, load_invoices

    config = load_config()
    start, end = _resolve_date_range(period)

    with get_spinner() as spinner:
        spinner.add_task("Analyzing vendor payments...", total=None)
        invoices = load_invoices(config, start, end)
        bank_txns = load_bank_transactions(config, start, end)
        engine = PaymentEngine(config)
        result = engine.get_payment_status(invoices, bank_txns)

    console.print(create_payment_status_table(result))

    summary = result.get("summary", {})
    overdue = summary.get("total_overdue", 0)
    if overdue > 0:
        print_warning(f"${overdue:,.2f} overdue across {summary.get('overdue_vendor_count', 0)} vendor(s)")


@app.command("calendar")
def payment_calendar(
    days: int = typer.Option(14, "--days", "-d", help="Days ahead to show"),
) -> None:
    """Show upcoming payment due dates."""
    from bizops.parsers.payments import PaymentEngine
    from bizops.utils.storage import load_bank_transactions, load_invoices

    config = load_config()
    start, _ = _resolve_date_range(TimeRange.month)
    from datetime import datetime
    end = datetime.now().strftime("%Y-%m-%d")

    with get_spinner() as spinner:
        spinner.add_task("Building payment calendar...", total=None)
        invoices = load_invoices(config, start, end)
        bank_txns = load_bank_transactions(config, start, end)
        engine = PaymentEngine(config)
        upcoming = engine.get_payment_calendar(invoices, bank_txns, days)

    if upcoming:
        console.print(create_payment_calendar_table(upcoming))
        total = sum(p["amount"] for p in upcoming)
        overdue = sum(p["amount"] for p in upcoming if p.get("is_overdue"))
        print_info(f"Total due in next {days} days: ${total:,.2f}")
        if overdue > 0:
            print_warning(f"${overdue:,.2f} already overdue!")
    else:
        print_info(f"No payments due in the next {days} days.")


@app.command("forecast")
def cash_forecast(
    days: int = typer.Option(14, "--days", "-d", help="Days to forecast"),
) -> None:
    """Forecast cash position based on upcoming payments and expected income."""
    from bizops.parsers.payments import PaymentEngine
    from bizops.utils.storage import (
        load_bank_transactions,
        load_invoices,
        load_toast_reports,
    )

    config = load_config()
    start, _ = _resolve_date_range(TimeRange.month)
    from datetime import datetime
    end = datetime.now().strftime("%Y-%m-%d")

    with get_spinner() as spinner:
        spinner.add_task("Forecasting cash flow...", total=None)
        invoices = load_invoices(config, start, end)
        bank_txns = load_bank_transactions(config, start, end)
        toast = load_toast_reports(config, start, end)
        engine = PaymentEngine(config)
        forecast = engine.get_cash_forecast(invoices, bank_txns, toast, days)

    console.print(create_cash_forecast_panel(forecast))

    danger = forecast.get("danger_days", [])
    if danger:
        print_warning(f"Cash drops below $2,000 on {len(danger)} day(s) — review payments!")


@app.command("vendor")
def vendor_history(
    vendor: str = typer.Argument(..., help="Vendor name"),
    period: TimeRange = typer.Option(TimeRange.quarter, "--period", "-p"),
) -> None:
    """Show detailed payment history for a specific vendor."""
    from rich.table import Table

    from bizops.parsers.payments import PaymentEngine
    from bizops.utils.storage import load_bank_transactions, load_invoices

    config = load_config()
    start, end = _resolve_date_range(period)

    with get_spinner() as spinner:
        spinner.add_task(f"Loading {vendor} history...", total=None)
        invoices = load_invoices(config, start, end)
        bank_txns = load_bank_transactions(config, start, end)
        engine = PaymentEngine(config)
        history = engine.get_vendor_payment_history(vendor, invoices, bank_txns)

    if history.get("message"):
        print_info(history["message"])
        return

    # Summary
    console.print(f"\n[bold cyan]{history['vendor']}[/bold cyan]")
    console.print(f"  Terms: {history['payment_terms']}  |  Avg Days to Pay: {history.get('avg_days_to_pay') or 'N/A'}")
    console.print(f"  Invoiced: ${history['total_invoiced']:,.2f}  |  Paid: ${history['total_paid']:,.2f}  |  Due: ${history['balance_due']:,.2f}")

    # Invoice table
    table = Table(show_header=True, header_style="bold")
    table.add_column("Date", width=12)
    table.add_column("Amount", justify="right", width=12)
    table.add_column("Due", width=12)
    table.add_column("Status", width=10)

    for inv in history.get("invoices", []):
        status = inv.get("status", "")
        style = {"paid": "[green]Paid[/green]", "unpaid": "[yellow]Unpaid[/yellow]", "overdue": "[red]OVERDUE[/red]"}.get(status, status)
        table.add_row(inv.get("date", ""), f"${inv['amount']:,.2f}", inv.get("due_date", ""), style)

    console.print(table)
