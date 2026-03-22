"""P&L trends and business benchmarks CLI commands."""

from __future__ import annotations

import typer
from rich.console import Console

from bizops.utils.config import load_config
from bizops.utils.display import (
    create_benchmark_panel,
    create_forecast_panel,
    create_pl_trend_table,
    get_spinner,
    print_info,
)

console = Console()
app = typer.Typer(no_args_is_help=True)


@app.command("pl")
def pl_trend(
    months: int = typer.Option(6, "--months", "-m", help="Number of months to analyze"),
) -> None:
    """Show month-over-month P&L trend — revenue, expenses, profit margin."""
    from bizops.parsers.trends import TrendEngine

    config = load_config()

    with get_spinner() as spinner:
        spinner.add_task("Building P&L trend...", total=None)
        engine = TrendEngine(config)
        data = engine.get_pl_trend(months)

    console.print(create_pl_trend_table(data))

    valid = data.get("months_with_data", 0)
    if valid == 0:
        print_info("No data found. Import bank statements and Toast reports first.")


@app.command("category")
def category_trend(
    category: str = typer.Argument(..., help="Expense category (e.g., food_supplies, payroll, rent)"),
    months: int = typer.Option(6, "--months", "-m"),
) -> None:
    """Track a specific expense category over time."""
    from rich.table import Table

    from bizops.parsers.trends import TrendEngine

    config = load_config()

    with get_spinner() as spinner:
        spinner.add_task(f"Analyzing {category} trend...", total=None)
        engine = TrendEngine(config)
        data = engine.get_category_trend(category, months)

    label = category.replace("_", " ").title()
    table = Table(title=f"{label} Trend", show_header=True, header_style="bold cyan")
    table.add_column("Month", style="cyan", width=10)
    table.add_column("Total", justify="right", width=12)
    table.add_column("% of Revenue", justify="right", width=12)
    table.add_column("Trend", width=8)

    arrows = {"up": "[red]^[/red]", "down": "[green]v[/green]", "flat": "[dim]-[/dim]"}

    for snap in data.get("snapshots", []):
        table.add_row(
            snap["month"],
            f"${snap['total']:,.2f}" if snap["total"] else "[dim]--[/dim]",
            f"{snap['pct_of_revenue']}%" if snap["pct_of_revenue"] else "[dim]--[/dim]",
            arrows.get(snap.get("trend", "flat"), "-"),
        )

    console.print(table)


@app.command("forecast")
def revenue_forecast(
    days: int = typer.Option(30, "--days", "-d", help="Days to forecast"),
) -> None:
    """Forecast revenue based on historical sales patterns."""
    from bizops.parsers.trends import TrendEngine

    config = load_config()

    with get_spinner() as spinner:
        spinner.add_task("Building revenue forecast...", total=None)
        engine = TrendEngine(config)
        data = engine.get_revenue_forecast(days)

    console.print(create_forecast_panel(data))


@app.command("benchmarks")
def benchmarks() -> None:
    """Compare your metrics against industry benchmarks — food cost, labor, profit margin."""
    from bizops.parsers.trends import TrendEngine

    config = load_config()

    with get_spinner() as spinner:
        spinner.add_task("Comparing against benchmarks...", total=None)
        engine = TrendEngine(config)
        data = engine.get_benchmarks()

    console.print(create_benchmark_panel(data))


@app.callback()
def main():
    """P&L trends, revenue forecasting, and industry benchmarks."""
    pass
