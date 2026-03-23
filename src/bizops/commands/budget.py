"""Budget tracking CLI commands."""

from __future__ import annotations

import typer
from rich.console import Console

from bizops.utils.config import ExpenseCategory, load_config, save_config
from bizops.utils.display import create_budget_status_table, get_spinner, print_info, print_success

console = Console()
app = typer.Typer(no_args_is_help=True)


@app.command("status")
def budget_status() -> None:
    """Show budget vs actual spending for current month."""
    from bizops.parsers.budget import BudgetEngine
    from bizops.utils.storage import load_expenses, load_toast_reports

    from datetime import datetime

    config = load_config()
    today = datetime.now()
    year_month = today.strftime("%Y-%m")
    start = today.replace(day=1).strftime("%Y-%m-%d")
    end = today.strftime("%Y-%m-%d")

    with get_spinner() as spinner:
        spinner.add_task("Loading budget data...", total=None)
        expenses = load_expenses(config, year_month)
        toast = load_toast_reports(config, start, end)
        engine = BudgetEngine(config)
        data = engine.get_budget_status(expenses or {}, toast)

    console.print(create_budget_status_table(data))

    summary = data.get("summary", {})
    if summary.get("over_budget_count", 0) > 0:
        console.print(f"\n[red]{summary['over_budget_count']} categories OVER budget![/red]")
    elif summary.get("warning_count", 0) > 0:
        console.print(f"\n[yellow]{summary['warning_count']} categories approaching budget limit[/yellow]")
    else:
        print_success("All categories on track!")


@app.command("set")
def set_budget(
    category: str = typer.Argument(..., help="Expense category"),
    amount: float = typer.Argument(..., help="Monthly budget amount"),
    alert_pct: float = typer.Option(80.0, "--alert", "-a", help="Alert at this % of budget"),
) -> None:
    """Set monthly budget for a category."""
    from bizops.parsers.budget import BudgetEngine

    config = load_config()
    engine = BudgetEngine(config)
    result = engine.set_budget(category, amount, alert_pct)

    save_config(config)
    action = "Updated" if result["updated"] else "Created"
    print_success(f"{action} budget: {category} = ${amount:,.0f}/month (alert at {alert_pct}%)")


@app.command("alerts")
def budget_alerts() -> None:
    """Show budget alerts — overruns and warnings."""
    from bizops.parsers.budget import BudgetEngine
    from bizops.utils.storage import load_expenses

    from datetime import datetime

    config = load_config()
    year_month = datetime.now().strftime("%Y-%m")

    with get_spinner() as spinner:
        spinner.add_task("Checking budgets...", total=None)
        expenses = load_expenses(config, year_month)
        engine = BudgetEngine(config)
        alerts = engine.get_budget_alerts(expenses or {})

    if not alerts:
        print_success("No budget alerts — everything on track!")
        return

    severity_colors = {"critical": "red", "warning": "yellow", "info": "cyan"}
    for alert in alerts:
        color = severity_colors.get(alert["severity"], "white")
        console.print(f"[{color}][{alert['severity'].upper()}][/{color}] {alert['message']}")
        console.print(f"  [dim]{alert['action']}[/dim]")
        console.print()


@app.command("recommend")
def budget_recommend(
    months: int = typer.Option(3, "--months", "-m", help="Months of history to analyze"),
) -> None:
    """Get AI-recommended budgets based on spending history."""
    from rich.table import Table

    from bizops.parsers.budget import BudgetEngine
    from bizops.utils.storage import load_expenses

    from datetime import datetime, timedelta

    config = load_config()
    today = datetime.now()

    with get_spinner() as spinner:
        spinner.add_task("Analyzing spending history...", total=None)
        history = []
        for m in range(months):
            dt = today.replace(day=1) - timedelta(days=30 * m)
            ym = dt.strftime("%Y-%m")
            exp = load_expenses(config, ym)
            if exp:
                history.append(exp)

        engine = BudgetEngine(config)
        recs = engine.get_budget_recommendation(history)

    if not recs:
        print_info("Not enough history to make recommendations. Need at least 1 month.")
        return

    table = Table(title="Recommended Budgets", show_header=True, header_style="bold cyan")
    table.add_column("Category", style="cyan", width=16)
    table.add_column("Recommended", justify="right", width=12)
    table.add_column("Current", justify="right", width=10)
    table.add_column("Avg/Month", justify="right", width=10)
    table.add_column("Max", justify="right", width=10)
    table.add_column("Action", width=10)

    change_display = {"increase": "[yellow]INCREASE[/yellow]", "decrease": "[green]DECREASE[/green]", "new": "[cyan]NEW[/cyan]", "no_change": "[dim]--[/dim]"}

    for r in recs:
        table.add_row(
            r["category"],
            f"${r['recommended_budget']:,.0f}",
            f"${r['current_budget']:,.0f}" if r["current_budget"] > 0 else "--",
            f"${r['avg_monthly']:,.0f}",
            f"${r['max_monthly']:,.0f}",
            change_display.get(r["change"], "--"),
        )

    console.print(table)


@app.callback()
def main():
    """Budget tracking — set budgets, track spending, get alerts."""
    pass
