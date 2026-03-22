"""Smart alerts and anomaly detection engine.

Scans all business data sources to detect problems proactively:
- Spending spikes by category or vendor
- Missed recurring orders
- Sales anomalies (unusual drops or spikes)
- Seasonal pattern reminders
- Combined cost ratio alerts (food + labor > 60%)
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from bizops.utils.config import BizOpsConfig


class AlertEngine:
    """Detect anomalies and generate proactive business alerts."""

    def __init__(self, config: BizOpsConfig):
        self.config = config

    def scan_all(
        self,
        bank_txns: list[dict[str, Any]],
        toast_data: list[dict[str, Any]],
        invoices: list[dict[str, Any]],
        prev_bank_txns: list[dict[str, Any]] | None = None,
        prev_toast_data: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Run all anomaly checks and return alerts sorted by severity.

        Args:
            bank_txns: Current period bank transactions.
            toast_data: Current period Toast reports.
            invoices: Current period invoices.
            prev_bank_txns: Previous period bank transactions (for comparison).
            prev_toast_data: Previous period Toast reports (for comparison).

        Returns:
            List of alert dicts sorted by severity (critical first).
        """
        alerts = []
        alerts.extend(self.check_spending_spikes(bank_txns, prev_bank_txns or []))
        alerts.extend(self.check_vendor_spikes(invoices, prev_bank_txns or []))
        alerts.extend(self.check_sales_anomalies(toast_data))
        alerts.extend(self.check_missed_orders())
        alerts.extend(self.check_combined_cost_ratio(bank_txns, toast_data))
        alerts.extend(self.check_large_transactions(bank_txns))

        # Sort: critical > warning > info
        severity_order = {"critical": 0, "warning": 1, "info": 2}
        alerts.sort(key=lambda a: severity_order.get(a.get("severity", "info"), 3))

        return alerts

    def check_spending_spikes(
        self,
        current_txns: list[dict[str, Any]],
        prev_txns: list[dict[str, Any]],
        threshold_pct: float = 40.0,
    ) -> list[dict[str, Any]]:
        """Detect category spending that jumped significantly vs prior period.

        Args:
            current_txns: Current period bank debits.
            prev_txns: Previous period bank debits.
            threshold_pct: Percentage increase to trigger alert.

        Returns:
            List of spending spike alerts.
        """
        if not prev_txns:
            return []

        current_by_cat = self._sum_debits_by_category(current_txns)
        prev_by_cat = self._sum_debits_by_category(prev_txns)

        alerts = []
        for cat, current_total in current_by_cat.items():
            prev_total = prev_by_cat.get(cat, 0)
            if prev_total < 100:  # skip tiny categories
                continue

            pct_change = ((current_total - prev_total) / prev_total) * 100
            if pct_change >= threshold_pct:
                label = cat.replace("_", " ").title()
                alerts.append({
                    "type": "spending_spike",
                    "severity": "warning",
                    "category": cat,
                    "message": f"{label} spending up {pct_change:.0f}% vs last period (${current_total:,.0f} vs ${prev_total:,.0f})",
                    "current": round(current_total, 2),
                    "previous": round(prev_total, 2),
                    "pct_change": round(pct_change, 1),
                    "source": "spending",
                })

        return alerts

    def check_vendor_spikes(
        self,
        invoices: list[dict[str, Any]],
        prev_txns: list[dict[str, Any]],
        threshold_pct: float = 50.0,
    ) -> list[dict[str, Any]]:
        """Detect vendors where spending jumped significantly.

        Args:
            invoices: Current period invoices.
            prev_txns: Previous period bank transactions.
            threshold_pct: Percentage increase to trigger.

        Returns:
            List of vendor spike alerts.
        """
        if not prev_txns:
            return []

        # Current period by vendor (from invoices)
        current_by_vendor: dict[str, float] = {}
        for inv in invoices:
            vendor = inv.get("vendor", "Unknown")
            current_by_vendor[vendor] = current_by_vendor.get(vendor, 0) + abs(inv.get("amount", 0))

        # Previous period by rough vendor match (from bank descriptions)
        prev_by_vendor: dict[str, float] = {}
        for txn in prev_txns:
            if txn.get("type") != "debit":
                continue
            desc = (txn.get("description") or "").lower()
            for vc in self.config.vendors:
                vc_lower = vc.name.lower()
                if vc_lower in desc or any(a.lower() in desc for a in vc.aliases):
                    prev_by_vendor[vc.name] = prev_by_vendor.get(vc.name, 0) + abs(txn.get("amount", 0))
                    break

        alerts = []
        for vendor, current_total in current_by_vendor.items():
            prev_total = prev_by_vendor.get(vendor, 0)
            if prev_total < 100:
                continue

            pct_change = ((current_total - prev_total) / prev_total) * 100
            if pct_change >= threshold_pct:
                alerts.append({
                    "type": "vendor_spike",
                    "severity": "warning",
                    "vendor": vendor,
                    "message": f"{vendor} spending up {pct_change:.0f}% (${current_total:,.0f} vs ${prev_total:,.0f})",
                    "current": round(current_total, 2),
                    "previous": round(prev_total, 2),
                    "pct_change": round(pct_change, 1),
                    "source": "vendor",
                })

        return alerts

    def check_sales_anomalies(
        self,
        toast_data: list[dict[str, Any]],
        lookback_days: int = 14,
        threshold_pct: float = 25.0,
    ) -> list[dict[str, Any]]:
        """Detect days with unusual sales vs rolling average.

        Args:
            toast_data: Toast POS daily reports.
            lookback_days: Days for rolling average.
            threshold_pct: % deviation to flag.

        Returns:
            Alerts for recent anomalous sales days.
        """
        if len(toast_data) < 3:
            return []

        sorted_reports = sorted(toast_data, key=lambda r: r.get("date", ""))

        # Calculate rolling average
        all_sales = [r.get("net_sales", 0) for r in sorted_reports]
        if not all_sales:
            return []

        avg_sales = sum(all_sales) / len(all_sales)
        if avg_sales < 100:
            return []

        alerts = []
        # Check the most recent 3 days
        recent = sorted_reports[-3:]
        for report in recent:
            daily_sales = report.get("net_sales", 0)
            pct_diff = ((daily_sales - avg_sales) / avg_sales) * 100

            if pct_diff < -threshold_pct:
                alerts.append({
                    "type": "sales_drop",
                    "severity": "warning",
                    "date": report.get("date", ""),
                    "message": f"Sales on {report.get('date', '?')} were ${daily_sales:,.0f} — {abs(pct_diff):.0f}% below average (${avg_sales:,.0f})",
                    "daily_sales": round(daily_sales, 2),
                    "avg_sales": round(avg_sales, 2),
                    "pct_diff": round(pct_diff, 1),
                    "source": "sales",
                })
            elif pct_diff > threshold_pct * 2:  # big spike = info (good news)
                alerts.append({
                    "type": "sales_spike",
                    "severity": "info",
                    "date": report.get("date", ""),
                    "message": f"Sales on {report.get('date', '?')} were ${daily_sales:,.0f} — {pct_diff:.0f}% above average. Stock up!",
                    "daily_sales": round(daily_sales, 2),
                    "avg_sales": round(avg_sales, 2),
                    "pct_diff": round(pct_diff, 1),
                    "source": "sales",
                })

        return alerts

    def check_missed_orders(self) -> list[dict[str, Any]]:
        """Check if any vendor's order day was missed recently.

        Compares vendor order_day config against today's weekday
        to alert if an order should have been placed.

        Returns:
            Alerts for potentially missed orders.
        """
        today = datetime.now()
        today_dow = today.weekday()  # 0=Mon

        alerts = []
        for vendor in self.config.vendors:
            if vendor.order_day < 0:
                continue

            active_products = [p for p in vendor.products if p.active]
            if not active_products:
                continue

            # If order day was yesterday or today, remind
            days_since_order_day = (today_dow - vendor.order_day) % 7
            if days_since_order_day == 0:
                alerts.append({
                    "type": "order_reminder",
                    "severity": "info",
                    "vendor": vendor.name,
                    "message": f"Today is {vendor.name} order day — {len(active_products)} products to review",
                    "product_count": len(active_products),
                    "source": "ordering",
                })
            elif days_since_order_day == 1:
                alerts.append({
                    "type": "order_missed",
                    "severity": "warning",
                    "vendor": vendor.name,
                    "message": f"Yesterday was {vendor.name} order day — did you place the order?",
                    "product_count": len(active_products),
                    "source": "ordering",
                })

        return alerts

    def check_combined_cost_ratio(
        self,
        bank_txns: list[dict[str, Any]],
        toast_data: list[dict[str, Any]],
        threshold_pct: float = 65.0,
    ) -> list[dict[str, Any]]:
        """Check if food + labor costs exceed a healthy ratio of revenue.

        Industry rule: food + labor should be under 60-65% of revenue.

        Args:
            bank_txns: Bank transactions (for labor/food costs).
            toast_data: Toast data (for revenue).
            threshold_pct: Combined cost threshold.

        Returns:
            Alert if prime cost ratio is too high.
        """
        net_sales = sum(r.get("net_sales", 0) for r in toast_data)
        if net_sales < 100:
            return []

        food_categories = {"food_supplies", "produce", "meat", "beverages"}
        food_total = 0.0
        labor_total = 0.0

        for txn in bank_txns:
            if txn.get("type") != "debit":
                continue
            cat = txn.get("category", "")
            amount = abs(txn.get("amount", 0))
            if cat in food_categories:
                food_total += amount
            elif cat == "payroll":
                labor_total += amount

        prime_cost = food_total + labor_total
        prime_pct = (prime_cost / net_sales) * 100

        if prime_pct >= threshold_pct:
            return [{
                "type": "prime_cost_high",
                "severity": "critical" if prime_pct >= 70 else "warning",
                "message": f"Prime cost (food + labor) at {prime_pct:.1f}% of revenue — target is under {threshold_pct:.0f}%",
                "food_pct": round(food_total / net_sales * 100, 1),
                "labor_pct": round(labor_total / net_sales * 100, 1),
                "prime_pct": round(prime_pct, 1),
                "source": "cost_ratio",
            }]

        return []

    def check_large_transactions(
        self,
        bank_txns: list[dict[str, Any]],
        threshold: float = 5000.0,
    ) -> list[dict[str, Any]]:
        """Flag unusually large individual transactions for review.

        Args:
            bank_txns: Bank transactions.
            threshold: Dollar amount to flag.

        Returns:
            Alerts for large debits.
        """
        alerts = []
        for txn in bank_txns:
            if txn.get("type") != "debit":
                continue
            amount = abs(txn.get("amount", 0))
            if amount >= threshold:
                desc = txn.get("description", "Unknown")
                alerts.append({
                    "type": "large_transaction",
                    "severity": "info",
                    "date": txn.get("date", ""),
                    "message": f"Large payment: ${amount:,.2f} to {desc} on {txn.get('date', '?')}",
                    "amount": round(amount, 2),
                    "description": desc,
                    "source": "bank",
                })

        return alerts

    # ── Helpers ────────────────────────────────────────────────

    def _sum_debits_by_category(
        self, txns: list[dict[str, Any]]
    ) -> dict[str, float]:
        """Sum debit amounts by category."""
        totals: dict[str, float] = {}
        for txn in txns:
            if txn.get("type") != "debit":
                continue
            cat = txn.get("category", "uncategorized")
            totals[cat] = totals.get(cat, 0) + abs(txn.get("amount", 0))
        return totals
