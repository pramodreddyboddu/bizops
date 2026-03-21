"""Tests for the expense engine module."""

import pytest

from bizops.parsers.expenses import ExpenseEngine
from bizops.utils.config import BizOpsConfig, ExpenseCategory, VendorConfig


# ──────────────────────────────────────────────────────────────
#  Fixtures
# ──────────────────────────────────────────────────────────────

@pytest.fixture
def config():
    """Config with sample vendors for testing."""
    return BizOpsConfig(
        vendors=[
            VendorConfig(
                name="Sysco",
                email_patterns=["sysco.com"],
                category="food_supplies",
            ),
            VendorConfig(
                name="Gexa Energy",
                email_patterns=["gexa"],
                category="utilities",
                aliases=["Gexa"],
            ),
            VendorConfig(
                name="Toast POS",
                email_patterns=["toasttab.com"],
                category="pos_reports",
            ),
        ]
    )


@pytest.fixture
def engine(config):
    return ExpenseEngine(config)


def _make_invoice(
    vendor="Unknown",
    amount=100.0,
    subject="",
    body="",
    date="2026-03-15",
    **extra,
):
    """Helper to build a test invoice dict."""
    inv = {
        "vendor": vendor,
        "amount": amount,
        "subject": subject,
        "body": body,
        "date": date,
        "status": "paid",
        "category": "zelle_payment",
        "transaction_type": "payment",
    }
    inv.update(extra)
    return inv


# ──────────────────────────────────────────────────────────────
#  Vendor-config-based categorization
# ──────────────────────────────────────────────────────────────

class TestVendorConfigCategorization:
    def test_exact_vendor_name_match(self, engine):
        inv = _make_invoice(vendor="Sysco")
        assert engine.categorize_invoice(inv) == "food_supplies"

    def test_vendor_alias_match(self, engine):
        inv = _make_invoice(vendor="Gexa")
        assert engine.categorize_invoice(inv) == "utilities"

    def test_vendor_case_insensitive(self, engine):
        inv = _make_invoice(vendor="sysco")
        assert engine.categorize_invoice(inv) == "food_supplies"

    def test_pos_reports_category_skipped(self, engine):
        """pos_reports is not a valid expense category — should fall through."""
        inv = _make_invoice(vendor="Toast POS", subject="daily report")
        # "Toast POS" matches vendor config with category "pos_reports",
        # but that's skipped, so it falls through to keyword match on "toast"
        result = engine.categorize_invoice(inv)
        assert result == "pos_fees"


# ──────────────────────────────────────────────────────────────
#  Keyword-based categorization
# ──────────────────────────────────────────────────────────────

class TestKeywordCategorization:
    def test_zelle_meat_vendor(self, engine):
        inv = _make_invoice(
            vendor="YAMAN HALAL MEAT LLC",
            subject="Zelle® payment of $1,248.31 to YAMAN HALAL MEAT LLC has been sent",
        )
        assert engine.categorize_invoice(inv) == "meat"

    def test_zelle_produce_vendor(self, engine):
        inv = _make_invoice(
            vendor="Om Produce",
            subject="Zelle® payment of $500.00 to Om Produce has been sent",
        )
        assert engine.categorize_invoice(inv) == "produce"

    def test_keyword_in_subject(self, engine):
        inv = _make_invoice(
            vendor="ACME Corp",
            subject="Your Gexa Energy e-invoice is ready",
        )
        assert engine.categorize_invoice(inv) == "utilities"

    def test_keyword_in_body(self, engine):
        inv = _make_invoice(
            vendor="Some Vendor",
            body="Thank you for your cleaning supply order",
        )
        assert engine.categorize_invoice(inv) == "cleaning"

    def test_rent_keyword(self, engine):
        inv = _make_invoice(
            vendor="KPPSINVESTMENTS",
            subject="Zelle® payment of $3,000.00 to KPPSINVESTMENTS has been sent",
        )
        assert engine.categorize_invoice(inv) == "rent"

    def test_payroll_keyword(self, engine):
        inv = _make_invoice(
            vendor="Gusto Payroll",
            subject="Payroll payment processed",
        )
        assert engine.categorize_invoice(inv) == "payroll"

    def test_insurance_keyword(self, engine):
        inv = _make_invoice(
            vendor="State Farm",
            subject="Your insurance premium is due",
        )
        assert engine.categorize_invoice(inv) == "insurance"


# ──────────────────────────────────────────────────────────────
#  Fallback to miscellaneous
# ──────────────────────────────────────────────────────────────

class TestFallbackMiscellaneous:
    def test_unknown_vendor_no_keywords(self, engine):
        inv = _make_invoice(vendor="Random LLC", subject="Invoice attached")
        assert engine.categorize_invoice(inv) == "miscellaneous"

    def test_empty_vendor_and_subject(self, engine):
        inv = _make_invoice(vendor="", subject="")
        assert engine.categorize_invoice(inv) == "miscellaneous"


