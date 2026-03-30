"""Vendor payment intelligence — track who's paid, pending, overdue, and cash forecast.

Connects invoices (money owed) with bank transactions (money paid) to give the
owner a clear view of vendor payment status and upcoming cash needs.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from bizops.utils.config import BizOpsConfig

# Payment terms → days until due
TERMS_DAYS = {
    "cod": 0,
    "net7": 7,
    "net15": 15,
    "net30": 30,
    "weekly": 7,
}


class PaymentEngine:
    """Track vendor payments, detect overdue invoices, and forecast cash needs."""

    def __init__(self, config: BizOpsConfig):
        self.config = config
        self._vendor_terms: dict[str, str] = {}
        for v in config.vendors:
            self._vendor_terms[v.name.lower()] = v.payment_terms
            for alias in v.aliases:
                self._vendor_terms[alias.lower()] = v.payment_terms

    def get_payment_status(
        self,
        invoices: list[dict[str, Any]],
        bank_txns: list[dict[str, Any]],
        as_of_date: str | None = None,
    ) -> dict[str, Any]:
        """Determine payment status for each vendor.

        Cross-references invoices against bank debits to classify each
        invoice as paid, likely_paid, or unpaid.

        Args:
            invoices: Invoice list from storage.
            bank_txns: Bank transaction list from storage.
            as_of_date: Reference date (YYYY-MM-DD). Defaults to today.

        Returns:
            Dict with vendor_payments list, summary stats, and overdue items.
        """
        if as_of_date is None:
            as_of_date = datetime.now().strftime("%Y-%m-%d")

        # Index bank debits by vendor for fast lookup
        bank_payments = self._index_bank_payments(bank_txns)

        vendor_results: dict[str, dict[str, Any]] = {}

        for inv in invoices:
            # Only track payment invoices (money out)
            if inv.get("transaction_type") not in ("payment", None):
                if inv.get("transaction_type") != "payment":
                    continue

            vendor = inv.get("vendor", "Unknown")
            amount = abs(inv.get("amount") or 0)
            inv_date = inv.get("date", "")

            if vendor not in vendor_results:
                vendor_results[vendor] = {
                    "vendor": vendor,
                    "total_invoiced": 0.0,
                    "total_paid": 0.0,
                    "invoices": [],
                }

            # Determine payment terms for this vendor
            terms = self._get_terms(vendor)
            due_days = TERMS_DAYS.get(terms, 0)
            due_date = ""
            if inv_date:
                try:
                    inv_dt = datetime.strptime(inv_date, "%Y-%m-%d")
                    due_date = (inv_dt + timedelta(days=due_days)).strftime("%Y-%m-%d")
                except ValueError:
                    pass

            # Check if this invoice appears paid in bank
            is_paid, matched_txn = self._find_payment(
                vendor, amount, inv_date, bank_payments
            )

            status = "paid" if is_paid else "unpaid"
            if not is_paid and due_date and due_date < as_of_date:
                status = "overdue"

            inv_entry = {
                "date": inv_date,
                "amount": round(amount, 2),
                "status": status,
                "payment_terms": terms,
                "due_date": due_date,
                "matched_bank_txn": matched_txn,
                "subject": inv.get("subject", ""),
            }

            vendor_results[vendor]["invoices"].append(inv_entry)
            vendor_results[vendor]["total_invoiced"] += amount
            if is_paid:
                vendor_results[vendor]["total_paid"] += amount

        # Build summary
        vendors = list(vendor_results.values())
        for v in vendors:
            v["total_invoiced"] = round(v["total_invoiced"], 2)
            v["total_paid"] = round(v["total_paid"], 2)
            v["balance_due"] = round(v["total_invoiced"] - v["total_paid"], 2)
            v["paid_count"] = sum(1 for i in v["invoices"] if i["status"] == "paid")
            v["unpaid_count"] = sum(1 for i in v["invoices"] if i["status"] == "unpaid")
            v["overdue_count"] = sum(1 for i in v["invoices"] if i["status"] == "overdue")

        total_invoiced = sum(v["total_invoiced"] for v in vendors)
        total_paid = sum(v["total_paid"] for v in vendors)
        total_overdue = sum(
            i["amount"]
            for v in vendors
            for i in v["invoices"]
            if i["status"] == "overdue"
        )

        return {
            "as_of_date": as_of_date,
            "vendors": sorted(vendors, key=lambda v: v["balance_due"], reverse=True),
            "summary": {
                "total_vendors": len(vendors),
                "total_invoiced": round(total_invoiced, 2),
                "total_paid": round(total_paid, 2),
                "total_outstanding": round(total_invoiced - total_paid, 2),
                "total_overdue": round(total_overdue, 2),
                "overdue_vendor_count": sum(1 for v in vendors if v["overdue_count"] > 0),
            },
        }

    def get_payment_calendar(
        self,
        invoices: list[dict[str, Any]],
        bank_txns: list[dict[str, Any]],
        days_ahead: int = 14,
    ) -> list[dict[str, Any]]:
        """Get upcoming payment due dates.

        Args:
            invoices: Invoice list.
            bank_txns: Bank transactions.
            days_ahead: How many days ahead to look.

        Returns:
            List of upcoming payments sorted by due date.
        """
        status = self.get_payment_status(invoices, bank_txns)
        today = datetime.now()
        cutoff = (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
        today_str = today.strftime("%Y-%m-%d")

        upcoming = []
        for vendor in status["vendors"]:
            for inv in vendor["invoices"]:
                if inv["status"] in ("unpaid", "overdue") and inv["due_date"]:
                    if inv["due_date"] <= cutoff:
                        upcoming.append({
                            "vendor": vendor["vendor"],
                            "amount": inv["amount"],
                            "due_date": inv["due_date"],
                            "is_overdue": inv["due_date"] < today_str,
                            "days_until_due": (
                                datetime.strptime(inv["due_date"], "%Y-%m-%d") - today
                            ).days,
                            "payment_terms": inv["payment_terms"],
                        })

        return sorted(upcoming, key=lambda x: x["due_date"])

    def get_cash_forecast(
        self,
        invoices: list[dict[str, Any]],
        bank_txns: list[dict[str, Any]],
        toast_data: list[dict[str, Any]] | None = None,
        days_ahead: int = 14,
    ) -> dict[str, Any]:
        """Forecast cash position based on upcoming payments and expected income.

        Args:
            invoices: Invoice list.
            bank_txns: Bank transactions.
            toast_data: Toast POS reports for revenue estimation.
            days_ahead: Days to forecast.

        Returns:
            Dict with current balance, upcoming payments, projected income, and daily forecast.
        """
        today = datetime.now()
        today_str = today.strftime("%Y-%m-%d")

        # Estimate current balance from bank transactions
        credits = sum(t.get("amount", 0) for t in bank_txns if t.get("type") == "credit")
        debits = sum(t.get("amount", 0) for t in bank_txns if t.get("type") == "debit")
        current_balance = credits + debits  # debits are negative

        # Get upcoming payments
        upcoming = self.get_payment_calendar(invoices, bank_txns, days_ahead)
        total_upcoming = sum(p["amount"] for p in upcoming)

        # Estimate daily income from Toast
        avg_daily_income = 0.0
        if toast_data:
            recent = toast_data[-14:] if len(toast_data) >= 14 else toast_data
            if recent:
                avg_daily_income = sum(r.get("net_sales", 0) for r in recent) / len(recent)

        projected_income = round(avg_daily_income * days_ahead, 2)

        # Daily forecast
        daily_forecast = []
        running_balance = current_balance

        for day_offset in range(days_ahead):
            forecast_date = (today + timedelta(days=day_offset)).strftime("%Y-%m-%d")
            day_payments = sum(p["amount"] for p in upcoming if p["due_date"] == forecast_date)

            running_balance += avg_daily_income - day_payments
            daily_forecast.append({
                "date": forecast_date,
                "projected_balance": round(running_balance, 2),
                "payments_due": round(day_payments, 2),
                "expected_income": round(avg_daily_income, 2),
            })

        # Find danger days (balance goes below threshold)
        danger_days = [
            d for d in daily_forecast
            if d["projected_balance"] < 2000
        ]

        return {
            "as_of_date": today_str,
            "current_balance": round(current_balance, 2),
            "upcoming_payments": round(total_upcoming, 2),
            "projected_income": projected_income,
            "projected_end_balance": round(
                current_balance + projected_income - total_upcoming, 2
            ),
            "avg_daily_income": round(avg_daily_income, 2),
            "days_forecast": days_ahead,
            "danger_days": danger_days,
            "payment_calendar": upcoming,
            "daily_forecast": daily_forecast,
        }

    def get_vendor_payment_history(
        self,
        vendor_name: str,
        invoices: list[dict[str, Any]],
        bank_txns: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Get detailed payment history for a specific vendor.

        Args:
            vendor_name: Vendor name to look up.
            invoices: Invoice list.
            bank_txns: Bank transactions.

        Returns:
            Dict with vendor payment history, avg days to pay, and reliability score.
        """
        status = self.get_payment_status(invoices, bank_txns)
        vendor_data = None
        for v in status["vendors"]:
            if v["vendor"].lower() == vendor_name.lower():
                vendor_data = v
                break

        if not vendor_data:
            return {"vendor": vendor_name, "message": "No payment history found."}

        # Calculate avg days to pay for paid invoices
        days_to_pay = []
        for inv in vendor_data["invoices"]:
            if inv["status"] == "paid" and inv["date"] and inv.get("matched_bank_txn"):
                try:
                    inv_dt = datetime.strptime(inv["date"], "%Y-%m-%d")
                    pay_dt = datetime.strptime(inv["matched_bank_txn"]["date"], "%Y-%m-%d")
                    days_to_pay.append((pay_dt - inv_dt).days)
                except (ValueError, KeyError):
                    pass

        avg_days = round(sum(days_to_pay) / len(days_to_pay), 1) if days_to_pay else None
        terms = self._get_terms(vendor_name)

        return {
            "vendor": vendor_name,
            "payment_terms": terms,
            "total_invoiced": vendor_data["total_invoiced"],
            "total_paid": vendor_data["total_paid"],
            "balance_due": vendor_data["balance_due"],
            "paid_count": vendor_data["paid_count"],
            "unpaid_count": vendor_data["unpaid_count"],
            "overdue_count": vendor_data["overdue_count"],
            "avg_days_to_pay": avg_days,
            "invoices": vendor_data["invoices"],
        }

    # ── Private helpers ───────────────────────────────────────

    def _get_terms(self, vendor: str) -> str:
        """Look up payment terms for a vendor."""
        return self._vendor_terms.get(vendor.lower(), "cod")

    def _index_bank_payments(
        self, bank_txns: list[dict[str, Any]]
    ) -> dict[str, list[dict[str, Any]]]:
        """Index bank debits by rough vendor name for matching.

        Returns:
            Dict mapping lowercased description fragments to transaction lists.
        """
        index: dict[str, list[dict[str, Any]]] = {}
        for txn in bank_txns:
            if txn.get("type") != "debit":
                continue
            desc = (txn.get("description") or "").lower()
            # Index by each word in description for fuzzy matching
            for word in desc.split():
                if len(word) >= 3:  # skip tiny words
                    if word not in index:
                        index[word] = []
                    index[word].append(txn)
        return index

    def _find_payment(
        self,
        vendor: str,
        amount: float,
        inv_date: str,
        bank_index: dict[str, list[dict[str, Any]]],
        tolerance_days: int = 5,
        tolerance_pct: float = 0.02,
    ) -> tuple[bool, dict[str, Any] | None]:
        """Try to find a matching bank payment for an invoice.

        Matches on: vendor name in description + amount within tolerance + date proximity.

        Returns:
            (is_paid, matched_transaction_or_None)
        """
        vendor_lower = vendor.lower()
        # Get vendor words and aliases
        search_words = [w for w in vendor_lower.split() if len(w) >= 3]

        # Also check config aliases
        for vc in self.config.vendors:
            if vc.name.lower() == vendor_lower:
                search_words.extend(a.lower() for a in vc.aliases)
                break

        # Collect candidate transactions
        candidates: set[int] = set()  # track by id to avoid dupes
        candidate_txns: list[dict[str, Any]] = []
        for word in search_words:
            for txn in bank_index.get(word, []):
                txn_id = id(txn)
                if txn_id not in candidates:
                    candidates.add(txn_id)
                    candidate_txns.append(txn)

        if not candidate_txns or not inv_date:
            return False, None

        # Score candidates
        best_match = None
        best_score = 0.0

        try:
            inv_dt = datetime.strptime(inv_date, "%Y-%m-%d")
        except ValueError:
            return False, None

        for txn in candidate_txns:
            txn_amount = abs(txn.get("amount", 0))
            if txn_amount == 0:
                continue

            # Amount match (within tolerance %)
            amount_diff = abs(txn_amount - amount)
            if amount_diff > amount * tolerance_pct and amount_diff > 1.0:
                continue

            # Date proximity
            try:
                txn_dt = datetime.strptime(txn.get("date", ""), "%Y-%m-%d")
            except ValueError:
                continue

            day_diff = abs((txn_dt - inv_dt).days)
            if day_diff > tolerance_days:
                continue

            # Score: closer date + closer amount = better
            score = 1.0
            if day_diff == 0:
                score += 0.5
            else:
                score += 0.5 * (1 - day_diff / (tolerance_days + 1))
            if amount_diff == 0:
                score += 0.3

            if score > best_score:
                best_score = score
                best_match = {
                    "date": txn.get("date", ""),
                    "description": txn.get("description", ""),
                    "amount": txn.get("amount", 0),
                }

        return (best_match is not None, best_match)
