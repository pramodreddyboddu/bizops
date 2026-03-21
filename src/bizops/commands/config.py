"""Configuration commands — setup, vendor management."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from bizops.utils.config import (
    DEFAULT_VENDORS,
    BizOpsConfig,
    VendorConfig,
    load_config,
    save_config,
)
from bizops.utils.display import print_error, print_success, print_warning

console = Console()
app = typer.Typer(no_args_is_help=True)


@app.command("setup")
def setup(
    credentials: Path | None = typer.Option(
        None,
        "--credentials", "-c",
        help="Path to Gmail API credentials.json file.",
    ),
    output_dir: Path | None = typer.Option(
        None,
        "--output-dir", "-o",
        help="Directory for output files.",
    ),
    use_defaults: bool = typer.Option(
        False,
        "--defaults",
        help="Load default vendor list (Sysco, Restaurant Depot, Toast).",
    ),
):
    """
    Set up BizOps configuration.

    Run this first to configure Gmail credentials and output paths.

    Examples:
        bizops config setup --credentials ~/Downloads/credentials.json
        bizops config setup --defaults
    """
    config = load_config()

    if credentials:
        if not credentials.exists():
            print_error(f"Credentials file not found: {credentials}")
            raise typer.Exit(code=1)
        config.gmail_credentials_path = credentials
        print_success(f"Gmail credentials: {credentials}")

    if output_dir:
        config.output_dir = output_dir
        print_success(f"Output directory: {output_dir}")

    if use_defaults:
        existing_names = {v.name.lower() for v in config.vendors}
        added = 0
        for vendor in DEFAULT_VENDORS:
            if vendor.name.lower() not in existing_names:
                config.vendors.append(vendor)
                added += 1
        print_success(f"Added {added} default vendors")

    config.ensure_dirs()
    save_config(config)
    print_success("Configuration saved!")

    # Show status
    console.print()
    _show_config_summary(config)


@app.command("vendors")
def list_vendors():
    """List configured vendors."""
    config = load_config()

    if not config.vendors:
        print_warning("No vendors configured. Run [bold]bizops config setup --defaults[/bold]")
        raise typer.Exit()

    table = Table(title="Configured Vendors", show_header=True)
    table.add_column("#", style="dim", width=4)
    table.add_column("Vendor", style="cyan")
    table.add_column("Category", style="green")
    table.add_column("Email Patterns")
    table.add_column("Aliases", style="dim")

    for i, vendor in enumerate(config.vendors, 1):
        table.add_row(
            str(i),
            vendor.name,
            vendor.category,
            ", ".join(vendor.email_patterns),
            ", ".join(vendor.aliases) if vendor.aliases else "—",
        )

    console.print(table)


@app.command("add-vendor")
def add_vendor(
    name: str = typer.Argument(..., help="Vendor name."),
    email: str = typer.Option(..., "--email", "-e", help="Email pattern to match."),
    category: str = typer.Option("uncategorized", "--category", "-c", help="Expense category."),
):
    """
    Add a new vendor to the configuration.

    Examples:
        bizops config add-vendor "Roma Foods" --email roma-foods.com --category produce
        bizops config add-vendor "US Foods" --email usfoods.com --category food_supplies
    """
    config = load_config()

    # Check for duplicate
    if any(v.name.lower() == name.lower() for v in config.vendors):
        print_error(f"Vendor '{name}' already exists.")
        raise typer.Exit(code=1)

    vendor = VendorConfig(
        name=name,
        email_patterns=[email],
        category=category,
    )
    config.vendors.append(vendor)
    save_config(config)
    print_success(f"Added vendor: [bold]{name}[/bold] ({category})")


@app.command("show")
def show_config():
    """Show current configuration."""
    config = load_config()
    _show_config_summary(config)


def _show_config_summary(config: BizOpsConfig) -> None:
    """Display config summary table."""
    table = Table(title="BizOps Configuration", show_header=True)
    table.add_column("Setting", style="cyan")
    table.add_column("Value")

    table.add_row("Base directory", str(config.base_dir))
    table.add_row("Output directory", str(config.output_dir))
    table.add_row("Gmail credentials", str(config.gmail_credentials_path))
    table.add_row("Gmail label", config.gmail_label)
    table.add_row("Dedup enabled", str(config.dedup_enabled))
    table.add_row("Vendors configured", str(len(config.vendors)))

    console.print(table)
