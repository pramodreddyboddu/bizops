"""Tests for the Toast POS parser module."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from bizops.parsers.toast import ToastPOSParser, TOAST_SENDER


# ---------------------------------------------------------------------------
# Sample email bodies
# ---------------------------------------------------------------------------

SAMPLE_DAILY_SUMMARY = """\
Toast Daily Summary Report
Summary for March 15, 2026

Restaurant: Desi Delight Marketplace

Gross Sales: $4,523.78
Net Sales: $4,123.45
Tax Collected: $345.67
Tips: $612.34
Refunds/Voids: $54.33

Total Orders: 187

Payment Breakdown:
  Cash: $823.50
  Credit Card: $3,245.95
  Other Payments: $54.33

Thank you for using Toast!
"""

SAMPLE_DAILY_REPORT_MINIMAL = """\
Toast Daily Report
Date: 03/15/2026

Gross Sales: $1,200.00
Net Sales: $1,100.00
Tax: $100.00
Tips: $150.00

Total Orders: 42
"""

SAMPLE_MISSING_FIELDS = """\
Toast Daily Summary
Report for 2026-03-15

Gross Sales: $800.00
Net Sales: $750.00

Total Orders: 25
"""

SAMPLE_NO_DOLLAR_SIGNS = """\
Toast Daily Summary
Summary for March 10, 2026

Gross Sales: 2,500.00
Net Sales: 2,300.50
Tax: 199.50
Tips: 310.00
Refunds: 0.00

Total Orders: 95

Cash: 600.00
Credit Card: 1,900.00
"""

SAMPLE_WEIRD_FORMATTING = """\
Toast Daily Summary
   Date:   March 20, 2026

  Gross Sales:   $   3,100.55
  Net Sales   $2,800.00
  Tax Collected:$275.50
  Tips:$400.00
  Refunds/Voids:  $25.05

  187 orders

Payment Breakdown:
  Cash:  $500.00
  Credit Card:$2,575.50
  Other:$25.05
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_email(
    body: str,
    subject: str = "Daily Summary - March 15, 2026",
    sender: str = f"Toast POS <{TOAST_SENDER}>",
    date: str = "2026-03-15",
    message_id: str = "msg_001",
) -> dict:
    return {
        "body": body,
        "subject": subject,
        "sender": sender,
        "date": date,
        "message_id": message_id,
    }


@pytest.fixture
def parser() -> ToastPOSParser:
    return ToastPOSParser()


@pytest.fixture
def standard_email() -> dict:
    return _make_email(SAMPLE_DAILY_SUMMARY)


@pytest.fixture
def minimal_email() -> dict:
    return _make_email(
        SAMPLE_DAILY_REPORT_MINIMAL,
        subject="Daily Report - March 15, 2026",
    )


@pytest.fixture
def missing_fields_email() -> dict:
    return _make_email(SAMPLE_MISSING_FIELDS)


@pytest.fixture
def no_dollar_signs_email() -> dict:
    return _make_email(SAMPLE_NO_DOLLAR_SIGNS)


@pytest.fixture
def weird_formatting_email() -> dict:
    return _make_email(SAMPLE_WEIRD_FORMATTING, subject="Daily Summary - March 20, 2026")


# ---------------------------------------------------------------------------
# Test: _is_toast_daily_email
# ---------------------------------------------------------------------------

class TestIsToastDailyEmail:
    def test_valid_daily_summary(self, parser: ToastPOSParser, standard_email: dict) -> None:
        assert parser._is_toast_daily_email(standard_email) is True

    def test_valid_daily_report(self, parser: ToastPOSParser, minimal_email: dict) -> None:
        assert parser._is_toast_daily_email(minimal_email) is True

    def test_wrong_sender(self, parser: ToastPOSParser) -> None:
        email = _make_email(SAMPLE_DAILY_SUMMARY, sender="other@example.com")
        assert parser._is_toast_daily_email(email) is False

    def test_wrong_subject(self, parser: ToastPOSParser) -> None:
        email = _make_email(SAMPLE_DAILY_SUMMARY, subject="Your Toast Receipt")
        assert parser._is_toast_daily_email(email) is False


# ---------------------------------------------------------------------------
# Test: report date extraction
# ---------------------------------------------------------------------------

