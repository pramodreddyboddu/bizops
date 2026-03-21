"""Invoice processing commands."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path

import typer
from rich.console import Console

from bizops.utils.config import load_config
from bizops.utils.display import (
    create_invoice_table,
    create_summary_panel,
    get_spinner,
    print_error,
    print_info,
    print_success,
    print_warning,
)

console = Console()
app = typer.Typer(no_args_is_help=True)


class TimeRange(StrEnum):
    """Time range for invoice queries."""

    today = "today"
    week = "week"
    month = "month"
    quarter = "quarter"
    custom = "custom"


class StatusFilter(StrEnum):
    """Invoice payment status filter."""

    all = "all"
    paid = "paid"
    unpaid = "unpaid"
    partial = "partial"


@app.command("pull")
def pull_invoices(
    period: TimeRange = typer.Option(
        TimeRange.week,
        "--period", "-p",
        help="Time period to pull invoices for.",
    ),
    since: str | None = typer.Option(
        None,
        "--since",
        help="Start date (YYYY-MM-DD) for custom range.",
    ),
    until: str | None = typer.Option(
        None,
        "--until",
        help="End date (YYYY-MM-DD) for custom range.",
    ),
    vendor: str | None = typer.Option(
        None,
        "--vendor", "-v",
        help="Filter by vendor name.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be pulled without processing.",
    ),
):
    """
    Pull invoices from Gmail and process them.

    Examples:
        bizops invoices pull --period week
        bizops invoices pull --since 2026-03-01 --until 2026-03-15
        bizops invoices pull --vendor sysco
    """
    config = load_config()

    # Resolve date range
    start_date, end_date = _resolve_date_range(period, since, until)
    print_info(f"Pulling invoices from [bold]{start_date}[/bold] to [bold]{end_date}[/bold]")

    if vendor:
        print_info(f"Filtering by vendor: [bold]{vendor}[/bold]")

    if dry_run:
        print_warning("Dry run mode — no files will be created")

    # Connect to Gmail and fetch
    with get_spinner() as progress:
        task = progress.add_task("Connecting to Gmail...", total=None)

        try:
            from bizops.connectors.gmail import GmailConnector

            gmail = GmailConnector(config)
            progress.update(task, description="Searching for invoices...")

            raw_emails = gmail.search_invoices(
                start_date=start_date,
                end_date=end_date,
                vendor_filter=vendor,
            )
            progress.update(task, description="Extracting invoice data...")

            from bizops.parsers.invoice import InvoiceParser

            parser = InvoiceParser(config)
            invoices = parser.parse_emails(raw_emails)

            # Dedup
            if config.dedup_enabled:
                before_count = len(invoices)
                invoices = parser.deduplicate(invoices)
                duped = before_count - len(invoices)
                if duped > 0:
                    progress.update(
                        task, description=f"Removed {duped} duplicate(s)..."
                    )

        except FileNotFoundError:
            print_error(
                "Gmail credentials not found. Run [bold]bizops config setup[/bold] first."
            )
            raise typer.Exit(code=1)
        except Exception as e:
            print_error(f"Failed to pull invoices: {e}")
            raise typer.Exit(code=1)

    # Display results
    if not invoices:
        print_warning("No invoices found for this period.")
        raise typer.Exit()

    # Segregate into payments / deposits / orders / other
    from bizops.commands._export import segregate_invoices
    buckets = segregate_invoices(invoices)

    from rich.table import Table

    # ── Payments OUT ──
    if buckets["payment"]:
        pay_table = Table(
            title="[bold red]Payments OUT (Zelle & Scheduled)[/bold red]",
            show_lines=False, title_style="bold red",
        )
        pay_table.add_column("#", width=3, style="dim")
        pay_table.add_column("Date", width=12)
        pay_table.add_column("Recipient / Vendor", width=25)
        pay_table.add_column("Amount", width=12, justify="right")
        pay_table.add_column("Subject", width=50, style="dim")
        for i, inv in enumerate(buckets["payment"], 1):
            amt = inv.get("amount") or 0
            pay_table.add_row(
                str(i), inv.get("date", ""), inv.get("vendor", "Unknown"),
                f"${amt:,.2f}", (inv.get("subject") or "")[:50],
            )
        console.print(pay_table)
        pay_total = sum(inv.get("amount") or 0 for inv in buckets["payment"])
        console.print(f"  [bold red]Total Payments OUT: ${pay_total:,.2f}[/bold red]\n")

    # ── Deposits IN ──
    if buckets["deposit"]:
        dep_table = Table(
            title="[bold green]Deposits IN (DoorDash & Confirmations)[/bold green]",
            show_lines=False, title_style="bold green",
        )
        dep_table.add_column("#", width=3, style="dim")
        dep_table.add_column("Date", width=12)
        dep_table.add_column("Source", width=20)
        dep_table.add_column("Amount", width=12, justify="right")
        dep_table.add_column("Subject", width=50, style="dim")
        for i, inv in enumerate(buckets["deposit"], 1):
            amt = inv.get("amount") or 0
            dep_table.add_row(
                str(i), inv.get("date", ""), inv.get("vendor", "Unknown"),
                f"${amt:,.2f}", (inv.get("subject") or "")[:50],
            )
        console.print(dep_table)
        dep_total = sum(inv.get("amount") or 0 for inv in buckets["deposit"])
        console.print(f"  [bold green]Total Deposits IN: ${dep_total:,.2f}[/bold green]\n")

    # ── Orders ──
    if buckets["order"]:
        ord_table = Table(
            title="[bold blue]Orders, Statements & Confirmations[/bold blue]",
            show_lines=False, title_style="bold blue",
        )
        ord_table.add_column("#", width=3, style="dim")
        ord_table.add_column("Date", width=12)
        ord_table.add_column("Vendor", width=20)
        ord_table.add_column("Amount", width=12, justify="right")
        ord_table.add_column("Subject", width=55, style="dim")
        for i, inv in enumerate(buckets["order"], 1):
            amt = inv.get("amount") or 0
            ord_table.add_row(
                str(i), inv.get("date", ""), inv.get("vendor", "Unknown"),
                f"${amt:,.2f}", (inv.get("subject") or "")[:55],
            )
        console.print(ord_table)
        ord_total = sum(inv.get("amount") or 0 for inv in buckets["order"])
        console.print(f"  [bold blue]Total Orders: ${ord_total:,.2f}[/bold blue]\n")

    # ── Cash Flow Summary ──
    pay_total = sum(inv.get("amount") or 0 for inv in buckets.get("payment", []))
    dep_total = sum(inv.get("amount") or 0 for inv in buckets.get("deposit", []))
    net = dep_total - pay_total

    total_relevant = len(buckets.get("payment", [])) + len(buckets.get("deposit", [])) + len(buckets.get("order", []))

    summary = create_summary_panel(
        "Cash Flow Summary",
        {
            "Total Processed": f"{total_relevant} (skipped {len(invoices) - total_relevant} spam/promo)",
            "Payments OUT": f"${pay_total:,.2f}  ({len(buckets.get('payment', []))} txns)",
            "Deposits IN": f"${dep_total:,.2f}  ({len(buckets.get('deposit', []))} txns)",
            "Orders/Statements": f"{len(buckets.get('order', []))} items",
            "Net Cash Flow": f"${net:,.2f}",
        },
    )
    console.print(summary)

    # Save to local JSON storage + export if not dry run
    if not dry_run:
        from bizops.commands._export import export_invoices_to_excel
        from bizops.utils.storage import save_invoices

        # Persist to JSON so `list` and `export` commands can find them
        year_month = start_date[:7]  # e.g. "2026-03"
        storage_path = save_invoices(config, invoices, year_month)
        print_info(f"Saved {len(invoices)} invoice(s) to local storage ({storage_path.name})")

        output_path = export_invoices_to_excel(invoices, config, start_date, end_date)
        print_success(f"Exported to [bold]{output_path}[/bold]")


@app.command("list")
def list_invoices(
    period: TimeRange = typer.Option(
        TimeRange.month,
        "--period", "-p",
        help="Time period to show.",
    ),
    status: StatusFilter = typer.Option(
        StatusFilter.all,
        "--status", "-s",
        help="Filter by payment status.",
    ),
    vendor: str | None = typer.Option(
        None,
        "--vendor", "-v",
        help="Filter by vendor name.",
    ),
):
    """
    List previously processed invoices.

    Examples:
        bizops invoices list --period month --status unpaid
        bizops invoices list --vendor "restaurant depot"
    """
    config = load_config()
    start_date, end_date = _resolve_date_range(period, None, None)

    # Load from local storage
    from bizops.utils.storage import load_invoices

    invoices = load_invoices(config, start_date, end_date)

    # Apply filters
    if status != StatusFilter.all:
        invoices = [inv for inv in invoices if inv.get("status") == status.value]

    if vendor:
        vendor_lower = vendor.lower()
        invoices = [
            inv
            for inv in invoices
            if vendor_lower in inv.get("vendor", "").lower()
        ]

    if not invoices:
        print_warning("No invoices match your filters.")
        raise typer.Exit()

    table = create_invoice_table(invoices)
    console.print(table)


@app.command("export")
def export_command(
    period: TimeRange = typer.Option(
        TimeRange.month,
        "--period", "-p",
        help="Time period to export.",
    ),
    output: Path | None = typer.Option(
        None,
        "--output", "-o",
        help="Output file path (default: auto-generated).",
    ),
    format: str = typer.Option(
        "xlsx",
        "--format", "-f",
        help="Output format: xlsx or csv.",
    ),
):
    """
    Export invoices to Excel or CSV.

    Examples:
        bizops invoices export --period month --format xlsx
        bizops invoices export --output ./march_invoices.xlsx
    """
    config = load_config()
    start_date, end_date = _resolve_date_range(period, None, None)

    from bizops.utils.storage import load_invoices

    invoices = load_invoices(config, start_date, end_date)

    if not invoices:
        print_warning("No invoices to export.")
        raise typer.Exit()

    from bizops.commands._export import export_invoices_to_excel

    output_path = export_invoices_to_excel(
        invoices, config, start_date, end_date, output_path=output
    )
    print_success(f"Exported {len(invoices)} invoices to [bold]{output_path}[/bold]")


def _resolve_date_range(
    period: TimeRange,
    since: str | None,
    until: str | None,
) -> tuple[str, str]:
    """Convert period enum or custom dates to start/end date strings."""
    today = datetime.now()

    if since and until:
        return since, until

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
        # Default to current month
        start = today.replace(day=1)
        return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
