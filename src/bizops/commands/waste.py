"""Waste estimation CLI commands."""

from __future__ import annotations

from enum import StrEnum

import typer
from rich.console import Console

from bizops.utils.config import load_config
from bizops.utils.display import (
    create_waste_panel,
    create_waste_trend_table,
    get_spinner,
    print_info,
)

console = Console()
app = typer.Typer(no_args_is_help=True)


class TimeRange(StrEnum):
    month = "month"
    quarter = "quarter"


@app.command("estimate")
def waste_estimate(
    period: TimeRange = typer.Option(TimeRange.month, "--period", "-p"),
) -> None:
    """Estimate food waste from purchases vs theoretical usage."""
    from bizops.parsers.waste import WasteEngine

    config = load_config()

    with get_spinner() as spinner:
        spinner.add_task("Estimating waste...", total=None)
        engine = WasteEngine(config)
        data = engine.estimate_waste_from_data(period)

    console.print(create_waste_panel(data))

    if data.get("status") == "no_data":
        print_info("Import expense and sales data to start tracking waste.")


@app.command("trend")
def waste_trend(
    months: int = typer.Option(6, "--months", "-m"),
) -> None:
    """Show month-over-month waste trend."""
    from bizops.parsers.waste import WasteEngine

    config = load_config()

    with get_spinner() as spinner:
        spinner.add_task("Building waste trend...", total=None)
        engine = WasteEngine(config)
        data = engine.get_waste_trend(months)

    console.print(create_waste_trend_table(data))


@app.command("tips")
def waste_tips(
    period: TimeRange = typer.Option(TimeRange.month, "--period", "-p"),
) -> None:
    """Get actionable waste reduction recommendations."""
    from bizops.parsers.waste import WasteEngine

    config = load_config()

    with get_spinner() as spinner:
        spinner.add_task("Analyzing waste patterns...", total=None)
        engine = WasteEngine(config)
        data = engine.estimate_waste_from_data(period)
        tips = engine.get_waste_reduction_tips(data)

    priority_colors = {
        "critical": "[bold red]!!![/bold red]",
        "high": "[red]!![/red]",
        "medium": "[yellow]![/yellow]",
        "info": "[dim]i[/dim]",
    }

    for tip in tips:
        icon = priority_colors.get(tip["priority"], "")
        console.print(f"  {icon} {tip['action']}")
        console.print(f"      [dim]Impact: {tip['impact']}[/dim]")
        console.print()


@app.callback()
def main():
    """Waste estimation — track and reduce food waste."""
    pass
