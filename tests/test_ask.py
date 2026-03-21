"""Tests for the AI-powered ask commands and Anthropic client."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from rich.panel import Panel

from bizops.commands.ask import (
    _display_insights,
    _parse_insight_sections,
    build_data_context,
    build_system_prompt,
)
from bizops.connectors.anthropic_client import AgentClient
from bizops.utils.config import BizOpsConfig, VendorConfig


# ──────────────────────────────────────────────────────────────
#  Fixtures
# ──────────────────────────────────────────────────────────────


@pytest.fixture
def sample_config():
    """A BizOpsConfig with test vendors."""
    return BizOpsConfig(
        vendors=[
            VendorConfig(name="Sysco", email_patterns=["sysco.com"], category="food_supplies"),
            VendorConfig(name="Om Produce", email_patterns=["omproduce"], category="produce"),
            VendorConfig(name="Toast POS", email_patterns=["toasttab.com"], category="pos_reports"),
        ]
    )


@pytest.fixture
def sample_invoices():
    """Sample invoice data for testing."""
    return [
        {
            "vendor": "Sysco",
            "amount": 1250.00,
            "date": "2026-03-01",
            "category": "food_supplies",
            "subject": "Invoice #12345",
        },
        {
            "vendor": "Om Produce",
            "amount": 340.50,
            "date": "2026-03-05",
            "category": "produce",
            "subject": "Weekly produce delivery",
        },
        {
            "vendor": "Sysco",
            "amount": 980.00,
            "date": "2026-03-10",
            "category": "food_supplies",
            "subject": "Invoice #12399",
        },
        {
            "vendor": "AT&T",
            "amount": 189.99,
            "date": "2026-03-03",
            "category": "utilities",
            "subject": "Monthly bill",
        },
    ]


@pytest.fixture
def sample_expenses():
    """Sample expense/P&L data for testing."""
    return {
        "period": {"start": "2026-03-01", "end": "2026-03-21"},
        "revenue": {
            "gross_sales": 15000.00,
            "net_sales": 14200.00,
            "tax": 800.00,
            "tips": 1200.00,
        },
        "expenses_by_category": {
            "food_supplies": [
                {"vendor": "Sysco", "amount": 1250.00, "date": "2026-03-01"},
                {"vendor": "Sysco", "amount": 980.00, "date": "2026-03-10"},
            ],
            "produce": [
                {"vendor": "Om Produce", "amount": 340.50, "date": "2026-03-05"},
            ],
            "utilities": [
                {"vendor": "AT&T", "amount": 189.99, "date": "2026-03-03"},
            ],
        },
        "totals": {
            "total_revenue": 14200.00,
            "total_expenses": 2760.49,
            "net_profit": 11439.51,
        },
    }


# ──────────────────────────────────────────────────────────────
#  Test 1: System prompt includes vendor data
# ──────────────────────────────────────────────────────────────


def test_system_prompt_includes_vendors(sample_config):
    """System prompt should list configured vendors and their categories."""
    data_context = "No data."
    prompt = build_system_prompt(sample_config, data_context)

    assert "Sysco" in prompt
    assert "Om Produce" in prompt
    assert "food_supplies" in prompt
    assert "produce" in prompt
    assert "Desi Delight" in prompt


# ──────────────────────────────────────────────────────────────
#  Test 2: System prompt includes category keywords
# ──────────────────────────────────────────────────────────────


def test_system_prompt_includes_categories(sample_config):
    """System prompt should include expense category keywords."""
    data_context = "No data."
    prompt = build_system_prompt(sample_config, data_context)

    assert "sysco" in prompt.lower()
    assert "restaurant depot" in prompt.lower()
    assert "Expense categories" in prompt


# ──────────────────────────────────────────────────────────────
#  Test 3: Data context is built correctly from invoices
# ──────────────────────────────────────────────────────────────


def test_build_data_context_with_invoices(sample_invoices, sample_expenses):
    """Data context should summarize invoices with vendors and totals."""
    context = build_data_context(sample_invoices, sample_expenses)

    assert "INVOICES (4 total)" in context
    assert "Sysco" in context
    assert "Om Produce" in context
    assert "$2,230.00" in context  # Sysco total: 1250 + 980
    assert "P&L SUMMARY" in context
    assert "$14,200.00" in context  # Net sales


# ──────────────────────────────────────────────────────────────
#  Test 4: Data context handles empty data
# ──────────────────────────────────────────────────────────────


def test_build_data_context_empty():
    """Data context should handle empty invoices and expenses gracefully."""
    context = build_data_context([], {})

    assert "No invoice data available" in context
    assert "No expense data available" in context


# ──────────────────────────────────────────────────────────────
#  Test 5: Missing API key raises helpful error
# ──────────────────────────────────────────────────────────────


def test_missing_api_key_raises_error():
    """AgentClient should raise ValueError when no API key is available."""
    with patch.dict("os.environ", {}, clear=True):
        # Ensure ANTHROPIC_API_KEY is not set
        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
            AgentClient(api_key=None)


# ──────────────────────────────────────────────────────────────
#  Test 6: AgentClient query calls Anthropic API correctly
# ──────────────────────────────────────────────────────────────


@patch.object(AgentClient, "_build_client")
def test_agent_client_query(mock_build):
    """AgentClient.query should call the API and return response text."""
    # Set up mock client and response
    mock_client = MagicMock()
    mock_build.return_value = mock_client

    mock_block = MagicMock()
    mock_block.text = "Total produce spend is $340.50"
    mock_response = MagicMock()
    mock_response.content = [mock_block]
    mock_client.messages.create.return_value = mock_response

    client = AgentClient(api_key="test-key-123")
    result = client.query("You are a helper.", "How much did I spend on produce?")

    assert result == "Total produce spend is $340.50"
    mock_client.messages.create.assert_called_once()
    call_kwargs = mock_client.messages.create.call_args[1]
    assert call_kwargs["model"] == "claude-sonnet-4-20250514"
    assert call_kwargs["system"] == "You are a helper."
    assert call_kwargs["messages"][0]["content"] == "How much did I spend on produce?"


# ──────────────────────────────────────────────────────────────
#  Test 7: AgentClient stream_query yields text chunks
# ──────────────────────────────────────────────────────────────


@patch.object(AgentClient, "_build_client")
def test_agent_client_stream_query(mock_build):
    """AgentClient.stream_query should yield text chunks from stream."""
    mock_client = MagicMock()
    mock_build.return_value = mock_client

    # Mock the streaming context manager
    mock_stream = MagicMock()
    mock_stream.text_stream = iter(["Hello", " there", "!"])
    mock_stream.__enter__ = MagicMock(return_value=mock_stream)
    mock_stream.__exit__ = MagicMock(return_value=False)
    mock_client.messages.stream.return_value = mock_stream

    client = AgentClient(api_key="test-key-123")
    chunks = list(client.stream_query("system", "hello"))

    assert chunks == ["Hello", " there", "!"]
    mock_client.messages.stream.assert_called_once()


# ──────────────────────────────────────────────────────────────
#  Test 8: Insight sections are parsed correctly from markdown
# ──────────────────────────────────────────────────────────────


def test_parse_insight_sections():
    """Markdown response should be split into named sections."""
    response = """\
