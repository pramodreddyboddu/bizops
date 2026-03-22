"""Tests for product catalog extractor."""

from __future__ import annotations

import textwrap

import pytest

from bizops.parsers.product_extractor import ProductExtractor
from bizops.utils.config import BizOpsConfig, VendorConfig


@pytest.fixture
def config():
    return BizOpsConfig(
        vendors=[
            VendorConfig(
                name="Om Produce",
                email_patterns=["omproduce.com"],
                category="produce",
            ),
            VendorConfig(
                name="Yaman Halal",
                email_patterns=["yaman"],
                category="meat",
            ),
        ]
    )


@pytest.fixture
def extractor(config):
    return ProductExtractor(config)


# ──────────────────────────────────────────────────────────────
#  Email extraction — line item patterns
# ──────────────────────────────────────────────────────────────


class TestLineItemExtraction:
    def test_pattern1_product_qty_unit_price(self, extractor):
        body = "Cilantro    50  bunch  $0.75  $37.50"
        items = extractor._extract_line_items(body)
        assert len(items) == 1
        assert items[0]["name"] == "Cilantro"
        assert items[0]["quantity"] == 50
        assert items[0]["unit"] == "bunch"
        assert items[0]["unit_cost"] == 0.75

    def test_pattern2_qty_x_product_at_price(self, extractor):
        body = "50 x Cilantro @ $0.75"
        items = extractor._extract_line_items(body)
        assert len(items) == 1
        assert items[0]["name"] == "Cilantro"
        assert items[0]["quantity"] == 50
        assert items[0]["unit_cost"] == 0.75

    def test_pattern3_qty_unit_product_price(self, extractor):
        body = "50 lb Onions $0.50/lb"
        items = extractor._extract_line_items(body)
        assert len(items) == 1
        assert items[0]["name"] == "Onions"
        assert items[0]["quantity"] == 50
        assert items[0]["unit"] == "lb"
        assert items[0]["unit_cost"] == 0.50

    def test_pattern4_structured_format(self, extractor):
        body = "Item: Basmati Rice, Qty: 10, Price: $25.00"
        items = extractor._extract_line_items(body)
        assert len(items) == 1
        assert items[0]["name"] == "Basmati Rice"
        assert items[0]["quantity"] == 10
        assert items[0]["unit_cost"] == 25.00

    def test_pattern5_simple_price_list(self, extractor):
        body = "Chicken Breast  $3.50/lb"
        items = extractor._extract_line_items(body)
        assert len(items) == 1
        assert items[0]["name"] == "Chicken Breast"
        assert items[0]["unit_cost"] == 3.50

    def test_multiple_line_items(self, extractor):
        body = textwrap.dedent("""\
            Cilantro    50  bunch  $0.75  $37.50
            Onions      100 lb     $0.50  $50.00
            Tomatoes    80  lb     $1.25  $100.00
        """)
        items = extractor._extract_line_items(body)
        assert len(items) == 3
        names = [i["name"] for i in items]
        assert "Cilantro" in names
        assert "Onions" in names
        assert "Tomatoes" in names

    def test_skips_headers(self, extractor):
        body = "Product  Qty  Unit  Price\nCilantro  50  bunch  $0.75"
        items = extractor._extract_line_items(body)
        # Should skip header line, get the data line
        assert len(items) >= 1
        assert items[0]["name"] == "Cilantro"

    def test_skips_totals(self, extractor):
        body = textwrap.dedent("""\
            Cilantro  50  bunch  $0.75
            Subtotal  $37.50
            Total  $40.00
        """)
        items = extractor._extract_line_items(body)
        assert len(items) == 1
        assert items[0]["name"] == "Cilantro"

    def test_empty_body(self, extractor):
        assert extractor._extract_line_items("") == []

    def test_no_products_in_body(self, extractor):
        body = "Thank you for your payment of $500.00."
        items = extractor._extract_line_items(body)
        # Should not extract "Thank you" as a product
        for item in items:
            assert not extractor._is_generic_text(item["name"])


# ──────────────────────────────────────────────────────────────
#  Email extraction — full emails
# ──────────────────────────────────────────────────────────────


