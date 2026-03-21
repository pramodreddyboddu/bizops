"""Tests for the invoice parser module."""

import pytest

from bizops.parsers.invoice import InvoiceParser
from bizops.utils.config import BizOpsConfig, VendorConfig


@pytest.fixture
def config():
    """Create a test config with sample vendors."""
    return BizOpsConfig(
        vendors=[
            VendorConfig(name="Sysco", email_patterns=["sysco.com"], category="food_supplies"),
            VendorConfig(name="Toast", email_patterns=["toasttab.com"], category="pos_reports"),
        ]
    )


@pytest.fixture
def parser(config):
    return InvoiceParser(config)


class TestAmountExtraction:
    def test_simple_dollar_amount(self, parser):
        assert parser._extract_amount("Total: $1,234.56") == 1234.56

    def test_amount_due(self, parser):
        assert parser._extract_amount("Amount Due: $567.89") == 567.89

    def test_multiple_amounts_takes_largest(self, parser):
        text = "Subtotal: $100.00\nTax: $8.25\nShipping: $5.00"
        assert parser._extract_amount(text) == 100.00

    def test_total_keyword_priority(self, parser):
        text = "Item: $50.00\nItem: $30.00\nGrand Total: $80.00"
        assert parser._extract_amount(text) == 80.00

    def test_no_amount(self, parser):
        assert parser._extract_amount("No amounts here") is None

    def test_empty_text(self, parser):
        assert parser._extract_amount("") is None


class TestStatusDetection:
    def test_paid(self, parser):
        assert parser._detect_status("Payment received. Thank you!") == "paid"

    def test_unpaid(self, parser):
        assert parser._detect_status("Amount due: $500. Please remit.") == "unpaid"

    def test_partial(self, parser):
        assert parser._detect_status("Partial payment received. Remaining balance: $200") == "partial"

    def test_unknown(self, parser):
        assert parser._detect_status("Here is your monthly summary.") == "unknown"


class TestInvoiceNumber:
    def test_standard_format(self, parser):
        assert parser._extract_invoice_number("Invoice #INV-2026-001") == "INV-2026-001"

    def test_colon_format(self, parser):
        assert parser._extract_invoice_number("Invoice: ABC123") == "ABC123"

    def test_no_number(self, parser):
        assert parser._extract_invoice_number("Monthly statement") is None


class TestDeduplication:
    def test_removes_duplicates(self, parser):
        invoices = [
            {"vendor": "Sysco", "amount": 500.0, "date": "2026-03-01", "message_id": "a"},
            {"vendor": "Sysco", "amount": 500.0, "date": "2026-03-01", "message_id": "b"},
            {"vendor": "Sysco", "amount": 600.0, "date": "2026-03-01", "message_id": "c"},
        ]
        result = parser.deduplicate(invoices)
        assert len(result) == 2

    def test_keeps_unique(self, parser):
        invoices = [
            {"vendor": "Sysco", "amount": 500.0, "date": "2026-03-01"},
            {"vendor": "Toast", "amount": 500.0, "date": "2026-03-01"},
            {"vendor": "Sysco", "amount": 500.0, "date": "2026-03-02"},
        ]
        result = parser.deduplicate(invoices)
        assert len(result) == 3


class TestVendorCategory:
    def test_known_vendor(self, parser):
        assert parser._get_vendor_category("Sysco") == "food_supplies"

    def test_unknown_vendor(self, parser):
        assert parser._get_vendor_category("Random Vendor") == "uncategorized"
