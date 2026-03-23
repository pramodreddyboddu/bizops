"""BizOps CLI — main entry point."""

import typer
from rich.console import Console

from bizops import __version__
from bizops.commands.alerts import app as alerts_app
from bizops.commands.ask import app as ask_app
from bizops.commands.bank import app as bank_app
from bizops.commands.briefing import app as briefing_app
from bizops.commands.config import app as config_app
from bizops.commands.expenses import app as expenses_app
from bizops.commands.foodcost import app as foodcost_app
from bizops.commands.health import app as health_app
from bizops.commands.invoices import app as invoices_app
from bizops.commands.labor import app as labor_app
from bizops.commands.orders import app as orders_app
from bizops.commands.payments import app as payments_app
from bizops.commands.trends import app as trends_app
from bizops.commands.vendor_prices import app as vendor_prices_app
from bizops.commands.waste import app as waste_app

console = Console()

app = typer.Typer(
    name="bizops",
    help="🏪 Agentic CLI for small business operations.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

# Register command groups
app.add_typer(invoices_app, name="invoices", help="Process and manage vendor invoices.")
app.add_typer(expenses_app, name="expenses", help="Track and categorize business expenses.")
app.add_typer(bank_app, name="bank", help="Import bank statements and reconcile transactions.")
app.add_typer(foodcost_app, name="foodcost", help="Food cost analytics and budget tracking.")
app.add_typer(health_app, name="health", help="Business health score — your overall business grade.")
app.add_typer(orders_app, name="orders", help="Smart ordering and purchase order generation.")
app.add_typer(payments_app, name="payments", help="Vendor payment tracking, calendar, and cash forecast.")
app.add_typer(labor_app, name="labor", help="Labor cost tracking and payroll analysis.")
app.add_typer(briefing_app, name="briefing", help="Daily owner briefing — everything you need to know.")
app.add_typer(alerts_app, name="alerts", help="Smart alerts — proactive anomaly detection.")
app.add_typer(trends_app, name="trends", help="P&L trends, benchmarks, and revenue forecasting.")
app.add_typer(waste_app, name="waste", help="Waste estimation — track and reduce food waste.")
app.add_typer(vendor_prices_app, name="prices", help="Vendor price intelligence — spending, changes, negotiation.")
app.add_typer(config_app, name="config", help="Configure Gmail, vendors, and paths.")
app.add_typer(ask_app, name="ask", help="AI-powered business questions and insights.")


@app.command()
def version():
    """Show BizOps version."""
    console.print(f"[bold green]bizops[/bold green] v{__version__}")


@app.command()
def status():
    """Show current configuration and connection status."""
    from rich.table import Table

    from bizops.utils.config import load_config

    config = load_config()
    table = Table(title="BizOps Status", show_header=True)
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")
    table.add_column("Status")

    # Gmail connection
    gmail_status = "✓ Connected" if config.gmail_credentials_path.exists() else "✗ Not configured"
    table.add_row("Gmail", str(config.gmail_credentials_path), gmail_status)

    # Output directory
    out_status = "✓ Exists" if config.output_dir.exists() else "✗ Missing"
    table.add_row("Output Dir", str(config.output_dir), out_status)

    # Vendor list
    vendor_count = len(config.vendors)
    table.add_row("Vendors", f"{vendor_count} configured", "✓" if vendor_count > 0 else "⚠ None")

    console.print(table)


@app.callback()
def main():
    """
    [bold green]bizops[/bold green] — Your business operations agent.

    Process invoices, track expenses, generate P&L reports — all from your terminal.
    """
    pass


if __name__ == "__main__":
    app()