class TestEmailExtraction:
    def test_extract_from_vendor_email(self, extractor):
        emails = [
            {
                "vendor": "Om Produce",
                "sender": "orders@omproduce.com",
                "subject": "Invoice #1234",
                "body": "Cilantro  50  bunch  $0.75\nOnions  100  lb  $0.50",
                "date": "2026-03-15",
            }
        ]
        products = extractor.extract_from_emails(emails, "Om Produce")
        assert len(products) == 2

    def test_filter_by_vendor(self, extractor):
        emails = [
            {"vendor": "Om Produce", "sender": "om@test.com", "body": "Cilantro  50  bunch  $0.75", "date": "2026-03-15", "subject": ""},
            {"vendor": "Other Vendor", "sender": "other@test.com", "body": "Chicken  10  lb  $3.50", "date": "2026-03-15", "subject": ""},
        ]
        products = extractor.extract_from_emails(emails, "Om Produce")
        assert len(products) == 1
        assert products[0]["name"] == "Cilantro"

    def test_dedup_same_product(self, extractor):
        emails = [
            {"vendor": "Om Produce", "body": "Cilantro  50  bunch  $0.75", "date": "2026-03-10", "subject": ""},
            {"vendor": "Om Produce", "body": "Cilantro  60  bunch  $0.80", "date": "2026-03-15", "subject": ""},
        ]
        products = extractor.extract_from_emails(emails, "Om Produce")
        assert len(products) == 1
        # Should keep latest price
        assert products[0]["unit_cost"] == 0.80

    def test_all_vendors(self, extractor):
        emails = [
            {"vendor": "Om Produce", "body": "Cilantro  50  bunch  $0.75", "date": "2026-03-15", "subject": ""},
            {"vendor": "Yaman Halal", "body": "Chicken  10  lb  $3.50", "date": "2026-03-15", "subject": ""},
        ]
        products = extractor.extract_from_emails(emails)
        assert len(products) == 2


# ──────────────────────────────────────────────────────────────
#  File import — CSV
# ──────────────────────────────────────────────────────────────


class TestCSVImport:
    def test_standard_csv(self, extractor, tmp_path):
        csv = tmp_path / "products.csv"
        csv.write_text("name,unit,cost,par,multiple,category\n"
                       "Cilantro,bunch,0.75,50,10,produce\n"
                       "Onions,lb,0.50,100,25,produce\n")

        products = extractor.import_from_file(csv)
        assert len(products) == 2
        assert products[0]["name"] == "Cilantro"
        assert products[0]["unit_cost"] == 0.75
        assert products[0]["par_level"] == 50.0

    def test_flexible_headers(self, extractor, tmp_path):
        csv = tmp_path / "products.csv"
        csv.write_text("Product Name,UOM,Unit Price,Par Level\n"
                       "Basmati Rice,bag,25.00,10\n")

        products = extractor.import_from_file(csv)
        assert len(products) == 1
        assert products[0]["name"] == "Basmati Rice"

    def test_with_vendor_column(self, extractor, tmp_path):
        csv = tmp_path / "products.csv"
        csv.write_text("name,unit,cost,vendor\n"
                       "Cilantro,bunch,0.75,Om Produce\n"
                       "Chicken,lb,3.50,Yaman Halal\n")

        products = extractor.import_from_file(csv)
        assert len(products) == 2
        assert products[0]["vendor"] == "Om Produce"
        assert products[1]["vendor"] == "Yaman Halal"

    def test_dollar_signs_in_cost(self, extractor, tmp_path):
        csv = tmp_path / "products.csv"
        csv.write_text("name,cost\nCilantro,$0.75\n")

        products = extractor.import_from_file(csv)
        assert products[0]["unit_cost"] == 0.75

    def test_empty_rows_skipped(self, extractor, tmp_path):
        csv = tmp_path / "products.csv"
        csv.write_text("name,cost\nCilantro,0.75\n,,\nOnions,0.50\n")

        products = extractor.import_from_file(csv)
        assert len(products) == 2

    def test_no_name_column_raises(self, extractor, tmp_path):
        csv = tmp_path / "bad.csv"
        csv.write_text("price,quantity\n0.75,50\n")

        with pytest.raises(ValueError, match="name"):
            extractor.import_from_file(csv)

    def test_utf8_bom(self, extractor, tmp_path):
        csv = tmp_path / "bom.csv"
        csv.write_bytes(b"\xef\xbb\xbfname,cost\nCilantro,0.75\n")

        products = extractor.import_from_file(csv)
        assert len(products) == 1

    def test_unsupported_format(self, extractor, tmp_path):
        txt = tmp_path / "products.txt"
        txt.write_text("not a csv")

        with pytest.raises(ValueError, match="Unsupported"):
            extractor.import_from_file(txt)


