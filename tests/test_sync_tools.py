"""Tests for MCP sync tools — sync_gmail, sync_status, sync_toast, data_freshness."""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bizops.mcp_server import (
    _data_freshness,
    sync_gmail,
    sync_status,
    sync_toast,
)
from bizops.utils.config import BizOpsConfig, VendorConfig


@pytest.fixture
def tmp_output_dir(tmp_path):
    """Create a temp directory structure matching BizOps storage layout."""
    data_dir = tmp_path / "output" / "data"
    data_dir.mkdir(parents=True)
    return tmp_path


@pytest.fixture
def config_with_tmp(tmp_output_dir):
    """BizOpsConfig pointing to temp directory."""
    return BizOpsConfig(
        output_dir=tmp_output_dir / "output",
        vendors=[
            VendorConfig(name="Sysco", email_patterns=["sysco.com"], category="food_supplies"),
        ],
    )


# ── sync_gmail ───────────────────────────────────────────────


class TestSyncGmail:
    @patch("bizops.mcp_server.load_invoices")
    @patch("bizops.mcp_server.load_config")
    def test_successful_sync(self, mock_config, mock_load_inv):
        """sync_gmail should fetch emails, parse, dedup, save, and return summary."""
        mock_config.return_value = BizOpsConfig()
        mock_load_inv.return_value = [
            {"vendor": "Sysco", "amount": 500, "date": "2026-03-25"},
        ]

        raw_emails = [
            {"subject": "Invoice", "sender": "sysco@sysco.com", "date": "2026-03-25", "body": "Total: $500.00", "vendor": "Sysco", "message_id": "abc123", "attachments": []},
        ]
        parsed_invoices = [
            {"vendor": "Sysco", "amount": 500, "date": "2026-03-25", "message_id": "abc123", "subject": "Invoice"},
        ]

        with patch("bizops.connectors.gmail.GmailConnector") as MockGmail, \
             patch("bizops.parsers.invoice.InvoiceParser") as MockParser, \
             patch("bizops.utils.storage.save_invoices") as mock_save, \
             patch("bizops.commands._export.segregate_invoices", return_value={"payment": parsed_invoices}), \
             patch("bizops.parsers.expenses.ExpenseEngine") as MockExpense, \
             patch("bizops.utils.storage.load_toast_reports", return_value=[]), \
             patch("bizops.utils.storage.save_expenses"):

            mock_gmail_instance = MockGmail.return_value
            mock_gmail_instance.search_invoices.return_value = raw_emails

            mock_parser_instance = MockParser.return_value
            mock_parser_instance.parse_emails.return_value = parsed_invoices
            mock_parser_instance.deduplicate.return_value = parsed_invoices

            mock_expense_instance = MockExpense.return_value
            mock_expense_instance.categorize_all.return_value = {"expenses_by_category": {}}

            result = json.loads(sync_gmail(period="week"))

        assert result["status"] == "success"
        assert result["invoices"]["new"] == 1
        assert "Sysco" in result["invoices"]["vendors"]
        assert "synced_at" in result

    @patch("bizops.mcp_server.load_config")
    def test_missing_credentials(self, mock_config):
        """sync_gmail should handle missing Gmail credentials gracefully."""
        mock_config.return_value = BizOpsConfig()

        with patch("bizops.connectors.gmail.GmailConnector", side_effect=FileNotFoundError("no credentials")):
            result = json.loads(sync_gmail(period="week"))

        assert result["status"] == "error"
        assert len(result["errors"]) > 0
        assert "credentials" in result["errors"][0].lower()

    @patch("bizops.mcp_server.load_config")
    def test_api_error(self, mock_config):
        """sync_gmail should catch generic exceptions and return error."""
        mock_config.return_value = BizOpsConfig()

        with patch("bizops.connectors.gmail.GmailConnector", side_effect=RuntimeError("API quota exceeded")):
            result = json.loads(sync_gmail(period="today"))

        assert result["status"] == "error"
        assert any("API quota" in e for e in result["errors"])

    @patch("bizops.mcp_server.load_invoices")
    @patch("bizops.mcp_server.load_config")
    def test_empty_results(self, mock_config, mock_load_inv):
        """sync_gmail should handle no emails found gracefully."""
        mock_config.return_value = BizOpsConfig()
        mock_load_inv.return_value = []

        with patch("bizops.connectors.gmail.GmailConnector") as MockGmail, \
             patch("bizops.parsers.invoice.InvoiceParser") as MockParser, \
             patch("bizops.utils.storage.save_invoices"), \
             patch("bizops.commands._export.segregate_invoices", return_value={"payment": []}), \
             patch("bizops.parsers.expenses.ExpenseEngine") as MockExpense, \
             patch("bizops.utils.storage.load_toast_reports", return_value=[]), \
             patch("bizops.utils.storage.save_expenses"):

            MockGmail.return_value.search_invoices.return_value = []
            MockParser.return_value.parse_emails.return_value = []
            MockParser.return_value.deduplicate.return_value = []
            MockExpense.return_value.categorize_all.return_value = {}

            result = json.loads(sync_gmail(period="today"))

        assert result["status"] == "success"
        assert result["invoices"]["new"] == 0

    @patch("bizops.mcp_server.load_invoices")
    @patch("bizops.mcp_server.load_config")
    def test_period_parameter(self, mock_config, mock_load_inv):
        """sync_gmail should accept different period values."""
        mock_config.return_value = BizOpsConfig()
        mock_load_inv.return_value = []

        with patch("bizops.connectors.gmail.GmailConnector") as MockGmail, \
             patch("bizops.parsers.invoice.InvoiceParser") as MockParser, \
             patch("bizops.utils.storage.save_invoices"), \
             patch("bizops.commands._export.segregate_invoices", return_value={"payment": []}), \
             patch("bizops.parsers.expenses.ExpenseEngine") as MockExpense, \
             patch("bizops.utils.storage.load_toast_reports", return_value=[]), \
             patch("bizops.utils.storage.save_expenses"):

            MockGmail.return_value.search_invoices.return_value = []
            MockParser.return_value.parse_emails.return_value = []
            MockParser.return_value.deduplicate.return_value = []
            MockExpense.return_value.categorize_all.return_value = {}

            for period in ["today", "week", "month", "quarter"]:
                result = json.loads(sync_gmail(period=period))
                assert result["status"] == "success"
                assert "period" in result


