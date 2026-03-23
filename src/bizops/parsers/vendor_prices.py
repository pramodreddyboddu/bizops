"""Vendor price intelligence engine — track prices, detect increases, flag opportunities.

Analyzes invoice history per vendor to:
- Track average cost per invoice over time
- Detect price increases vs prior periods
- Compare vendor spending patterns
- Identify negotiation opportunities based on volume and trends
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from bizops.utils.config import BizOpsConfig


class VendorPriceEngine:
    """Track vendor pricing, detect increases, and flag negotiation opportunities."""

    def __init__(self, config: BizOpsConfig):
        self.config = config

    def get_vendor_spending(
        self,
        invoices: list[dict[str, Any]],
        bank_txns: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Analyze spending by vendor with trends.

        Args:
            invoices: Invoice records with vendor, amount, date.
            bank_txns: Optional bank transactions for additional matching.

        Returns:
            Dict with per-vendor spending summary and rankings.
        """
        vendor_data: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for inv in invoices:
            if inv.get("transaction_type") not in ("payment", None):
                continue
            vendor = inv.get("vendor", "Unknown")
            vendor_data[vendor].append({
                "amount": abs(inv.get("amount", 0)),
                "date": inv.get("date", ""),
            })

        # Add bank transaction data for vendors
        if bank_txns:
            for txn in bank_txns:
                if txn.get("type") != "debit":
                    continue
                desc = (txn.get("description") or "").lower()
                for vc in self.config.vendors:
                    if vc.name.lower() in desc or any(a.lower() in desc for a in vc.aliases):
                        vendor_data[vc.name].append({
                            "amount": abs(txn.get("amount", 0)),
                            "date": txn.get("date", ""),
                            "source": "bank",
                        })
                        break

        # Build summaries
        vendors = []
        for vendor, records in vendor_data.items():
            amounts = [r["amount"] for r in records]
            dates = sorted(r["date"] for r in records if r.get("date"))

            total = sum(amounts)
            avg = total / len(amounts) if amounts else 0
            count = len(amounts)

            # Calculate recent vs older trend
            trend = self._calculate_price_trend(records)

            vendors.append({
                "vendor": vendor,
                "total_spend": round(total, 2),
                "invoice_count": count,
                "avg_per_invoice": round(avg, 2),
                "min_invoice": round(min(amounts), 2) if amounts else 0,
                "max_invoice": round(max(amounts), 2) if amounts else 0,
                "first_date": dates[0] if dates else "",
                "last_date": dates[-1] if dates else "",
                "price_trend": trend,
            })

        # Sort by total spend descending
        vendors.sort(key=lambda v: v["total_spend"], reverse=True)

        total_all = sum(v["total_spend"] for v in vendors)

        return {
            "vendor_count": len(vendors),
            "total_spend": round(total_all, 2),
            "vendors": vendors,
            "top_vendor": vendors[0]["vendor"] if vendors else None,
        }

    def detect_price_changes(
        self,
        current_invoices: list[dict[str, Any]],
        prev_invoices: list[dict[str, Any]],
        threshold_pct: float = 10.0,
    ) -> list[dict[str, Any]]:
        """Detect vendors with significant price changes between periods.

        Args:
            current_invoices: Current period invoices.
            prev_invoices: Previous period invoices.
            threshold_pct: % change to flag.

        Returns:
            List of price change alerts sorted by % change.
        """
        current_by_vendor = self._avg_by_vendor(current_invoices)
        prev_by_vendor = self._avg_by_vendor(prev_invoices)

        changes = []
        for vendor, current_avg in current_by_vendor.items():
            prev_avg = prev_by_vendor.get(vendor)
            if prev_avg is None or prev_avg < 50:
                continue

            pct_change = (current_avg - prev_avg) / prev_avg * 100

            if abs(pct_change) >= threshold_pct:
                changes.append({
                    "vendor": vendor,
                    "current_avg": round(current_avg, 2),
                    "previous_avg": round(prev_avg, 2),
                    "pct_change": round(pct_change, 1),
                    "direction": "up" if pct_change > 0 else "down",
                    "impact": "negative" if pct_change > 0 else "positive",
                })

        # Sort by absolute change descending
        changes.sort(key=lambda c: abs(c["pct_change"]), reverse=True)
        return changes

    def get_negotiation_targets(
        self,
        invoices: list[dict[str, Any]],
        prev_invoices: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Identify vendors where negotiation could save money.

        Criteria:
        - High spend volume (top vendors)
        - Price increases detected
        - High invoice variance (inconsistent pricing)
        - Single-source categories (no alternatives)

        Args:
            invoices: Current period invoices.
            prev_invoices: Optional previous period for comparison.

        Returns:
            List of negotiation targets with reasons and estimated savings.
        """
        spending = self.get_vendor_spending(invoices)
        changes = self.detect_price_changes(invoices, prev_invoices or []) if prev_invoices else []

        targets = []
        total_spend = spending["total_spend"]

        for v in spending["vendors"]:
            reasons = []
            priority = "low"
            est_savings = 0

            # High spend concentration
            if total_spend > 0:
                spend_pct = v["total_spend"] / total_spend * 100
                if spend_pct >= 25:
                    reasons.append(f"Top vendor at {spend_pct:.0f}% of total spend — leverage volume for discount")
                    est_savings += v["total_spend"] * 0.05  # 5% volume discount potential
                    priority = "high"

            # Price increase detected
            change = next((c for c in changes if c["vendor"] == v["vendor"] and c["direction"] == "up"), None)
            if change:
                reasons.append(f"Prices up {change['pct_change']}% vs last period")
                est_savings += v["total_spend"] * abs(change["pct_change"]) / 200  # half the increase
                priority = "high" if change["pct_change"] > 15 else max(priority, "medium")

            # High variance (inconsistent pricing)
            if v["max_invoice"] > 0 and v["min_invoice"] > 0:
                variance_ratio = v["max_invoice"] / v["min_invoice"]
                if variance_ratio > 2.0 and v["invoice_count"] >= 3:
                    reasons.append(f"High price variance ({variance_ratio:.1f}x range) — request consistent pricing")
                    priority = max(priority, "medium")

            # Frequent small orders (consolidation opportunity)
            if v["invoice_count"] >= 8 and v["avg_per_invoice"] < 300:
                reasons.append(f"{v['invoice_count']} orders averaging ${v['avg_per_invoice']:.0f} — consolidate for better rates")
                est_savings += v["invoice_count"] * 10  # ~$10 saved per consolidated order
                priority = max(priority, "medium")

            if reasons:
                targets.append({
                    "vendor": v["vendor"],
                    "total_spend": v["total_spend"],
                    "priority": priority,
                    "reasons": reasons,
                    "est_monthly_savings": round(est_savings, 2),
                })

        # Sort by priority then savings
        priority_order = {"high": 0, "medium": 1, "low": 2}
        targets.sort(key=lambda t: (priority_order.get(t["priority"], 3), -t["est_monthly_savings"]))

        return targets

    def get_vendor_comparison(
        self,
        invoices: list[dict[str, Any]],
        category: str | None = None,
    ) -> dict[str, Any]:
        """Compare vendors within the same category.

        Args:
            invoices: Invoice records.
            category: Optional category filter (e.g., "food_supplies").

        Returns:
            Dict with category-grouped vendor comparisons.
        """
        # Group vendors by category from config
        vendor_categories: dict[str, str] = {}
        for vc in self.config.vendors:
            vendor_categories[vc.name] = vc.category

        # Build per-category vendor lists
        categories: dict[str, list[dict[str, Any]]] = defaultdict(list)

        vendor_spend = self._sum_by_vendor(invoices)
        for vendor, total in vendor_spend.items():
            cat = vendor_categories.get(vendor, "uncategorized")
            if category and cat != category:
                continue
            categories[cat].append({
                "vendor": vendor,
                "total_spend": round(total, 2),
            })

        # Sort within each category
        comparisons = {}
        for cat, vendors in categories.items():
            vendors.sort(key=lambda v: v["total_spend"], reverse=True)
            cat_total = sum(v["total_spend"] for v in vendors)
            for v in vendors:
                v["pct_of_category"] = round(v["total_spend"] / cat_total * 100, 1) if cat_total > 0 else 0
            comparisons[cat] = {
                "vendors": vendors,
                "total": round(cat_total, 2),
                "vendor_count": len(vendors),
            }

        return {
            "categories": comparisons,
            "filter": category,
        }

    # ── Helpers ────────────────────────────────────────────────

    def _avg_by_vendor(self, invoices: list[dict[str, Any]]) -> dict[str, float]:
        """Calculate average invoice amount by vendor."""
        totals: dict[str, list[float]] = defaultdict(list)
        for inv in invoices:
            if inv.get("transaction_type") not in ("payment", None):
                continue
            vendor = inv.get("vendor", "Unknown")
            totals[vendor].append(abs(inv.get("amount", 0)))

        return {
            vendor: sum(amounts) / len(amounts)
            for vendor, amounts in totals.items()
            if amounts
        }

    def _sum_by_vendor(self, invoices: list[dict[str, Any]]) -> dict[str, float]:
        """Sum invoice amounts by vendor."""
        totals: dict[str, float] = defaultdict(float)
        for inv in invoices:
            if inv.get("transaction_type") not in ("payment", None):
                continue
            vendor = inv.get("vendor", "Unknown")
            totals[vendor] += abs(inv.get("amount", 0))
        return dict(totals)

    def _calculate_price_trend(self, records: list[dict[str, Any]]) -> str:
        """Calculate price trend from records (recent vs older)."""
        if len(records) < 4:
            return "insufficient_data"

        sorted_records = sorted(records, key=lambda r: r.get("date", ""))
        mid = len(sorted_records) // 2

        older = sorted_records[:mid]
        recent = sorted_records[mid:]

        older_avg = sum(r["amount"] for r in older) / len(older)
        recent_avg = sum(r["amount"] for r in recent) / len(recent)

        if older_avg == 0:
            return "flat"

        pct_change = (recent_avg - older_avg) / older_avg * 100
        if pct_change > 5:
            return "increasing"
        elif pct_change < -5:
            return "decreasing"
        return "stable"
