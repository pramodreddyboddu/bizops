"""Food cost analytics commands."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum

import typer
from rich.console import Console

from bizops.utils.config import load_config, save_config
from bizops.utils.display import (
    create_food_cost_panel,
    create_food_cost_trend_table,
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
    """Show current food cost percentage with category breakdown."""
    from bizops.commands._export import segregate_invoices
    from bizops.parsers.expenses import ExpenseEngine
    from bizops.parsers.food_cost import FoodCostEngine
    from bizops.utils.storage import (
        load_expenses,
        load_invoices,
        load_toast_reports,
        save_food_cost,
    )

    config = load_config()
    start, end = _resolve_date_range(period)
    year_month = start[:7]

    with get_spinner() as spinner:
        spinner.add_task("Calculating food cost...", total=None)

        # Try loading existing expense data
        expenses_data = load_expenses(config, year_month)

        if not expenses_data:
            # Build it from raw data
            raw_invoices = load_invoices(config, start, end)
            toast_reports = load_toast_reports(config, start, end)

            if not raw_invoices and not toast_reports:
                print_warning("No data found. Run 'bizops invoices pull' first.")
                raise typer.Exit(0)

            buckets = segregate_invoices(raw_invoices, config) if raw_invoices else {}
            payments = buckets.get("payment", [])

            engine = ExpenseEngine(config)
            expenses_data = engine.categorize_all(payments, toast_reports, start, end)

        toast_reports = load_toast_reports(config, start, end)
        fc_engine = FoodCostEngine(config)
        fc_data = fc_engine.calculate_food_cost(expenses_data, toast_reports)

        # Save snapshot
        save_food_cost(config, fc_data, year_month)

    console.print(create_food_cost_panel(fc_data))

    # Show alerts
    alerts = fc_engine.check_alerts(fc_data)
    for alert in alerts:
        if alert["type"] == "critical":
            print_error(alert["message"])
        elif alert["type"] in ("warning", "over_budget"):
            print_warning(alert["message"])


@app.command("trend")
def trend(
    months: int = typer.Option(3, "--months", "-m", help="Number of months to compare."),
) -> None:
    """Show month-over-month food cost trend."""
    from bizops.parsers.food_cost import FoodCostEngine

    config = load_config()
    engine = FoodCostEngine(config)

    with get_spinner() as spinner:
        spinner.add_task("Loading trend data...", total=None)
        snapshots = engine.month_over_month(months)

    if all(s["status"] == "no_data" for s in snapshots):
        print_warning("No expense data found. Run 'bizops expenses track' first.")
        raise typer.Exit(0)

    console.print(create_food_cost_trend_table(snapshots))


@app.command("alerts")
def alerts(
    period: TimeRange = typer.Option(
        TimeRange.month, "--period", "-p", help="Time period."
    ),
) -> None:
    """Show food cost budget alerts."""
    from bizops.parsers.food_cost import FoodCostEngine
    from bizops.utils.storage import load_food_cost

    config = load_config()
    year_month = _resolve_date_range(period)[0][:7]

    fc_data = load_food_cost(config, year_month)
    if not fc_data:
        print_warning("No food cost data found. Run 'bizops foodcost report' first.")
        raise typer.Exit(0)

    engine = FoodCostEngine(config)
    alert_list = engine.check_alerts(fc_data)

    if not alert_list:
        print_success(f"No alerts — food cost is within target ({fc_data.get('food_cost_pct', 0)}%)")
        return

    for alert in alert_list:
        if alert["type"] == "critical":
            print_error(alert["message"])
        else:
            print_warning(alert["message"])


@app.command("budget")
def set_budget(
    target: float = typer.Option(
        30.0, "--target", "-t", help="Target food cost percentage."
    ),
    alert: float = typer.Option(
        35.0, "--alert", "-a", help="Alert threshold percentage."
    ),
) -> None:
    """Set food cost budget targets."""
    config = load_config()
    config.food_cost_budget.target_food_cost_pct = target
    config.food_cost_budget.alert_threshold_pct = alert
    save_config(config)

    print_success(f"Budget targets updated: target={target}%, alert={alert}%")
    print_info("Category budgets can be set in bizops_config.json")
