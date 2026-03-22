"""Labor cost tracking commands."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum

import typer
from rich.console import Console

from bizops.utils.config import EmployeeConfig, load_config, save_config
from bizops.utils.display import (
    create_labor_panel,
    create_labor_trend_table,
    get_spinner,
    print_error,
    print_info,
    print_success,
    print_warning,
)

console = Console()
app = typer.Typer(no_args_is_help=True)


class TimeRange(StrEnum):
    today = "today"
    week = "week"
    month = "month"
    quarter = "quarter"


def _resolve_date_range(period: TimeRange) -> tuple[str, str]:
    today = datetime.now()
    if period == TimeRange.today:
        d = today.strftime("%Y-%m-%d")
        return d, d
    elif period == TimeRange.week:
        start = today - timedelta(days=today.weekday())
        return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
    elif period == TimeRange.quarter:
        q_start_month = ((today.month - 1) // 3) * 3 + 1
        start = today.replace(month=q_start_month, day=1)
        return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
    else:
        start = today.replace(day=1)
        return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")


@app.command("report")
def report(
    period: TimeRange = typer.Option(
        TimeRange.month, "--period", "-p", help="Time period."
    ),
) -> None:
    """Show current labor cost percentage with breakdown by source."""
    from bizops.parsers.labor import LaborEngine
    from bizops.utils.storage import (
        load_bank_transactions,
        load_toast_reports,
        save_labor,
    )

    config = load_config()
    start, end = _resolve_date_range(period)
    year_month = start[:7]

    with get_spinner() as spinner:
        spinner.add_task("Calculating labor cost...", total=None)

        bank_txns = load_bank_transactions(config, start, end)
        toast_reports = load_toast_reports(config, start, end)

        if not bank_txns and not toast_reports:
            print_warning("No data found. Import bank statements and pull Toast data first.")
            raise typer.Exit(0)

        engine = LaborEngine(config)
        labor_data = engine.calculate_labor_cost(bank_txns, toast_reports)

        save_labor(config, labor_data, year_month)

    console.print(create_labor_panel(labor_data))

    # Show alerts
    alerts = engine.check_labor_alerts(labor_data)
    for alert in alerts:
        if alert["type"] == "critical":
            print_error(alert["message"])
        elif alert["type"] == "warning":
            print_warning(alert["message"])
        else:
            print_info(alert["message"])


@app.command("trend")
def trend(
    months: int = typer.Option(3, "--months", "-m", help="Number of months to compare."),
) -> None:
    """Show month-over-month labor cost trend."""
    from bizops.parsers.labor import LaborEngine

    config = load_config()
    engine = LaborEngine(config)

    with get_spinner() as spinner:
        spinner.add_task("Loading trend data...", total=None)
        snapshots = engine.get_labor_trend(months)

    if all(s["status"] == "no_data" for s in snapshots):
        print_warning("No data found. Import bank statements first.")
        raise typer.Exit(0)

    console.print(create_labor_trend_table(snapshots))


@app.command("alerts")
def alerts(
    period: TimeRange = typer.Option(
        TimeRange.month, "--period", "-p", help="Time period."
    ),
) -> None:
    """Show labor cost alerts and warnings."""
    from bizops.utils.storage import load_labor

    config = load_config()
    year_month = _resolve_date_range(period)[0][:7]

    labor_data = load_labor(config, year_month)
    if not labor_data:
        print_warning("No labor data found. Run 'bizops labor report' first.")
        raise typer.Exit(0)

    from bizops.parsers.labor import LaborEngine

    engine = LaborEngine(config)
    alert_list = engine.check_labor_alerts(labor_data)

    if not alert_list:
        print_success(f"No alerts — labor cost is within target ({labor_data.get('labor_pct', 0)}%)")
        return

    for alert in alert_list:
        if alert["type"] == "critical":
            print_error(alert["message"])
        elif alert["type"] == "warning":
            print_warning(alert["message"])
        else:
            print_info(alert["message"])


@app.command("detect")
def detect(
    period: TimeRange = typer.Option(
        TimeRange.month, "--period", "-p", help="Time period."
    ),
) -> None:
    """Detect potential cash/Zelle labor payments for review."""
    from rich.table import Table

    from bizops.parsers.labor import LaborEngine
    from bizops.utils.storage import load_bank_transactions

    config = load_config()
    start, end = _resolve_date_range(period)

    bank_txns = load_bank_transactions(config, start, end)
    if not bank_txns:
        print_warning("No bank transactions found. Import bank statements first.")
        raise typer.Exit(0)

    engine = LaborEngine(config)
    flagged = engine.detect_cash_labor(bank_txns)

    if not flagged:
        print_info("No potential cash labor payments detected.")
        if not config.employees:
            print_info("Tip: Add employees with 'bizops labor add-employee' for better detection.")
        return

    table = Table(title="Potential Cash Labor Payments", show_header=True, header_style="bold yellow")
    table.add_column("#", style="dim", width=4)
    table.add_column("Date", style="green", width=12)
    table.add_column("Description", style="cyan", width=30)
    table.add_column("Amount", justify="right", width=12)
    table.add_column("Reason", width=20)
    table.add_column("Employee", width=15)

    for i, item in enumerate(flagged, 1):
        txn = item["txn"]
        table.add_row(
            str(i),
            txn.get("date", "-"),
            (txn.get("description", ""))[:30],
            f"[red]${abs(txn.get('amount', 0)):,.2f}[/red]",
            item.get("match_reason", "").replace("_", " ").title(),
            item.get("matched_employee", "unknown"),
        )

    console.print(table)
    print_info(f"{len(flagged)} potential cash labor payment(s) found — review and confirm.")


@app.command("add-employee")
def add_employee(
    name: str = typer.Option(..., "--name", "-n", help="Employee name."),
    role: str = typer.Option("", "--role", "-r", help="Role/position."),
    pay_type: str = typer.Option("hourly", "--pay-type", help="hourly, salary, or contract."),
    rate: float = typer.Option(0.0, "--rate", help="Pay rate."),
    aliases: str = typer.Option("", "--aliases", "-a", help="Comma-separated bank description aliases."),
) -> None:
    """Add an employee for labor cost tracking."""
    config = load_config()

    alias_list = [a.strip() for a in aliases.split(",") if a.strip()] if aliases else []

    emp = EmployeeConfig(
        name=name,
        role=role,
        pay_type=pay_type,
        pay_rate=rate,
        aliases=alias_list,
    )

    config.employees.append(emp)
    save_config(config)

    print_success(f"Added employee: {name}")
    if alias_list:
        print_info(f"Bank aliases: {', '.join(alias_list)}")
    print_info("These aliases help detect cash/Zelle payments in bank statements.")