# ──────────────────────────────────────────────────────────────
#  P&L calculation accuracy
# ──────────────────────────────────────────────────────────────

class TestPLCalculation:
    def test_totals_with_revenue_and_expenses(self, engine):
        invoices = [
            _make_invoice(vendor="Sysco", amount=500.0),
            _make_invoice(vendor="YAMAN HALAL MEAT LLC", amount=300.0,
                          subject="Zelle® payment to YAMAN HALAL MEAT LLC has been sent"),
        ]
        toast = [
            {"date": "2026-03-01", "gross_sales": 2000, "net_sales": 1800, "tax": 150, "tips": 50},
        ]
        result = engine.categorize_all(invoices, toast, "2026-03-01", "2026-03-31")

        assert result["totals"]["total_revenue"] == 1800.0
        assert result["totals"]["total_expenses"] == 800.0
        assert result["totals"]["net_profit"] == 1000.0

    def test_revenue_aggregation_multiple_days(self, engine):
        toast = [
            {"date": "2026-03-01", "gross_sales": 1000, "net_sales": 900, "tax": 80, "tips": 20},
            {"date": "2026-03-02", "gross_sales": 1500, "net_sales": 1350, "tax": 120, "tips": 30},
        ]
        result = engine.categorize_all([], toast, "2026-03-01", "2026-03-02")

        assert result["revenue"]["gross_sales"] == 2500.0
        assert result["revenue"]["net_sales"] == 2250.0
        assert result["revenue"]["tax"] == 200.0
        assert result["revenue"]["tips"] == 50.0

    def test_pl_summary_structure(self, engine):
        invoices = [_make_invoice(vendor="Sysco", amount=200.0)]
        toast = [
            {"date": "2026-03-01", "gross_sales": 1000, "net_sales": 900, "tax": 80, "tips": 20},
        ]
        full = engine.categorize_all(invoices, toast, "2026-03-01", "2026-03-31")
        pl = engine.generate_pl_summary(full)

        assert "revenue" in pl
        assert "expenses" in pl
        assert "net_profit" in pl
        assert pl["revenue"]["gross_sales"] == 1000.0
        assert pl["expenses"]["food_supplies"] == 200.0
        assert pl["net_profit"] == 700.0


# ──────────────────────────────────────────────────────────────
#  Edge cases
# ──────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_no_invoices_no_toast(self, engine):
        result = engine.categorize_all([], None, "2026-03-01", "2026-03-31")
        assert result["totals"]["total_revenue"] == 0.0
        assert result["totals"]["total_expenses"] == 0.0
        assert result["totals"]["net_profit"] == 0.0

    def test_invoices_with_none_amount(self, engine):
        inv = _make_invoice(vendor="Sysco", amount=None)
        result = engine.categorize_all([inv], [], "2026-03-01", "2026-03-31")
        assert result["totals"]["total_expenses"] == 0.0

    def test_daily_sales_sorted(self, engine):
        toast = [
            {"date": "2026-03-05", "gross_sales": 500, "net_sales": 450},
            {"date": "2026-03-01", "gross_sales": 800, "net_sales": 720},
            {"date": "2026-03-03", "gross_sales": 600, "net_sales": 540},
        ]
        result = engine.categorize_all([], toast, "2026-03-01", "2026-03-05")
        dates = [d["date"] for d in result["daily_sales"]]
        assert dates == ["2026-03-01", "2026-03-03", "2026-03-05"]

    def test_period_in_output(self, engine):
        result = engine.categorize_all([], [], "2026-03-01", "2026-03-31")
        assert result["period"]["start"] == "2026-03-01"
        assert result["period"]["end"] == "2026-03-31"

    def test_all_categories_present_in_output(self, engine):
        result = engine.categorize_all([], [], "2026-03-01", "2026-03-31")
        for cat in ExpenseCategory:
            assert cat.value in result["expenses_by_category"]

    def test_mixed_invoices_and_toast(self, engine):
        """Multiple invoices across categories plus POS data."""
        invoices = [
            _make_invoice(vendor="Sysco", amount=1000.0),
            _make_invoice(
                vendor="YAMAN HALAL MEAT LLC", amount=500.0,
                subject="Zelle® payment to YAMAN HALAL MEAT LLC has been sent",
            ),
            _make_invoice(vendor="Random Vendor", amount=50.0, subject="Misc stuff"),
        ]
        toast = [
            {"date": "2026-03-01", "gross_sales": 3000, "net_sales": 2700, "tax": 240, "tips": 60},
        ]
        result = engine.categorize_all(invoices, toast, "2026-03-01", "2026-03-31")

        assert len(result["expenses_by_category"]["food_supplies"]) == 1
        assert len(result["expenses_by_category"]["meat"]) == 1
        assert len(result["expenses_by_category"]["miscellaneous"]) == 1
        assert result["totals"]["total_expenses"] == 1550.0
        assert result["totals"]["total_revenue"] == 2700.0
        assert result["totals"]["net_profit"] == 1150.0
