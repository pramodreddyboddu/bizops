"""Bank statement commands — import, reconcile, and analyze cash flow."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path

import typer
from rich.console import Console

from bizops.utils.config import load_config
from bizops.utils.display import (
    create_bank_txn_table,
    create_cash_flow_table,
    create_reconciliation_panel,
    get_spinner,
    print_error,
    print_info,
    print_success,
    print_warning,
)

console = Console()
app = typer.Typer(no_args_is_help=True)


class TimeRange(StrEnum):
    """Time range for queries."""

    today = "today"
    week = "week"
    month = "month"
    quarter = "quarter"


def _resolve_date_range(period: TimeRange) -> tuple[str, str]:
    """Convert a time range to start/end date strings."""
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
    else:  # month
        start = today.replace(day=1)
        return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")


@app.command("import")
def import_statement(
    file: Path = typer.Option(
        ...,
        "--file", "-f",
        help="Path to bank statement file (CSV or PDF).",
        exists=True,
    ),
    period: str | None = typer.Option(
        None,
        "--period",
        help="Year-month tag for storage (YYYY-MM). Auto-detected if omitted.",
    ),
) -> None:
    """Import a bank statement from CSV or PDF file."""
    from bizops.parsers.bank_statement import BankStatementParser
    from bizops.utils.storage import save_bank_transactions

    config = load_config()

    with get_spinner() as spinner:
        spinner.add_task("Parsing bank statement...", total=None)

        parser = BankStatementParser(config)
        try:
            transactions = parser.parse_file(file)
        except ValueError as e:
            print_error(str(e))
            raise typer.Exit(1)
        except ImportError as e:
            print_error(str(e))
            raise typer.Exit(1)

    if not transactions:
        print_warning("No transactions found in the file.")
        raise typer.Exit(0)

    # Determine year-month for storage
    if period is None:
        # Use the most common month from the transactions
        months: dict[str, int] = {}
        for txn in transactions:
            m = txn.get("date", "")[:7]
            if m:
                months[m] = months.get(m, 0) + 1
        period = max(months, key=months.get) if months else datetime.now().strftime("%Y-%m")

    # Save
    path = save_bank_transactions(config, transactions, period)

    # Display
    debits = [t for t in transactions if t.get("type") == "debit"]
    credits = [t for t in transactions if t.get("type") == "credit"]
    total_debits = sum(t.get("amount", 0) for t in debits)
    total_credits = sum(t.get("amount", 0) for t in credits)

    console.print(create_bank_txn_table(transactions, f"Imported from {file.name}"))
    console.print()

    print_success(f"Imported {len(transactions)} transactions from {file.name}")
    print_info(f"  Debits:  {len(debits)} (${abs(total_debits):,.2f})")
    print_info(f"  Credits: {len(credits)} (${total_credits:,.2f})")
    print_info(f"  Saved to: {path}")


@app.command("list")
def list_transactions(
    period: TimeRange = typer.Option(
        TimeRange.month,
        "--period", "-p",
        help="Time period to list.",
    ),
    txn_type: str | None = typer.Option(
        None,
        "--type", "-t",
        help="Filter by type: credit, debit, or all.",
    ),
    category: str | None = typer.Option(
        None,
        "--category", "-c",
        help="Filter by category.",
    ),
    unreconciled: bool = typer.Option(
        False,
        "--unreconciled",
        help="Show only unreconciled transactions.",
    ),
) -> None:
    """List imported bank transactions."""
    from bizops.utils.storage import load_bank_transactions

    config = load_config()
    start, end = _resolve_date_range(period)
    transactions = load_bank_transactions(config, start, end)

    if not transactions:
        print_warning(f"No bank transactions found for {period.value}. Run 'bizops bank import' first.")
        raise typer.Exit(0)

    # Apply filters
    if txn_type and txn_type != "all":
        transactions = [t for t in transactions if t.get("type") == txn_type]

    if category:
        cat_lower = category.lower()
        transactions = [t for t in transactions if cat_lower in (t.get("category") or "").lower()]

    if unreconciled:
        transactions = [t for t in transactions if not t.get("reconciled")]

    if not transactions:
        print_warning("No transactions match your filters.")
        raise typer.Exit(0)

    console.print(create_bank_txn_table(transactions, f"Bank Transactions ({start} to {end})"))
    print_info(f"Showing {len(transactions)} transactions")


@app.command("reconcile")
def reconcile(
    period: TimeRange = typer.Option(
        TimeRange.month,
        "--period", "-p",
        help="Time period to reconcile.",
    ),
    tolerance_days: int = typer.Option(
        3,
        "--tolerance-days",
        help="Max days between bank and invoice dates for matching.",
    ),
    tolerance_amount: float = typer.Option(
        0.01,
        "--tolerance-amount",
        help="Max amount difference for matching.",
    ),
) -> None:
    """Reconcile bank transactions against Gmail invoice data."""
    from bizops.commands._export import segregate_invoices
    from bizops.parsers.reconciliation import ReconciliationEngine
    from bizops.utils.storage import (
        load_bank_transactions,
        load_invoices,
        save_reconciliation,
    )

    config = load_config()
    start, end = _resolve_date_range(period)

    with get_spinner() as spinner:
        spinner.add_task("Loading data...", total=None)

        bank_txns = load_bank_transactions(config, start, end)
        if not bank_txns:
            print_warning(f"No bank transactions found for {period.value}. Run 'bizops bank import' first.")
            raise typer.Exit(0)

        raw_invoices = load_invoices(config, start, end)
        if not raw_invoices:
            print_warning(f"No invoice data found for {period.value}. Run 'bizops invoices pull' first.")
            raise typer.Exit(0)

        # Get only payment invoices for reconciliation
        buckets = segregate_invoices(raw_invoices, config)
        payment_invoices = buckets.get("payment", [])

    with get_spinner() as spinner:
        spinner.add_task("Reconciling...", total=None)

        engine = ReconciliationEngine(config, tolerance_days, tolerance_amount)
        result = engine.reconcile(bank_txns, payment_invoices)
        cash_flow = engine.get_cash_flow(bank_txns)

        year_month = start[:7]
        save_reconciliation(config, result, year_month)

    # Display results
    console.print(create_reconciliation_panel(result))
    console.print()

    # Show unmatched bank transactions (the hidden expenses!)
    unmatched_bank = result.get("unmatched_bank", [])
    if unmatched_bank:
        debit_unmatched = [t for t in unmatched_bank if t.get("type") == "debit"]
        if debit_unmatched:
            console.print(create_bank_txn_table(
                debit_unmatched,
                f"Hidden Expenses (in bank, not in email) — {len(debit_unmatched)} items"
            ))
            total_hidden = sum(abs(t.get("amount", 0)) for t in debit_unmatched)
            print_warning(f"${total_hidden:,.2f} in expenses not captured by email invoices!")
            console.print()

    # Show unmatched invoices
    unmatched_inv = result.get("unmatched_invoices", [])
    if unmatched_inv:
        print_warning(f"{len(unmatched_inv)} invoices not found in bank statement")

    print_success(f"Reconciliation complete — {result['summary']['match_rate']}% match rate")


@app.command("cashflow")
def cashflow(
    period: TimeRange = typer.Option(
        TimeRange.month,
        "--period", "-p",
        help="Time period for cash flow.",
    ),
) -> None:
    """Show complete cash flow from bank data — every dollar in and out."""
    from bizops.parsers.reconciliation import ReconciliationEngine
    from bizops.utils.storage import load_bank_transactions

    config = load_config()
    start, end = _resolve_date_range(period)

    bank_txns = load_bank_transactions(config, start, end)
    if not bank_txns:
        print_warning(f"No bank transactions found for {period.value}. Run 'bizops bank import' first.")
        raise typer.Exit(0)

    engine = ReconciliationEngine(config)
    cash_flow = engine.get_cash_flow(bank_txns)

    console.print(create_cash_flow_table(cash_flow))
    print_info(f"Based on {len(bank_txns)} bank transactions ({start} to {end})")


@app.command("export")
def export_report(
    period: TimeRange = typer.Option(
        TimeRange.month,
        "--period", "-p",
        help="Time period for the report.",
    ),
    output: Path | None = typer.Option(
        None,
        "--output", "-o",
        help="Output file path.",
    ),
) -> None:
    """Export reconciliation report to Excel."""
    from bizops.commands._export import export_reconciliation_workbook
    from bizops.parsers.reconciliation import ReconciliationEngine
    from bizops.utils.storage import load_bank_transactions, load_reconciliation

    config = load_config()
    start, end = _resolve_date_range(period)
    year_month = start[:7]

    # Try loading saved reconciliation first
    result = load_reconciliation(config, year_month)

    if not result:
        # Run reconciliation on the fly
        print_info("No saved reconciliation found. Running reconciliation...")
        from bizops.commands._export import segregate_invoices
        from bizops.utils.storage import load_invoices

        bank_txns = load_bank_transactions(config, start, end)
        if not bank_txns:
            print_error(f"No bank transactions found. Run 'bizops bank import' first.")
            raise typer.Exit(1)

        raw_invoices = load_invoices(config, start, end)
        buckets = segregate_invoices(raw_invoices, config) if raw_invoices else {}
        payment_invoices = buckets.get("payment", [])

        engine = ReconciliationEngine(config)
        result = engine.reconcile(bank_txns, payment_invoices)

    # Get cash flow data
    bank_txns = load_bank_transactions(config, start, end)
    engine = ReconciliationEngine(config)
    cash_flow = engine.get_cash_flow(bank_txns)

    with get_spinner() as spinner:
        spinner.add_task("Generating Excel report...", total=None)
        path = export_reconciliation_workbook(result, cash_flow, config, output)

    print_success(f"Reconciliation report saved to: {path}")
