"""Local storage for processed invoices and expenses.

Stores data as JSON files organized by month in the output directory.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from bizops.utils.config import BizOpsConfig


def _get_storage_path(config: BizOpsConfig, year_month: str) -> Path:
    """Get the JSON storage file path for a given month."""
    storage_dir = config.output_dir / "data"
    storage_dir.mkdir(parents=True, exist_ok=True)
    return storage_dir / f"invoices_{year_month}.json"


def save_invoices(
    config: BizOpsConfig,
    invoices: list[dict[str, Any]],
    year_month: str | None = None,
) -> Path:
    """Save processed invoices to local JSON storage.

    Args:
        config: BizOps configuration.
        invoices: List of invoice dicts.
        year_month: YYYY-MM string (defaults to current month).

    Returns:
        Path to the saved file.
    """
    if year_month is None:
        year_month = datetime.now().strftime("%Y-%m")

    path = _get_storage_path(config, year_month)

    # Load existing data and merge
    existing = _load_json(path)
    existing_ids = {inv.get("message_id") for inv in existing if inv.get("message_id")}

    # Add only new invoices
    new_count = 0
    for inv in invoices:
        if inv.get("message_id") and inv["message_id"] not in existing_ids:
            existing.append(inv)
            new_count += 1

    _save_json(path, existing)
    return path


def load_invoices(
    config: BizOpsConfig,
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    """Load invoices from local storage for a date range.

    Args:
        config: BizOps configuration.
        start_date: YYYY-MM-DD start.
        end_date: YYYY-MM-DD end.

    Returns:
        List of invoice dicts within the date range.
    """
    # Determine which months to load
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    all_invoices = []
    current = start.replace(day=1)
    while current <= end:
        year_month = current.strftime("%Y-%m")
        path = _get_storage_path(config, year_month)
        all_invoices.extend(_load_json(path))

        # Move to next month
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

    # Filter by exact date range
    filtered = []
    for inv in all_invoices:
        inv_date = inv.get("date", "")
        if inv_date and start_date <= inv_date <= end_date:
            filtered.append(inv)

    return filtered


# ──────────────────────────────────────────────────────────────
#  Toast POS storage
# ──────────────────────────────────────────────────────────────

def _get_toast_storage_path(config: BizOpsConfig, year_month: str) -> Path:
    """Get the JSON storage file path for Toast POS data."""
    storage_dir = config.output_dir / "data"
    storage_dir.mkdir(parents=True, exist_ok=True)
    return storage_dir / f"toast_{year_month}.json"


def save_toast_reports(
    config: BizOpsConfig,
    reports: list[dict[str, Any]],
    year_month: str | None = None,
) -> Path:
    """Save Toast POS daily reports to local JSON storage."""
    if year_month is None:
        year_month = datetime.now().strftime("%Y-%m")

    path = _get_toast_storage_path(config, year_month)
    existing = _load_json(path)
    existing_ids = {r.get("message_id") for r in existing if r.get("message_id")}

    for report in reports:
        if report.get("message_id") and report["message_id"] not in existing_ids:
            existing.append(report)

    _save_json(path, existing)
    return path


def load_toast_reports(
    config: BizOpsConfig,
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    """Load Toast POS reports from local storage for a date range."""
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    all_reports: list[dict[str, Any]] = []
    current = start.replace(day=1)
    while current <= end:
        year_month = current.strftime("%Y-%m")
        path = _get_toast_storage_path(config, year_month)
        all_reports.extend(_load_json(path))
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

    return [
        r for r in all_reports
        if r.get("date") and start_date <= r["date"] <= end_date
    ]


# ──────────────────────────────────────────────────────────────
#  Expense / P&L storage
# ──────────────────────────────────────────────────────────────

def _get_expense_storage_path(config: BizOpsConfig, year_month: str) -> Path:
    """Get the JSON storage file path for expense data."""
    storage_dir = config.output_dir / "data"
    storage_dir.mkdir(parents=True, exist_ok=True)
    return storage_dir / f"expenses_{year_month}.json"


def save_expenses(
    config: BizOpsConfig,
    expense_data: dict[str, Any],
    year_month: str | None = None,
) -> Path:
    """Save categorized expense data (P&L result) to local JSON storage."""
    if year_month is None:
        year_month = datetime.now().strftime("%Y-%m")

    path = _get_expense_storage_path(config, year_month)
    # Expense data is a single dict (the full P&L result), not a list
    _save_json_dict(path, expense_data)
    return path


def load_expenses(
    config: BizOpsConfig,
    year_month: str,
) -> dict[str, Any]:
    """Load categorized expense data from local storage."""
    path = _get_expense_storage_path(config, year_month)
    return _load_json_dict(path)


# ──────────────────────────────────────────────────────────────
#  Bank statement storage
# ──────────────────────────────────────────────────────────────

def _get_bank_storage_path(config: BizOpsConfig, year_month: str) -> Path:
    """Get the JSON storage file path for bank transaction data."""
    storage_dir = config.output_dir / "data"
    storage_dir.mkdir(parents=True, exist_ok=True)
    return storage_dir / f"bank_{year_month}.json"


def save_bank_transactions(
    config: BizOpsConfig,
    transactions: list[dict[str, Any]],
    year_month: str | None = None,
) -> Path:
    """Save bank transactions to local JSON storage.

    Deduplicates by date + description + amount composite key.
    """
    if year_month is None:
        year_month = datetime.now().strftime("%Y-%m")

    path = _get_bank_storage_path(config, year_month)
    existing = _load_json(path)

    # Build dedup keys from existing
    existing_keys = {
        (t.get("date", ""), t.get("raw_description", ""), t.get("amount", 0))
        for t in existing
    }

    for txn in transactions:
        key = (txn.get("date", ""), txn.get("raw_description", ""), txn.get("amount", 0))
        if key not in existing_keys:
            existing.append(txn)
            existing_keys.add(key)

    _save_json(path, existing)
    return path


def load_bank_transactions(
    config: BizOpsConfig,
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    """Load bank transactions from local storage for a date range."""
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    all_txns: list[dict[str, Any]] = []
    current = start.replace(day=1)
    while current <= end:
        year_month = current.strftime("%Y-%m")
        path = _get_bank_storage_path(config, year_month)
        all_txns.extend(_load_json(path))
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

    return [
        t for t in all_txns
        if t.get("date") and start_date <= t["date"] <= end_date
    ]


# ──────────────────────────────────────────────────────────────
#  Reconciliation storage
# ──────────────────────────────────────────────────────────────

def _get_reconciliation_storage_path(config: BizOpsConfig, year_month: str) -> Path:
    """Get the JSON storage file path for reconciliation results."""
    storage_dir = config.output_dir / "data"
    storage_dir.mkdir(parents=True, exist_ok=True)
    return storage_dir / f"reconciliation_{year_month}.json"


def save_reconciliation(
    config: BizOpsConfig,
    result: dict[str, Any],
    year_month: str | None = None,
) -> Path:
    """Save reconciliation result to local JSON storage."""
    if year_month is None:
        year_month = datetime.now().strftime("%Y-%m")

    path = _get_reconciliation_storage_path(config, year_month)
    _save_json_dict(path, result)
    return path


def load_reconciliation(
    config: BizOpsConfig,
    year_month: str,
) -> dict[str, Any]:
    """Load reconciliation result from local storage."""
    path = _get_reconciliation_storage_path(config, year_month)
    return _load_json_dict(path)


# ──────────────────────────────────────────────────────────────
#  Food cost storage
# ──────────────────────────────────────────────────────────────

def _get_food_cost_storage_path(config: BizOpsConfig, year_month: str) -> Path:
    """Get the JSON storage file path for food cost data."""
    storage_dir = config.output_dir / "data"
    storage_dir.mkdir(parents=True, exist_ok=True)
    return storage_dir / f"food_cost_{year_month}.json"


def save_food_cost(
    config: BizOpsConfig,
    data: dict[str, Any],
    year_month: str | None = None,
) -> Path:
    """Save food cost snapshot to local JSON storage."""
    if year_month is None:
        year_month = datetime.now().strftime("%Y-%m")
    path = _get_food_cost_storage_path(config, year_month)
    _save_json_dict(path, data)
    return path


def load_food_cost(
    config: BizOpsConfig,
    year_month: str,
) -> dict[str, Any]:
    """Load food cost snapshot from local storage."""
    path = _get_food_cost_storage_path(config, year_month)
    return _load_json_dict(path)


# ──────────────────────────────────────────────────────────────
#  Orders storage
# ──────────────────────────────────────────────────────────────

def _get_orders_storage_path(config: BizOpsConfig, year_month: str) -> Path:
    """Get the JSON storage file path for generated orders."""
    storage_dir = config.output_dir / "data"
    storage_dir.mkdir(parents=True, exist_ok=True)
    return storage_dir / f"orders_{year_month}.json"


def save_orders(
    config: BizOpsConfig,
    orders: list[dict[str, Any]],
    year_month: str | None = None,
) -> Path:
    """Save generated orders to local JSON storage."""
    if year_month is None:
        year_month = datetime.now().strftime("%Y-%m")
    path = _get_orders_storage_path(config, year_month)

    existing = _load_json(path)
    existing.extend(orders)
    _save_json(path, existing)
    return path


def load_orders(
    config: BizOpsConfig,
    year_month: str,
) -> list[dict[str, Any]]:
    """Load generated orders from local storage."""
    path = _get_orders_storage_path(config, year_month)
    return _load_json(path)


# ──────────────────────────────────────────────────────────────
#  Labor cost storage
# ──────────────────────────────────────────────────────────────

def _get_labor_storage_path(config: BizOpsConfig, year_month: str) -> Path:
    """Get the JSON storage file path for labor cost data."""
    storage_dir = config.output_dir / "data"
    storage_dir.mkdir(parents=True, exist_ok=True)
    return storage_dir / f"labor_{year_month}.json"


def save_labor(
    config: BizOpsConfig,
    data: dict[str, Any],
    year_month: str | None = None,
) -> Path:
    """Save labor cost snapshot to local JSON storage."""
    if year_month is None:
        year_month = datetime.now().strftime("%Y-%m")
    path = _get_labor_storage_path(config, year_month)
    _save_json_dict(path, data)
    return path


def load_labor(
    config: BizOpsConfig,
    year_month: str,
) -> dict[str, Any]:
    """Load labor cost snapshot from local storage."""
    path = _get_labor_storage_path(config, year_month)
    return _load_json_dict(path)


# ──────────────────────────────────────────────────────────────
#  Daily briefing storage
# ──────────────────────────────────────────────────────────────

def _get_briefing_storage_path(config: BizOpsConfig, date_str: str) -> Path:
    """Get the JSON storage file path for a daily briefing."""
    storage_dir = config.output_dir / "data"
    storage_dir.mkdir(parents=True, exist_ok=True)
    return storage_dir / f"briefing_{date_str}.json"


def save_briefing(
    config: BizOpsConfig,
    data: dict[str, Any],
    date_str: str | None = None,
) -> Path:
    """Save daily briefing to local JSON storage."""
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    path = _get_briefing_storage_path(config, date_str)
    _save_json_dict(path, data)
    return path


def load_briefing(
    config: BizOpsConfig,
    date_str: str,
) -> dict[str, Any]:
    """Load daily briefing from local storage."""
    path = _get_briefing_storage_path(config, date_str)
    return _load_json_dict(path)


# ──────────────────────────────────────────────────────────────
#  Internal helpers
# ──────────────────────────────────────────────────────────────

def _load_json(path: Path) -> list[dict[str, Any]]:
    """Load JSON file, returning empty list if not found."""
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, ValueError):
        return []


def _save_json(path: Path, data: list[dict[str, Any]]) -> None:
    """Save list data to JSON file."""
    path.write_text(json.dumps(data, indent=2, default=str))


def _load_json_dict(path: Path) -> dict[str, Any]:
    """Load JSON file as a dict, returning empty dict if not found."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, ValueError):
        return {}


def _save_json_dict(path: Path, data: dict[str, Any]) -> None:
    """Save dict data to JSON file."""
    path.write_text(json.dumps(data, indent=2, default=str))
