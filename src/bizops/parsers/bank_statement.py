"""Bank statement parser — CSV and PDF support for Bank of America."""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from bizops.utils.config import BizOpsConfig, ExpenseCategory


class BankStatementParser:
    """Parse Bank of America statements from CSV or PDF files."""

    def __init__(self, config: BizOpsConfig) -> None:
        self.config = config
        self._category_keywords = config.category_keywords.model_dump()

    def parse_csv(self, file_path: Path) -> list[dict[str, Any]]:
        """Parse a Bank of America CSV statement.

        BoA CSV format:
            Date,Description,Amount,Running Bal.
            03/15/2026,ZELLE PAYMENT TO OM PRODUCE,-1500.00,12345.67

        Some files also have headers like:
            Posted Date,Reference Number,Payee,Address,Amount
        """
        path = Path(file_path)
        # BoA CSVs are sometimes UTF-8 BOM encoded
        text = path.read_text(encoding="utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))

        fieldnames = reader.fieldnames or []
        lower_fields = [f.lower().strip() for f in fieldnames]

        # Detect which column layout we're dealing with
        date_col = _find_column(fieldnames, lower_fields, ["date", "posted date", "posting date"])
        desc_col = _find_column(fieldnames, lower_fields, ["description", "payee", "original description"])
        amount_col = _find_column(fieldnames, lower_fields, ["amount"])

        if not date_col or not amount_col:
            raise ValueError(
                f"Cannot detect BoA CSV format. Found columns: {fieldnames}. "
                "Expected at least 'Date' and 'Amount' columns."
            )

        transactions: list[dict[str, Any]] = []
        for row in reader:
            raw_date = (row.get(date_col) or "").strip()
            raw_desc = (row.get(desc_col) or "").strip() if desc_col else ""
            raw_amount = (row.get(amount_col) or "").strip()

            if not raw_date or not raw_amount:
                continue

            try:
                amount = float(raw_amount.replace(",", "").replace("$", ""))
            except ValueError:
                continue

            txn = self._normalize_transaction(
                raw_date=raw_date,
                raw_description=raw_desc,
                amount=amount,
                source_file=path.name,
            )
            if txn:
                transactions.append(txn)

        return transactions

    def parse_pdf(self, file_path: Path) -> list[dict[str, Any]]:
        """Parse a Bank of America PDF statement using pdfplumber."""
        try:
            import pdfplumber
        except ImportError:
            raise ImportError(
                "pdfplumber is required for PDF parsing. "
                "Install it with: pip install pdfplumber"
            )

        path = Path(file_path)
        transactions: list[dict[str, Any]] = []

        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                # Try table extraction first
                tables = page.extract_tables()
                if tables:
                    for table in tables:
                        txns = self._parse_pdf_table(table, path.name)
                        transactions.extend(txns)
                else:
                    # Fall back to text-based extraction
                    text = page.extract_text() or ""
                    txns = self._parse_pdf_text(text, path.name)
                    transactions.extend(txns)

        return transactions

    def parse_file(self, file_path: Path) -> list[dict[str, Any]]:
        """Auto-detect format and parse a bank statement file."""
        path = Path(file_path)
        suffix = path.suffix.lower()

        if suffix == ".csv":
            return self.parse_csv(path)
        elif suffix == ".pdf":
            return self.parse_pdf(path)
        else:
            raise ValueError(f"Unsupported file format: {suffix}. Use .csv or .pdf")

    def _normalize_transaction(
        self,
        raw_date: str,
        raw_description: str,
        amount: float,
        source_file: str,
    ) -> dict[str, Any] | None:
        """Normalize a raw transaction into a standard dict."""
        date_str = self._parse_date(raw_date)
        if not date_str:
            return None

        description = self._clean_description(raw_description)
        txn_type = "credit" if amount > 0 else "debit"
        category = self._detect_category(description, amount)

        return {
            "date": date_str,
            "description": description,
            "raw_description": raw_description,
            "amount": round(amount, 2),
            "abs_amount": round(abs(amount), 2),
            "type": txn_type,
            "category": category,
            "source_file": source_file,
            "reconciled": False,
            "matched_invoice_id": None,
        }

    def _parse_date(self, date_str: str) -> str | None:
        """Parse common BoA date formats to YYYY-MM-DD."""
        formats = ["%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%m-%d-%Y", "%b %d, %Y"]
        for fmt in formats:
            try:
                return datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
        return None

    def _clean_description(self, desc: str) -> str:
        """Strip noise from BoA transaction descriptions."""
        # Remove trailing reference numbers
        desc = re.sub(r'\s+Ref\s*#?\s*\w+$', '', desc, flags=re.IGNORECASE)
        # Remove trailing transaction IDs
        desc = re.sub(r'\s+\d{10,}$', '', desc)
        # Remove leading "Withdrawal" / "Deposit" prefixes
        desc = re.sub(r'^(Withdrawal|Deposit|Payment)\s*[-:]\s*', '', desc, flags=re.IGNORECASE)
        # Collapse whitespace
        desc = re.sub(r'\s+', ' ', desc).strip()
        return desc

    def _detect_category(self, description: str, amount: float) -> str:
        """Categorize a bank transaction based on its description."""
        desc_lower = description.lower()

        # Check vendor config first
        for vendor in self.config.vendors:
            for pattern in vendor.email_patterns:
                if pattern.lower() in desc_lower:
                    if vendor.category in [c.value for c in ExpenseCategory]:
                        return vendor.category

            for alias in vendor.aliases:
                if alias.lower() in desc_lower:
                    if vendor.category in [c.value for c in ExpenseCategory]:
                        return vendor.category

        # Check category keywords
        for cat in ExpenseCategory:
            keywords = self._category_keywords.get(cat.value, [])
            for kw in keywords:
                if kw.lower() in desc_lower:
                    return cat.value

        # Common bank transaction patterns
        bank_patterns: dict[str, str] = {
            "merchant fee": "pos_fees",
            "card fee": "pos_fees",
            "processing fee": "pos_fees",
            "square": "pos_fees",
            "stripe": "pos_fees",
            "toast": "pos_fees",
            "insurance": "insurance",
            "premium": "insurance",
            "payroll": "payroll",
            "gusto": "payroll",
            "adp": "payroll",
            "rent": "rent",
            "lease": "rent",
        }
        for pattern, cat in bank_patterns.items():
            if pattern in desc_lower:
                return cat

        return "uncategorized"

    def _parse_pdf_table(
        self, table: list[list[str | None]], source_file: str
    ) -> list[dict[str, Any]]:
        """Parse a table extracted from a PDF page."""
        if not table or len(table) < 2:
            return []

        # Try to identify header row
        header = table[0]
        if not header:
            return []

        lower_header = [str(h or "").lower().strip() for h in header]

        date_idx = _find_index(lower_header, ["date", "posted date", "posting date"])
        desc_idx = _find_index(lower_header, ["description", "payee", "transaction"])
        amount_idx = _find_index(lower_header, ["amount"])

        # If no clear header, try columns by position (BoA: Date, Description, Amount)
        if date_idx is None:
            # Check if first row looks like data (has a date)
            if header and _looks_like_date(str(header[0] or "")):
                date_idx, desc_idx, amount_idx = 0, 1, len(header) - 1
                data_rows = table  # No header row
            else:
                return []
        else:
            data_rows = table[1:]

        transactions: list[dict[str, Any]] = []
        for row in data_rows:
            if not row or len(row) <= max(
                i for i in [date_idx, desc_idx, amount_idx] if i is not None
            ):
                continue

            raw_date = str(row[date_idx] or "").strip() if date_idx is not None else ""
            raw_desc = str(row[desc_idx] or "").strip() if desc_idx is not None else ""
            raw_amount = str(row[amount_idx] or "").strip() if amount_idx is not None else ""

            if not raw_date or not raw_amount:
                continue

            try:
                amount = float(raw_amount.replace(",", "").replace("$", "").replace("(", "-").replace(")", ""))
            except ValueError:
                continue

            txn = self._normalize_transaction(raw_date, raw_desc, amount, source_file)
            if txn:
                transactions.append(txn)

        return transactions

    def _parse_pdf_text(self, text: str, source_file: str) -> list[dict[str, Any]]:
        """Fall back to regex-based line parsing for PDF text."""
        # BoA statement line pattern: MM/DD/YY  Description  Amount
        pattern = re.compile(
            r'(\d{1,2}/\d{1,2}/\d{2,4})\s+'  # date
            r'(.+?)\s+'                        # description
            r'(-?\$?[\d,]+\.\d{2})\s*$',       # amount
            re.MULTILINE,
        )

        transactions: list[dict[str, Any]] = []
        for match in pattern.finditer(text):
            raw_date = match.group(1)
            raw_desc = match.group(2).strip()
            raw_amount = match.group(3).replace(",", "").replace("$", "")

            try:
                amount = float(raw_amount)
            except ValueError:
                continue

            txn = self._normalize_transaction(raw_date, raw_desc, amount, source_file)
            if txn:
                transactions.append(txn)

        return transactions


# ──────────────────────────────────────────────────────────────
#  Module-level helpers
# ──────────────────────────────────────────────────────────────


def _find_column(
    fieldnames: list[str], lower_fields: list[str], candidates: list[str]
) -> str | None:
    """Find the original column name matching one of the candidate names."""
    for candidate in candidates:
        for i, lf in enumerate(lower_fields):
            if lf == candidate:
                return fieldnames[i]
    return None


def _find_index(lower_header: list[str], candidates: list[str]) -> int | None:
    """Find the index of a column matching one of the candidate names."""
    for candidate in candidates:
        for i, h in enumerate(lower_header):
            if candidate in h:
                return i
    return None


def _looks_like_date(s: str) -> bool:
    """Quick check if a string looks like a date."""
    return bool(re.match(r'\d{1,2}/\d{1,2}/\d{2,4}', s))