# ──────────────────────────────────────────────────────────────
#  Convert to ProductItem
# ──────────────────────────────────────────────────────────────


class TestToProductItems:
    def test_basic_conversion(self, extractor):
        extracted = [
            {"name": "Cilantro", "unit": "bunch", "unit_cost": 0.75, "par_level": 50, "order_multiple": 10},
        ]
        items = extractor.to_product_items(extracted)
        assert len(items) == 1
        assert items[0].name == "Cilantro"
        assert items[0].unit == "bunch"
        assert items[0].unit_cost == 0.75
        assert items[0].par_level == 50

    def test_dedup_by_name(self, extractor):
        extracted = [
            {"name": "Cilantro", "unit_cost": 0.75},
            {"name": "cilantro", "unit_cost": 0.80},
        ]
        items = extractor.to_product_items(extracted)
        assert len(items) == 1
        assert items[0].unit_cost == 0.80  # Latest price wins

    def test_empty_names_skipped(self, extractor):
        extracted = [{"name": "", "unit_cost": 1.00}, {"name": "  ", "unit_cost": 2.00}]
        items = extractor.to_product_items(extracted)
        assert len(items) == 0

    def test_default_category(self, extractor):
        extracted = [{"name": "Rice"}]
        items = extractor.to_product_items(extracted, default_category="produce")
        assert items[0].category == "produce"


# ──────────────────────────────────────────────────────────────
#  Unit normalization
# ──────────────────────────────────────────────────────────────


class TestUnitNormalization:
    def test_normalize_plurals(self, extractor):
        assert extractor._normalize_unit("lbs") == "lb"
        assert extractor._normalize_unit("bags") == "bag"
        assert extractor._normalize_unit("bunches") == "bunch"
        assert extractor._normalize_unit("boxes") == "box"

    def test_normalize_abbreviations(self, extractor):
        assert extractor._normalize_unit("ea") == "each"
        assert extractor._normalize_unit("cs") == "case"
        assert extractor._normalize_unit("pk") == "pack"

    def test_passthrough_standard(self, extractor):
        assert extractor._normalize_unit("lb") == "lb"
        assert extractor._normalize_unit("case") == "case"
        assert extractor._normalize_unit("each") == "each"

    def test_empty_returns_each(self, extractor):
        assert extractor._normalize_unit("") == "each"


# ──────────────────────────────────────────────────────────────
#  Helper functions
# ──────────────────────────────────────────────────────────────


class TestHelpers:
    def test_is_header_or_summary(self, extractor):
        assert extractor._is_header_or_summary("Total  $500.00") is True
        assert extractor._is_header_or_summary("Subtotal") is True
        assert extractor._is_header_or_summary("Product  Qty  Price") is True
        assert extractor._is_header_or_summary("Cilantro  50  bunch") is False

    def test_is_generic_text(self, extractor):
        assert extractor._is_generic_text("total") is True
        assert extractor._is_generic_text("payment") is True
        assert extractor._is_generic_text("Cilantro") is False

    def test_parse_number(self, extractor):
        assert extractor._parse_number("1,234.56") == 1234.56
        assert extractor._parse_number("$50.00") == 50.0
        assert extractor._parse_number(42) == 42.0
        assert extractor._parse_number("") == 0.0
        assert extractor._parse_number(None) == 0.0
