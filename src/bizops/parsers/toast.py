"""Toast POS parser — extract structured data from Toast daily summary emails.

Handles daily sales reports from Toast POS system (noreply@toasttab.com).
Extracts gross/net sales, tax, tips, refunds, order counts, and payment breakdowns.
"""

from __future__ import annotations

import re
from typing import Any

TOAST_SENDER = "noreply@toasttab.com"
TOAST_SUBJECT_PATTERNS = ["daily summary", "daily report"]


class ToastPOSParser:
    """Parse Toast POS daily summary emails into structured report data."""

    def __init__(self) -> None:
        self._amount_pattern = re.compile(
            r"\$\s*([\d,]+\.?\d{0,2})"
        )

    def parse_daily_reports(
        self, emails: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Parse a list of raw email dicts into structured Toast report records.

        Args:
            emails: List of email dicts (same format as GmailConnector returns).

        Returns:
            List of parsed report dicts. Non-Toast emails are skipped.
        """
        reports: list[dict[str, Any]] = []
        for email in emails:
            report = self._parse_single(email)
            if report is not None:
                reports.append(report)
        return reports

    def parse_date_range(
        self,
        start_date: str,
        end_date: str,
        gmail_connector: Any,
    ) -> list[dict[str, Any]]:
        """Fetch Toast emails for a date range and return parsed reports.

        Args:
            start_date: Start date as YYYY-MM-DD.
            end_date: End date as YYYY-MM-DD.
            gmail_connector: A GmailConnector instance used to fetch emails.

        Returns:
            List of parsed report dicts.
        """
        emails = gmail_connector.search_invoices(
            start_date=start_date,
            end_date=end_date,
            vendor_filter="Toast",
        )

        # Filter to only Toast daily summary/report emails
        toast_emails = [
            e for e in emails
            if self._is_toast_daily_email(e)
        ]

        return self.parse_daily_reports(toast_emails)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_toast_daily_email(self, email: dict[str, Any]) -> bool:
        """Check if an email is a Toast daily summary/report."""
        sender = email.get("sender", "").lower()
        subject = email.get("subject", "").lower()

        sender_match = TOAST_SENDER in sender
        subject_match = any(p in subject for p in TOAST_SUBJECT_PATTERNS)

        return sender_match and subject_match

    def _parse_single(self, email: dict[str, Any]) -> dict[str, Any] | None:
        """Parse a single email into a Toast daily report record.

        Returns None if the email is not a recognizable Toast daily summary.
        """
        if not self._is_toast_daily_email(email):
            return None

        body = email.get("body", "")

        report_date = self._extract_report_date(body, email.get("date", ""))
        gross_sales = self._extract_labelled_amount(body, "gross sales")
        net_sales = self._extract_labelled_amount(body, "net sales")
        tax = self._extract_labelled_amount(body, "tax collected")
        if tax is None:
            tax = self._extract_labelled_amount(body, "tax")
        tips = self._extract_labelled_amount(body, "tips")
        refunds = self._extract_refunds(body)
        total_orders = self._extract_total_orders(body)
        payment_breakdown = self._extract_payment_breakdown(body)

        return {
            "date": report_date,
            "gross_sales": gross_sales,
            "net_sales": net_sales,
            "tax_collected": tax,
            "tips": tips,
            "refunds": refunds,
            "total_orders": total_orders,
            "payment_breakdown": payment_breakdown,
            "subject": email.get("subject", ""),
            "source_email": email.get("sender", ""),
            "message_id": email.get("message_id", ""),
        }

    # ------------------------------------------------------------------
    # Extraction methods
    # ------------------------------------------------------------------

    def _extract_report_date(
        self, body: str, fallback_date: str
    ) -> str | None:
        """Extract the report date from the email body.

        Looks for patterns like 'Date: March 15, 2026' or 'Report for 03/15/2026'.
        Falls back to the email-level date if nothing is found.
        """
        if not body:
            return fallback_date or None

        # Pattern: "March 15, 2026" or "Mar 15, 2026"
        month_day_year = re.search(
            r"(?:date|report\s+for|summary\s+for|for)\s*:?\s*"
            r"([A-Za-z]+\.?\s+\d{1,2},?\s+\d{4})",
            body,
            re.IGNORECASE,
        )
        if month_day_year:
            return month_day_year.group(1).strip()

        # Pattern: MM/DD/YYYY
        slash_date = re.search(
            r"(?:date|report\s+for|summary\s+for|for)\s*:?\s*"
            r"(\d{1,2}/\d{1,2}/\d{4})",
            body,
            re.IGNORECASE,
        )
        if slash_date:
            return slash_date.group(1).strip()

        # Pattern: YYYY-MM-DD
        iso_date = re.search(
            r"(?:date|report\s+for|summary\s+for|for)\s*:?\s*"
            r"(\d{4}-\d{2}-\d{2})",
            body,
            re.IGNORECASE,
        )
        if iso_date:
            return iso_date.group(1).strip()

        return fallback_date or None

    def _extract_labelled_amount(
        self, text: str, label: str
    ) -> float | None:
        """Extract a dollar amount next to a label.

        Handles patterns like:
            Gross Sales: $1,234.56
            Gross Sales   $1,234.56
            Gross Sales     1,234.56
        """
        if not text:
            return None

        # Escape label for regex, allow flexible whitespace and colon
        pattern = (
            rf"{re.escape(label)}"
            r"[\s:]*"
            r"\$?\s*([\d,]+\.?\d{0,2})"
        )
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return self._parse_dollar(match.group(1))
        return None

    def _extract_refunds(self, text: str) -> float | None:
        """Extract refund/void amount from text.

        Looks for 'Refunds', 'Voids', or 'Refunds/Voids'.
        """
        if not text:
            return None

        patterns = [
            r"refunds?\s*/?\s*voids?[\s:]*\$?\s*([\d,]+\.?\d{0,2})",
            r"refunds?[\s:]*\$?\s*([\d,]+\.?\d{0,2})",
            r"voids?[\s:]*\$?\s*([\d,]+\.?\d{0,2})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return self._parse_dollar(match.group(1))
        return None

    def _extract_total_orders(self, text: str) -> int | None:
        """Extract the total number of orders from text."""
        if not text:
            return None

        patterns = [
            r"total\s+orders?[\s:]*(\d+)",
            r"orders?\s+count[\s:]*(\d+)",
            r"(\d+)\s+(?:total\s+)?orders?",
            r"number\s+of\s+orders?[\s:]*(\d+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    return int(match.group(1))
                except ValueError:
                    continue
        return None

    def _extract_payment_breakdown(
        self, text: str
    ) -> dict[str, float | None]:
        """Extract payment method breakdown from text.

        Returns a dict with keys 'cash', 'credit_card', 'other'.
        """
        cash = self._extract_labelled_amount(text, "cash")
        credit_card = (
            self._extract_labelled_amount(text, "credit card")
            or self._extract_labelled_amount(text, "credit")
            or self._extract_labelled_amount(text, "card")
        )
        other = (
            self._extract_labelled_amount(text, "other payments")
            or self._extract_labelled_amount(text, "other")
        )

        return {
            "cash": cash,
            "credit_card": credit_card,
            "other": other,
        }

    def _parse_dollar(self, raw: str) -> float | None:
        """Parse a raw dollar string like '1,234.56' into a float."""
        try:
            value = float(raw.replace(",", ""))
            if value < 0:
                return None
            return round(value, 2)
        except (ValueError, TypeError):
            return None
