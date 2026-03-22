"""Reconciliation engine — match bank transactions against Gmail invoice data."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from bizops.utils.config import BizOpsConfig


class ReconciliationEngine:
    """Match bank transactions to invoices for reconciliation and cash flow analysis."""

    def __init__(
        self,
        config: BizOpsConfig,
        tolerance_days: int = 3,
        tolerance_amount: float = 0.01,
    ) -> None:
        self.config = config
        self.tolerance_days = tolerance_days
        self.tolerance_amount = tolerance_amount

    def reconcile(
        self,
        bank_txns: list[dict[str, Any]],
        invoices: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Match bank transactions against invoices.

        Returns a result dict with matched pairs, unmatched items, and summary stats.
        """
        # Only reconcile debits (money out) against payment invoices
        debit_txns = [t for t in bank_txns if t.get("type") == "debit"]
        credit_txns = [t for t in bank_txns if t.get("type") == "credit"]

        # Track which invoices have been matched
        available_invoices = list(invoices)
        matched: list[dict[str, Any]] = []
        unmatched_bank: list[dict[str, Any]] = []

        for txn in debit_txns:
            best_match = self._find_match(txn, available_invoices)
            if best_match:
                invoice, score, match_type = best_match
                matched.append({
                    "bank_txn": txn,
                    "invoice": invoice,
                    "match_score": score,
                    "match_type": match_type,
                })
                available_invoices.remove(invoice)
                # Mark the bank txn as reconciled
                txn["reconciled"] = True
                txn["matched_invoice_id"] = invoice.get("message_id")
            else:
                unmatched_bank.append(txn)

        # Credits that didn't match anything are also unmatched bank items
        unmatched_bank.extend(credit_txns)

        # Remaining invoices are unmatched
        unmatched_invoices = available_invoices

        # Build summary
        total_bank_debits = sum(t.get("amount", 0) for t in debit_txns)
        total_bank_credits = sum(t.get("amount", 0) for t in credit_txns)

        summary = {
            "total_bank_txns": len(bank_txns),
            "total_invoices": len(invoices),
            "matched_count": len(matched),
            "match_rate": round(
                (len(matched) / len(debit_txns) * 100) if debit_txns else 0, 1
            ),
            "unmatched_bank_count": len(unmatched_bank),
            "unmatched_invoice_count": len(unmatched_invoices),
            "total_bank_debits": round(total_bank_debits, 2),
            "total_bank_credits": round(total_bank_credits, 2),
            "net_bank_flow": round(total_bank_debits + total_bank_credits, 2),
        }

        return {
            "matched": matched,
            "unmatched_bank": unmatched_bank,
            "unmatched_invoices": unmatched_invoices,
            "summary": summary,
        }

    def get_cash_flow(self, bank_txns: list[dict[str, Any]]) -> dict[str, Any]:
        """Build a complete cash flow breakdown from bank transactions."""
        debits_by_cat: dict[str, list[dict[str, Any]]] = {}
        credits_by_cat: dict[str, list[dict[str, Any]]] = {}

        for txn in bank_txns:
            cat = txn.get("category", "uncategorized")
            if txn.get("type") == "debit":
                debits_by_cat.setdefault(cat, []).append(txn)
            else:
                credits_by_cat.setdefault(cat, []).append(txn)

        # Build category summaries
        expense_categories: dict[str, dict[str, Any]] = {}
        for cat, items in sorted(debits_by_cat.items()):
            total = sum(t.get("amount", 0) for t in items)
            expense_categories[cat] = {
                "total": round(total, 2),
                "count": len(items),
                "transactions": items,
            }

        income_categories: dict[str, dict[str, Any]] = {}
        for cat, items in sorted(credits_by_cat.items()):
            total = sum(t.get("amount", 0) for t in items)
            income_categories[cat] = {
                "total": round(total, 2),
                "count": len(items),
                "transactions": items,
            }

        total_out = sum(c["total"] for c in expense_categories.values())
        total_in = sum(c["total"] for c in income_categories.values())

        return {
            "expenses": expense_categories,
            "income": income_categories,
            "total_expenses": round(total_out, 2),
            "total_income": round(total_in, 2),
            "net_cash_flow": round(total_in + total_out, 2),  # debits are negative
            "transaction_count": len(bank_txns),
        }

    def _find_match(
        self,
        txn: dict[str, Any],
        invoices: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], float, str] | None:
        """Find the best matching invoice for a bank transaction.

        Returns (invoice, score, match_type) or None.
        """
        txn_amount = abs(txn.get("amount", 0))
        txn_date = txn.get("date", "")

        if not txn_date or txn_amount == 0:
            return None

        try:
            txn_dt = datetime.strptime(txn_date, "%Y-%m-%d")
        except ValueError:
            return None

        candidates: list[tuple[dict[str, Any], float, str]] = []

        for inv in invoices:
            inv_amount = inv.get("amount") or 0
            inv_date = inv.get("date", "")

            if not inv_date or inv_amount == 0:
                continue

            # Amount must be close
            if abs(txn_amount - inv_amount) > self.tolerance_amount:
                continue

            # Date must be within tolerance
            try:
                inv_dt = datetime.strptime(inv_date, "%Y-%m-%d")
            except ValueError:
                continue

            day_diff = abs((txn_dt - inv_dt).days)
            if day_diff > self.tolerance_days:
                continue

            # Compute score
            score = self._compute_match_score(txn, inv, day_diff)
            match_type = "exact" if day_diff == 0 else "close_date"

            # Boost if vendor name appears in description
            desc_lower = txn.get("description", "").lower()
            vendor_lower = (inv.get("vendor") or "").lower()
            if vendor_lower and vendor_lower in desc_lower:
                score += 0.3
                match_type = "vendor_match"

            candidates.append((inv, score, match_type))

        if not candidates:
            return None

        # Return the best match
        candidates.sort(key=lambda c: c[1], reverse=True)
        return candidates[0]

    def _compute_match_score(
        self,
        txn: dict[str, Any],
        inv: dict[str, Any],
        day_diff: int,
    ) -> float:
        """Compute a numeric match score (higher = better)."""
        score = 1.0

        # Exact date = bonus
        if day_diff == 0:
            score += 0.5
        else:
            # Closer dates score higher
            score += 0.5 * (1 - day_diff / (self.tolerance_days + 1))

        # Exact amount = bonus
        txn_amount = abs(txn.get("amount", 0))
        inv_amount = inv.get("amount") or 0
        if abs(txn_amount - inv_amount) < 0.01:
            score += 0.2

        return round(score, 3)
