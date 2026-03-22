"""Smart alerts CLI commands — proactive anomaly detection."""

from __future__ import annotations

from enum import StrEnum

import typer
from rich.console import Console

from bizops.utils.config import load_config
from bizops.utils.display import create_alerts_panel, get_spinner, print_info

console = Console()
app = typer.Typer(no_args_is_help=True)


class TimeRange(StrEnum):
    month = "month"
    quarter = "quarter"


def _resolve_date_range(period: TimeRange) -> tuple[str, str]:
    """Convert time range to start/end date strings."""
    from datetime import datetime

    today = datetime.now()
    if period == TimeRange.quarter:
        q_start_month = ((today.month - 1) // 3) * 3 + 1
        start = today.replace(month=q_start_month, day=1)
        return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
    else:
        start = today.replace(day=1)
        return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")


def _prev_period(start: str, end: str) -> tuple[str, str]:
    """Get the equivalent previous period dates."""
    from datetime import datetime, timedelta

    s = datetime.strptime(start, "%Y-%m-%d")
    e = datetime.strptime(end, "%Y-%m-%d")
    duration = (e - s).days
    prev_end = s - timedelta(days=1)
    prev_start = prev_end - timedelta(days=duration)
    return prev_start.strftime("%Y-%m-%d"), prev_end.strftime("%Y-%m-%d")


@app.command("scan")
def scan_alerts(
    period: TimeRange = typer.Option(TimeRange.month, "--period", "-p"),
) -> None:
    """Scan all data sources for anomalies and warnings."""
    from bizops.parsers.alerts import AlertEngine
    from bizops.utils.storage import load_bank_transactions, load_invoices, load_toast_reports

    config = load_config()
    start, end = _resolve_date_range(period)

    with get_spinner() as spinner:
        spinner.add_task("Scanning for anomalies...", total=None)

        bank_txns = load_bank_transactions(config, start, end)
        toast = load_toast_reports(config, start, end)
        invoices = load_invoices(config, start, end)

        # Load previous period for comparison
        prev_start, prev_end = _prev_period(start, end)
        prev_bank = load_bank_transactions(config, prev_start, prev_end)
        prev_toast = load_toast_reports(config, prev_start, prev_end)

        engine = AlertEngine(config)
        alerts = engine.scan_all(bank_txns, toast, invoices, prev_bank, prev_toast)

    console.print(create_alerts_panel(alerts))

    if not alerts:
        print_info("All clear — no anomalies detected.")


@app.callback()
def main():
    """Smart alerts — proactive anomaly detection for your business."""
    pass