## Anomalies & Warnings
- Duplicate Sysco charge on March 1 and March 10.
- AT&T bill is higher than usual.

## Spending Trends
- Food supplies account for 80% of expenses.

## Missing or Late Items
- No produce invoices after March 5.

## Cost-Saving Opportunities
- Consider bulk ordering from Sysco.
"""
    sections = _parse_insight_sections(response)

    assert len(sections) == 4
    assert "anomalies_and_warnings" in sections
    assert "spending_trends" in sections
    assert "missing_or_late_items" in sections
    assert "cost-saving_opportunities" in sections
    assert "Duplicate Sysco" in sections["anomalies_and_warnings"]


# ──────────────────────────────────────────────────────────────
#  Test 9: Insights display formats panels correctly
# ──────────────────────────────────────────────────────────────


@patch("bizops.commands.ask.console")
def test_display_insights_creates_panels(mock_console):
    """_display_insights should create colored panels for each section."""
    response = """\
## Anomalies & Warnings
- High charges detected.

## Spending Trends
- Produce costs rising.

## Cost-Saving Opportunities
- Switch vendors for savings.
"""
    _display_insights(response)

    # Should print panels (Panel calls) + blank lines between them
    assert mock_console.print.call_count >= 3

    # Check that Panel objects were created
    panel_calls = [
        call for call in mock_console.print.call_args_list
        if call.args and isinstance(call.args[0], Panel)
    ]
    assert len(panel_calls) >= 3


# ──────────────────────────────────────────────────────────────
#  Test 10: Data context includes date range from invoices
# ──────────────────────────────────────────────────────────────


def test_build_data_context_date_range(sample_invoices):
    """Data context should show the date range from invoices."""
    context = build_data_context(sample_invoices, {})

    assert "2026-03-01" in context
    assert "2026-03-10" in context
    assert "Date range" in context


# ──────────────────────────────────────────────────────────────
#  Test 11: AgentClient uses correct model name
# ──────────────────────────────────────────────────────────────


def test_agent_client_model_constant():
    """AgentClient should use the correct model identifier."""
    assert AgentClient.MODEL == "claude-sonnet-4-20250514"
    assert AgentClient.MAX_TOKENS == 1024
