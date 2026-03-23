"""Inventory estimation CLI commands."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from bizops.utils.config import load_config
from bizops.utils.display import get_spinner, print_info

console = Console()
app = typer.Typer(no_args_is_help=True)


@app.command("stock")
def stock_estimate() -> None:
    """Estimate current stock levels from purchase history."""
    from datetime import datetime

    from bizops.parsers.inventory import InventoryEstimator
    from bizops.utils.storage import load_invoices, load_toast_reports

    config = load_config()
    today = datetime.now()
    start = (today.replace(day=1)).strftime("%Y-%m-%d")
    end = today.strftime("%Y-%m-%d")

    with get_spinner() as spinner:
        spinner.add_task("Estimating stock levels...", total=None)
        invoices = load_invoices(config, start, end)
        toast = load_toast_reports(config, start, end)
        engine = InventoryEstimator(config)
        data = engine.estimate_stock(invoices, toast)

    table = Table(title="Estimated Stock Levels", show_header=True, header_style="bold cyan")
    table.add_column("Category", style="cyan", width=16)
    table.add_column("Purchased", justify="right", width=12)
    table.add_column("Est. Remaining", justify="right", width=14)
    table.add_column("Days Left", justify="right", width=10)
    table.add_column("Daily Usage", justify="right", width=12)
    table.add_column("Status", width=14)

    status_display = {
        "critical": "[bold red]CRITICAL[/bold red]",
        "low": "[red]LOW[/red]",
        "reorder_soon": "[yellow]REORDER[/yellow]",
        "adequate": "[green]OK[/green]",
    }

    for item in data["items"]:
        table.add_row(
            item["category"],
            f"${item['total_purchased']:,.0f}",
            f"${item['estimated_remaining']:,.0f}",
            f"{item['est_days_remaining']:.0f}" if item["est_days_remaining"] < 100 else "30+",
            f"${item['est_daily_usage']:,.0f}/day",
            status_display.get(item["status"], "--"),
        )

    console.print(table)

    if data["low_stock_count"] > 0:
        console.print(f"\n[yellow]{data['low_stock_count']} categories need attention![/yellow]")


@app.command("reorder")
def reorder_list() -> None:
    """Show items that need to be reordered now."""
    from datetime import datetime

    from bizops.parsers.inventory import InventoryEstimator
    from bizops.utils.storage import load_invoices, load_toast_reports

    config = load_config()
    today = datetime.now()
    start = today.replace(day=1).strftime("%Y-%m-%d")
    end = today.strftime("%Y-%m-%d")

    with get_spinner() as spinner:
        spinner.add_task("Checking reorder needs...", total=None)
        invoices = load_invoices(config, start, end)
        toast = load_toast_reports(config, start, end)
        engine = InventoryEstimator(config)
        reorders = engine.get_reorder_list(invoices, toast)

    if not reorders:
        print_info("No reorders needed — stock levels look good!")
        return

    table = Table(title="Reorder Needed", show_header=True, header_style="bold red")
    table.add_column("Category", style="cyan", width=16)
    table.add_column("Vendor", width=16)
    table.add_column("Urgency", width=14)
    table.add_column("Days Left", justify="right", width=10)
    table.add_column("Suggested Order", justify="right", width=14)

    urgency_display = {
        "order_today": "[bold red]ORDER TODAY[/bold red]",
        "order_soon": "[yellow]ORDER SOON[/yellow]",
        "plan_order": "[cyan]PLAN ORDER[/cyan]",
    }

    for r in reorders:
        table.add_row(
            r["category"],
            r["vendor"],
            urgency_display.get(r["urgency"], "--"),
            f"{r['est_days_left']:.0f}",
            f"${r['suggested_order_value']:,.0f}",
        )

    console.print(table)


@app.command("frequency")
def purchase_frequency() -> None:
    """Analyze purchase patterns — how often you order from each vendor."""
    from datetime import datetime, timedelta

    from bizops.parsers.inventory import InventoryEstimator
    from bizops.utils.storage import load_invoices

    config = load_config()
    today = datetime.now()
    start = (today - timedelta(days=90)).strftime("%Y-%m-%d")
    end = today.strftime("%Y-%m-%d")

    with get_spinner() as spinner:
        spinner.add_task("Analyzing purchase patterns...", total=None)
        invoices = load_invoices(config, start, end)
        engine = InventoryEstimator(config)
        patterns = engine.get_purchase_frequency(invoices)

    if not patterns:
        print_info("Not enough purchase history to analyze patterns.")
        return

    table = Table(title="Purchase Frequency (Last 90 Days)", show_header=True, header_style="bold cyan")
    table.add_column("Vendor", style="cyan", width=20)
    table.add_column("Orders", justify="right", width=8)
    table.add_column("Avg Order", justify="right", width=12)
    table.add_column("Total", justify="right", width=12)
    table.add_column("Avg Gap", justify="right", width=10)
    table.add_column("Frequency", width=16)

    for p in patterns:
        table.add_row(
            p["vendor"],
            str(p["order_count"]),
            f"${p['avg_order_value']:,.0f}",
            f"${p['total_spend']:,.0f}",
            f"{p['avg_days_between_orders']:.0f} days",
            p["estimated_frequency"].replace("_", " ").title(),
        )

    console.print(table)


@app.callback()
def main():
    """Inventory estimation — stock levels, reorders, and purchase patterns."""
    pass