# ── sync_status ──────────────────────────────────────────────


class TestSyncStatus:
    @patch("bizops.mcp_server.load_config")
    def test_fresh_data(self, mock_config, tmp_output_dir):
        """sync_status should report fresh for recently modified files."""
        mock_config.return_value = BizOpsConfig(output_dir=tmp_output_dir / "output")
        data_dir = tmp_output_dir / "output" / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        # Create a fresh invoices file
        year_month = datetime.now().strftime("%Y-%m")
        (data_dir / f"invoices_{year_month}.json").write_text("[]")

        result = json.loads(sync_status())

        assert result["files"]["invoices"]["exists"] is True
        assert result["files"]["invoices"]["freshness"] == "fresh"
        assert result["files"]["invoices"]["hours_ago"] < 1

    @patch("bizops.mcp_server.load_config")
    def test_missing_data(self, mock_config, tmp_output_dir):
        """sync_status should report missing for non-existent files."""
        mock_config.return_value = BizOpsConfig(output_dir=tmp_output_dir / "output")
        data_dir = tmp_output_dir / "output" / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        result = json.loads(sync_status())

        assert result["files"]["invoices"]["exists"] is False
        assert result["files"]["invoices"]["freshness"] == "missing"
        assert "invoices" in result["stale_data_types"]

    @patch("bizops.mcp_server.load_config")
    def test_stale_data(self, mock_config, tmp_output_dir):
        """sync_status should report stale for old files."""
        mock_config.return_value = BizOpsConfig(output_dir=tmp_output_dir / "output")
        data_dir = tmp_output_dir / "output" / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        year_month = datetime.now().strftime("%Y-%m")
        filepath = data_dir / f"invoices_{year_month}.json"
        filepath.write_text("[]")

        # Set mtime to 4 days ago
        old_time = time.time() - (4 * 24 * 3600)
        os.utime(filepath, (old_time, old_time))

        result = json.loads(sync_status())

        assert result["files"]["invoices"]["freshness"] == "very_stale"
        assert result["overall_status"] == "stale"
        assert "sync_gmail" in result["recommendation"].lower()

    @patch("bizops.mcp_server.load_config")
    def test_has_recommendation(self, mock_config, tmp_output_dir):
        """sync_status should include a recommendation."""
        mock_config.return_value = BizOpsConfig(output_dir=tmp_output_dir / "output")
        data_dir = tmp_output_dir / "output" / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        result = json.loads(sync_status())

        assert "recommendation" in result
        assert "checked_at" in result


# ── sync_toast ───────────────────────────────────────────────


class TestSyncToast:
    def test_returns_not_automated(self):
        result = json.loads(sync_toast())

        assert result["status"] == "not_automated"
        assert len(result["workarounds"]) >= 2
        assert "manual_command" in result


# ── _data_freshness ──────────────────────────────────────────