class TestReportDateExtraction:
    def test_month_name_format(self, parser: ToastPOSParser) -> None:
        result = parser._extract_report_date(SAMPLE_DAILY_SUMMARY, "")
        assert result == "March 15, 2026"

    def test_slash_date_format(self, parser: ToastPOSParser) -> None:
        result = parser._extract_report_date(SAMPLE_DAILY_REPORT_MINIMAL, "")
        assert result == "03/15/2026"

    def test_iso_date_format(self, parser: ToastPOSParser) -> None:
        result = parser._extract_report_date(SAMPLE_MISSING_FIELDS, "")
        assert result == "2026-03-15"

    def test_fallback_to_email_date(self, parser: ToastPOSParser) -> None:
        result = parser._extract_report_date("No date here at all.", "2026-01-01")
        assert result == "2026-01-01"

    def test_empty_body_empty_fallback(self, parser: ToastPOSParser) -> None:
        result = parser._extract_report_date("", "")
        assert result is None


# ---------------------------------------------------------------------------
# Test: amount extraction (gross sales, net sales, tax, tips)
# ---------------------------------------------------------------------------

class TestAmountExtraction:
    def test_gross_sales(self, parser: ToastPOSParser) -> None:
        assert parser._extract_labelled_amount(SAMPLE_DAILY_SUMMARY, "gross sales") == 4523.78

    def test_net_sales(self, parser: ToastPOSParser) -> None:
        assert parser._extract_labelled_amount(SAMPLE_DAILY_SUMMARY, "net sales") == 4123.45

    def test_tax_collected(self, parser: ToastPOSParser) -> None:
        assert parser._extract_labelled_amount(SAMPLE_DAILY_SUMMARY, "tax collected") == 345.67

    def test_tips(self, parser: ToastPOSParser) -> None:
        assert parser._extract_labelled_amount(SAMPLE_DAILY_SUMMARY, "tips") == 612.34

    def test_no_dollar_sign(self, parser: ToastPOSParser) -> None:
        assert parser._extract_labelled_amount(SAMPLE_NO_DOLLAR_SIGNS, "gross sales") == 2500.00

    def test_missing_label(self, parser: ToastPOSParser) -> None:
        assert parser._extract_labelled_amount(SAMPLE_DAILY_SUMMARY, "discount") is None

    def test_empty_text(self, parser: ToastPOSParser) -> None:
        assert parser._extract_labelled_amount("", "gross sales") is None


# ---------------------------------------------------------------------------
# Test: refund extraction
# ---------------------------------------------------------------------------

class TestRefundExtraction:
    def test_refunds_voids_combined(self, parser: ToastPOSParser) -> None:
        assert parser._extract_refunds(SAMPLE_DAILY_SUMMARY) == 54.33

    def test_refunds_only(self, parser: ToastPOSParser) -> None:
        assert parser._extract_refunds(SAMPLE_NO_DOLLAR_SIGNS) == 0.00

    def test_no_refunds_field(self, parser: ToastPOSParser) -> None:
        assert parser._extract_refunds(SAMPLE_MISSING_FIELDS) is None

    def test_empty_text(self, parser: ToastPOSParser) -> None:
        assert parser._extract_refunds("") is None


# ---------------------------------------------------------------------------
# Test: total orders extraction
# ---------------------------------------------------------------------------

class TestTotalOrdersExtraction:
    def test_total_orders_label(self, parser: ToastPOSParser) -> None:
        assert parser._extract_total_orders(SAMPLE_DAILY_SUMMARY) == 187

    def test_n_orders_pattern(self, parser: ToastPOSParser) -> None:
        assert parser._extract_total_orders(SAMPLE_WEIRD_FORMATTING) == 187

    def test_missing_orders(self, parser: ToastPOSParser) -> None:
        assert parser._extract_total_orders("No order info here.") is None

    def test_empty_text(self, parser: ToastPOSParser) -> None:
        assert parser._extract_total_orders("") is None


# ---------------------------------------------------------------------------
# Test: payment breakdown extraction
# ---------------------------------------------------------------------------

