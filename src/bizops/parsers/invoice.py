"""Invoice parser — extract structured data from invoice emails.

Handles amount extraction, payment status detection, and deduplication.
Adapted from the Desi Delight production pipeline.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from bizops.utils.config import BizOpsConfig


class InvoiceParser:
    """Parse invoice data from email content."""

    def __init__(self, config: BizOpsConfig):
        self.config = config
        self._seen_hashes: set[str] = set()

    def parse_emails(self, emails: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Parse a list of raw email dicts into structured invoice records."""
        invoices = []
        for email in emails:
            invoice = self._parse_single(email)
            if invoice:
                invoices.append(invoice)
        return invoices

    def _parse_single(self, email: dict[str, Any]) -> dict[str, Any] | None:
        """Parse a single email into an invoice record."""
        body = email.get("body", "")
        subject = email.get("subject", "")
        combined_text = f"{subject}\n{body}"

        # Extract amount
        amount = self._extract_amount(combined_text)

        # Detect payment status
        status = self._detect_status(combined_text)

        # Extract invoice number if present
        invoice_number = self._extract_invoice_number(combined_text)

        # Determine category from vendor config
        vendor_name = email.get("vendor", "Unknown")
        category = self._get_vendor_category(vendor_name)

        return {
            "date": email.get("date", ""),
            "vendor": vendor_name,
            "amount": amount,
            "status": status,
            "category": category,
            "invoice_number": invoice_number,
            "subject": subject,
            "source_email": email.get("sender", ""),
            "message_id": email.get("message_id", ""),
            "has_attachment": len(email.get("attachments", [])) > 0,
        }

    def _extract_amount(self, text: str) -> float | None:
        """Extract the most likely invoice amount from text.

        Looks for dollar amounts, prioritizing those near keywords like
        'total', 'amount due', 'balance', 'invoice total'.
        """
        if not text:
            return None

        # Priority patterns — amount near key phrases
        priority_patterns = [
            r"(?:total|amount\s*due|balance\s*due|invoice\s*total|grand\s*total)"
            r"[\s:]*\$?([\d,]+\.?\d{0,2})",
            r"\$?([\d,]+\.?\d{0,2})\s*(?:total|due|balance)",
        ]

        for pattern in priority_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                # Take the last match (usually the grand total)
                amount_str = matches[-1].replace(",", "")
                try:
                    amount = float(amount_str)
                    if 0.01 < amount < 1_000_000:  # Sanity check
                        return round(amount, 2)
                except ValueError:
                    continue

        # Fallback: find all dollar amounts and take the largest
        all_amounts = re.findall(r"\$\s*([\d,]+\.?\d{0,2})", text)
        if all_amounts:
            parsed = []
            for a in all_amounts:
                try:
                    val = float(a.replace(",", ""))
                    if 0.01 < val < 1_000_000:
                        parsed.append(val)
                except ValueError:
                    continue
            if parsed:
                return round(max(parsed), 2)

        return None

    def _detect_status(self, text: str) -> str:
        """Detect payment status from email text.

        Returns: 'paid', 'unpaid', 'partial', or 'unknown'.
        """
        text_lower = text.lower()

        paid_signals = [
            "payment received", "paid in full", "thank you for your payment",
            "payment confirmed", "receipt of payment", "payment processed",
            "payment successful",
        ]
        unpaid_signals = [
            "amount due", "balance due", "payment due", "please remit",
            "past due", "overdue", "outstanding balance", "please pay",
            "invoice due",
        ]
        partial_signals = [
            "partial payment", "remaining balance", "balance remaining",
        ]

        if any(signal in text_lower for signal in partial_signals):
            return "partial"
        if any(signal in text_lower for signal in paid_signals):
            return "paid"
        if any(signal in text_lower for signal in unpaid_signals):
            return "unpaid"

        return "unknown"

    def _extract_invoice_number(self, text: str) -> str | None:
        """Extract invoice number from text."""
        patterns = [
            r"invoice\s*#?\s*:?\s*([A-Z0-9][\w-]{2,20})",
            r"inv\s*#?\s*:?\s*([A-Z0-9][\w-]{2,20})",
            r"#\s*([A-Z0-9][\w-]{4,20})",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()

        return None

    def _get_vendor_category(self, vendor_name: str) -> str:
        """Look up expense category for a vendor."""
        for vendor in self.config.vendors:
            if vendor.name.lower() == vendor_name.lower():
                return vendor.category
        return "uncategorized"

    def deduplicate(self, invoices: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Remove duplicate invoices based on vendor + amount + date hash."""
        unique = []
        for inv in invoices:
            h = self._invoice_hash(inv)
            if h not in self._seen_hashes:
                self._seen_hashes.add(h)
                unique.append(inv)
        return unique

    def _invoice_hash(self, invoice: dict[str, Any]) -> str:
        """Generate a dedup hash for an invoice."""
        key = f"{invoice.get('vendor', '')}|{invoice.get('amount', '')}|{invoice.get('date', '')}"
        return hashlib.md5(key.encode()).hexdigest()