class TestDataFreshness:
    @patch("bizops.mcp_server.load_config")
    def test_fresh_file(self, mock_config, tmp_output_dir):
        mock_config.return_value = BizOpsConfig(output_dir=tmp_output_dir / "output")
        data_dir = tmp_output_dir / "output" / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        year_month = datetime.now().strftime("%Y-%m")
        (data_dir / f"invoices_{year_month}.json").write_text("[]")

        result = _data_freshness("invoices")

        assert result["status"] == "fresh"
        assert result["hours_ago"]["invoices"] < 1
        assert "suggestion" not in result

    @patch("bizops.mcp_server.load_config")
    def test_missing_file(self, mock_config, tmp_output_dir):
        mock_config.return_value = BizOpsConfig(output_dir=tmp_output_dir / "output")
        data_dir = tmp_output_dir / "output" / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        result = _data_freshness("invoices")

        assert result["status"] == "no_data"
        assert result["hours_ago"]["invoices"] is None
        assert "suggestion" in result

    @patch("bizops.mcp_server.load_config")
    def test_stale_file(self, mock_config, tmp_output_dir):
        mock_config.return_value = BizOpsConfig(output_dir=tmp_output_dir / "output")
        data_dir = tmp_output_dir / "output" / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        year_month = datetime.now().strftime("%Y-%m")
        filepath = data_dir / f"invoices_{year_month}.json"
        filepath.write_text("[]")

        # Set mtime to 48 hours ago
        old_time = time.time() - (48 * 3600)
        os.utime(filepath, (old_time, old_time))

        result = _data_freshness("invoices")

        assert result["status"] == "stale"
        assert result["hours_ago"]["invoices"] >= 47
        assert "suggestion" in result

    @patch("bizops.mcp_server.load_config")
    def test_different_data_types(self, mock_config, tmp_output_dir):
        mock_config.return_value = BizOpsConfig(output_dir=tmp_output_dir / "output")
        data_dir = tmp_output_dir / "output" / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        for data_type in ["invoices", "expenses", "toast", "bank", "food_cost", "labor"]:
            result = _data_freshness(data_type)
            assert "status" in result


# ── data_freshness in get_* tools ────────────────────────────


class TestFreshnessInGetTools:
    @patch("bizops.mcp_server._data_freshness")
    @patch("bizops.mcp_server.load_invoices")
    @patch("bizops.mcp_server.load_config")
    def test_get_invoices_has_freshness(self, mock_config, mock_load, mock_fresh):
        from bizops.mcp_server import get_invoices

        mock_config.return_value = BizOpsConfig()
        mock_load.return_value = []
        mock_fresh.return_value = {"status": "stale", "hours_ago": {"invoices": 48}}

        result = json.loads(get_invoices())
        assert "data_freshness" in result
        assert result["data_freshness"]["status"] == "stale"

    @patch("bizops.mcp_server._data_freshness")
    @patch("bizops.mcp_server.load_expenses")
    @patch("bizops.mcp_server.load_config")
    def test_get_expenses_has_freshness(self, mock_config, mock_load, mock_fresh):
        from bizops.mcp_server import get_expenses

        mock_config.return_value = BizOpsConfig()
        mock_load.return_value = {
            "revenue": {}, "totals": {},
            "expenses_by_category": {"food": [{"amount": 100, "vendor": "X"}]},
        }
        mock_fresh.return_value = {"status": "fresh", "hours_ago": {"expenses": 1}}

        result = json.loads(get_expenses())
        assert "data_freshness" in result

    @patch("bizops.mcp_server._data_freshness")
    @patch("bizops.mcp_server.load_toast_reports")
    @patch("bizops.mcp_server.load_config")
    def test_get_toast_has_freshness(self, mock_config, mock_load, mock_fresh):
        from bizops.mcp_server import get_toast_sales

        mock_config.return_value = BizOpsConfig()
        mock_load.return_value = [
            {"date": "2026-03-01", "gross_sales": 5000, "net_sales": 4700, "tax": 300, "tips": 400, "total_orders": 120},
        ]
        mock_fresh.return_value = {"status": "fresh", "hours_ago": {"toast": 0.5}}

        result = json.loads(get_toast_sales())
        assert "data_freshness" in result

    @patch("bizops.mcp_server._data_freshness")
    @patch("bizops.mcp_server.load_bank_transactions")
    @patch("bizops.mcp_server.load_config")
    def test_get_bank_has_freshness(self, mock_config, mock_load, mock_fresh):
        from bizops.mcp_server import get_bank_transactions

        mock_config.return_value = BizOpsConfig()
        mock_load.return_value = []
        mock_fresh.return_value = {"status": "no_data", "hours_ago": {"bank": None}}

        result = json.loads(get_bank_transactions())
        assert "data_freshness" in result