class TestPaymentBreakdown:
    def test_full_breakdown(self, parser: ToastPOSParser) -> None:
        breakdown = parser._extract_payment_breakdown(SAMPLE_DAILY_SUMMARY)
        assert breakdown["cash"] == 823.50
        assert breakdown["credit_card"] == 3245.95
        assert breakdown["other"] == 54.33

    def test_no_other_payments(self, parser: ToastPOSParser) -> None:
        breakdown = parser._extract_payment_breakdown(SAMPLE_DAILY_REPORT_MINIMAL)
        assert breakdown["cash"] is None
        assert breakdown["credit_card"] is None
        assert breakdown["other"] is None

    def test_without_dollar_signs(self, parser: ToastPOSParser) -> None:
        breakdown = parser._extract_payment_breakdown(SAMPLE_NO_DOLLAR_SIGNS)
        assert breakdown["cash"] == 600.00
        assert breakdown["credit_card"] == 1900.00


# ---------------------------------------------------------------------------
# Test: full parse_single integration
# ---------------------------------------------------------------------------

class TestParseSingle:
    def test_full_report(self, parser: ToastPOSParser, standard_email: dict) -> None:
        result = parser._parse_single(standard_email)
        assert result is not None
        assert result["gross_sales"] == 4523.78
        assert result["net_sales"] == 4123.45
        assert result["tax_collected"] == 345.67
        assert result["tips"] == 612.34
        assert result["refunds"] == 54.33
        assert result["total_orders"] == 187
        assert result["payment_breakdown"]["cash"] == 823.50
        assert result["message_id"] == "msg_001"

    def test_non_toast_email_returns_none(self, parser: ToastPOSParser) -> None:
        email = _make_email(SAMPLE_DAILY_SUMMARY, sender="other@example.com")
        assert parser._parse_single(email) is None

    def test_missing_fields_returns_none_for_absent(
        self, parser: ToastPOSParser, missing_fields_email: dict
    ) -> None:
        result = parser._parse_single(missing_fields_email)
        assert result is not None
        assert result["gross_sales"] == 800.00
        assert result["tips"] is None
        assert result["refunds"] is None
        assert result["tax_collected"] is None


# ---------------------------------------------------------------------------
# Test: parse_daily_reports batch
# ---------------------------------------------------------------------------

class TestParseDailyReports:
    def test_filters_non_toast(self, parser: ToastPOSParser) -> None:
        emails = [
            _make_email(SAMPLE_DAILY_SUMMARY),
            _make_email(SAMPLE_DAILY_SUMMARY, sender="other@example.com"),
            _make_email(SAMPLE_DAILY_REPORT_MINIMAL, subject="Daily Report"),
        ]
        results = parser.parse_daily_reports(emails)
        assert len(results) == 2

    def test_empty_list(self, parser: ToastPOSParser) -> None:
        assert parser.parse_daily_reports([]) == []


# ---------------------------------------------------------------------------
# Test: parse_date_range with mocked GmailConnector
# ---------------------------------------------------------------------------

class TestParseDateRange:
    def test_calls_gmail_and_filters(self, parser: ToastPOSParser) -> None:
        mock_gmail = MagicMock()
        mock_gmail.search_invoices.return_value = [
            _make_email(SAMPLE_DAILY_SUMMARY),
            _make_email(SAMPLE_DAILY_SUMMARY, sender="other@example.com"),
        ]

        results = parser.parse_date_range("2026-03-01", "2026-03-31", mock_gmail)

        mock_gmail.search_invoices.assert_called_once_with(
            start_date="2026-03-01",
            end_date="2026-03-31",
            vendor_filter="Toast",
        )
        assert len(results) == 1

    def test_no_results(self, parser: ToastPOSParser) -> None:
        mock_gmail = MagicMock()
        mock_gmail.search_invoices.return_value = []

        results = parser.parse_date_range("2026-03-01", "2026-03-31", mock_gmail)
        assert results == []


# ---------------------------------------------------------------------------
# Test: edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_weird_formatting(self, parser: ToastPOSParser, weird_formatting_email: dict) -> None:
        result = parser._parse_single(weird_formatting_email)
        assert result is not None
        assert result["gross_sales"] == 3100.55
        assert result["net_sales"] == 2800.00
        assert result["tax_collected"] == 275.50
        assert result["tips"] == 400.00
        assert result["refunds"] == 25.05

    def test_zero_dollar_amount(self, parser: ToastPOSParser) -> None:
        assert parser._parse_dollar("0.00") == 0.00

    def test_invalid_dollar_string(self, parser: ToastPOSParser) -> None:
        assert parser._parse_dollar("abc") is None

    def test_negative_amount(self, parser: ToastPOSParser) -> None:
        assert parser._parse_dollar("-50.00") is None
