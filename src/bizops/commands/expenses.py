"""Expense tracking commands — categorize, report, and summarize."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path

import typer

from bizops.utils.config import load_config
from bizops.utils.display import (
    console,
    create_expense_table,
    create_pl_panel,
    print_info,
    print_success,
    print_warning,
)

app = typer.Typer(no_args_is_help=True)


class TimeRange(StrEnum):
    today = "today"
    week = "week"
    month = "month"
    quarter = "quarter"


class Source(StrEnum):
    all = "all"
    toast = "toast"
    gmail = "gmail"


def _resolve_date_range(period: TimeRange) -> tuple[str, str]:
    """Convert period enum to start/end date strings."""
    today = datetime.now()
    if period == TimeRange.today:
        d = today.strftime("%Y-%m-%d")
        return d, d
    elif period == TimeRange.week:
        start = today - timedelta(days=today.weekday())
        return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
    elif period == TimeRange.month:
        start = today.replace(day=1)
        return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
    elif period == TimeRange.quarter:
        q_start_month = ((today.month - 1) // 3) * 3 + 1
        start = today.replace(month=q_start_month, day=1)
        return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
    else:
        start = today.replace(day=1)
        return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")


@app.command("track")
def track_expenses(
    period: TimeRange = typer.Option(
        TimeRange.month,
        "--period", "-p",
        help="Time period: today, week, month, quarter.",
    ),
    source: Source = typer.Option(
        Source.all,
        "--source", "-s",
        help="Data source: toast, gmail, all.",
    ),
):
    """
    Track and categorize expenses from POS and invoices.

    Fetches data, categorizes by vendor/keyword, and shows P&L summary.

    Examples:
        bizops expenses track --period month
        bizops expenses track --source toast --period week
    """
    config = load_config()
    start_date, end_date = _resolve_date_range(period)

    print_info(f"Tracking expenses from {start_date} to {end_date} (source: {source.value})")

    # Load invoices
    from bizops.utils.storage import load_invoices, load_toast_reports, save_expenses

    invoices: list = []
    toast_reports: list = []

    if source in (Source.all, Source.gmail):
        invoices = load_invoices(config, start_date, end_date)
        if not invoices:
            print_warning("No invoice data found. Run 'bizops invoices pull' first.")

    if source in (Source.all, Source.toast):
        toast_reports = load_toast_reports(config, start_date, end_date)
        if not toast_reports:
            print_info("No Toast POS data found. Toast reports will be included when available.")

    if not invoices and not toast_reports:
        print_warning("No data to categorize.")
        raise typer.Exit()

    # Segregate invoices to get only payments (money OUT)
    from bizops.commands._export import segregate_invoices
    from bizops.parsers.expenses import ExpenseEngine

    if invoices:
        buckets = segregate_invoices(invoices)
        payment_invoices = buckets.get("payment", [])
    else:
        payment_invoices = []

    engine = ExpenseEngine(config)
    pl_data = engine.categorize_all(payment_invoices, toast_reports, start_date, end_date)

    # Display categorized expenses
    all_expenses = []
    for cat, items in pl_data.get("expenses_by_category", {}).items():
        for item in items:
            item["expense_category"] = cat.replace("_", " ").title()
            all_expenses.append(item)

    all_expenses.sort(key=lambda x: x.get("date", ""), reverse=True)

    if all_expenses:
        table = create_expense_table(all_expenses, title=f"Expenses ({start_date} to {end_date})")
        console.print(table)

    # Show P&L panel
    pl_panel = create_pl_panel(pl_data)
    console.print(pl_panel)

    # Save to storage
    year_month = start_date[:7]
    storage_path = save_expenses(config, pl_data, year_month)
    print_info(f"Saved expense data to {storage_path.name}")


@app.command("report")
def expense_report(
    period: TimeRange = typer.Option(
        TimeRange.month,
        "--period", "-p",
        help="Time period.",
    ),
    output: Path | None = typer.Option(
        None,
        "--output", "-o",
        help="Output file path (default: auto-generated).",
    ),
    format: str = typer.Option(
        "xlsx",
        "--format", "-f",
        help="Output format: xlsx.",
    ),
):
    """
    Generate P&L report as Excel workbook.

    Examples:
        bizops expenses report --period month
        bizops expenses report --output ./march_pl.xlsx
    """
    config = load_config()
    start_date, end_date = _resolve_date_range(period)
    year_month = start_date[:7]

    # Load expense data from storage
    from bizops.utils.storage import load_expenses, load_invoices, load_toast_reports

    pl_data = load_expenses(config, year_month)

    if not pl_data:
        print_info("No saved expense data. Running categorization first...")
        invoices = load_invoices(config, start_date, end_date)
        toast_reports = load_toast_reports(config, start_date, end_date)

        if not invoices and not toast_reports:
            print_warning("No data available. Run 'bizops invoices pull' first.")
            raise typer.Exit()

        from bizops.commands._export import segregate_invoices
        from bizops.parsers.expenses import ExpenseEngine

        payment_invoices = segregate_invoices(invoices).get("payment", []) if invoices else []
        engine = ExpenseEngine(config)
        pl_data = engine.categorize_all(payment_invoices, toast_reports, start_date, end_date)

    from bizops.commands._export import export_pl_workbook

    output_path = export_pl_workbook(pl_data, config, output_path=output)
    print_success(f"P&L report exported to [bold]{output_path}[/bold]")


@app.command("summary")
def expense_summary(
    period: TimeRange = typer.Option(
        TimeRange.month,
        "--period", "-p",
        help="Time period.",
    ),
):
    """
    Show a quick P&L summary in the terminal.

    Examples:
        bizops expenses summary --period month
    """
    config = load_config()
    start_date, end_date = _resolve_date_range(period)
    year_month = start_date[:7]

    from bizops.utils.storage import load_expenses, load_invoices, load_toast_reports

    pl_data = load_expenses(config, year_month)

    if not pl_data:
        # Try building from raw data
        invoices = load_invoices(config, start_date, end_date)
        toast_reports = load_toast_reports(config, start_date, end_date)

        if not invoices and not toast_reports:
            print_warning("No data available. Run 'bizops invoices pull' first.")
            raise typer.Exit()

        from bizops.commands._export import segregate_invoices
        from bizops.parsers.expenses import ExpenseEngine

        payment_invoices = segregate_invoices(invoices).get("payment", []) if invoices else []
        engine = ExpenseEngine(config)
        pl_data = engine.categorize_all(payment_invoices, toast_reports, start_date, end_date)

    pl_panel = create_pl_panel(pl_data)
    console.print(pl_panel)
