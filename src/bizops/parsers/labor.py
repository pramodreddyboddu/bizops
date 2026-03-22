"""Labor cost tracking engine — calculate labor cost %, detect cash payments, trends.

Uses bank statement data (ADP payroll + cash/Zelle payments) and Toast POS
revenue to compute labor cost percentages, breakdowns, and alerts.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from bizops.utils.config import BizOpsConfig


class LaborEngine:
    """Calculate labor cost percentages, detect cash labor, and trend analysis."""

    def __init__(self, config: BizOpsConfig):
        self.config = config
        self.budget = config.labor_budget

    def calculate_labor_cost(
        self,
        bank_txns: list[dict[str, Any]],
        toast_data: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Calculate labor cost percentage from bank transactions and sales data.

        Args:
            bank_txns: Bank transactions (from bank statement parser).
            toast_data: Toast POS daily reports for revenue.

        Returns:
            Dict with total_labor, net_sales, labor_pct, status, and breakdown.
        """
        # Get all payroll-category transactions (ADP, Gusto, etc.)
        payroll_txns = [
            t for t in bank_txns
            if t.get("category") == "payroll" and t.get("type") == "debit"
        ]

        # Detect additional cash labor payments
        cash_labor = self.detect_cash_labor(bank_txns)
        cash_labor_txns = [item["txn"] for item in cash_labor]

        # Avoid double-counting: exclude txns already in payroll
        payroll_keys = {
            (t.get("date"), t.get("description"), t.get("amount"))
            for t in payroll_txns
        }
        unique_cash = [
            t for t in cash_labor_txns
            if (t.get("date"), t.get("description"), t.get("amount")) not in payroll_keys
        ]

        # Build breakdown
        adp_txns = [t for t in payroll_txns if "adp" in t.get("description", "").lower()]
        other_payroll = [t for t in payroll_txns if t not in adp_txns]

        adp_total = sum(abs(t.get("amount", 0)) for t in adp_txns)
        cash_total = sum(abs(t.get("amount", 0)) for t in unique_cash)
        other_total = sum(abs(t.get("amount", 0)) for t in other_payroll)

        total_labor = round(adp_total + cash_total + other_total, 2)

        # Get net sales from toast data
        net_sales = 0.0
        if toast_data:
            net_sales = sum(r.get("net_sales", 0) for r in toast_data)
        net_sales = round(net_sales, 2)

        # Calculate percentage
        labor_pct = (total_labor / net_sales * 100) if net_sales > 0 else 0.0
        labor_pct = round(labor_pct, 1)

        # Determine status
        status = "healthy"
        if labor_pct >= self.budget.alert_threshold_pct:
            status = "critical"
        elif labor_pct >= self.budget.target_labor_pct:
            status = "warning"

        return {
            "total_labor": total_labor,
            "net_sales": net_sales,
            "labor_pct": labor_pct,
            "status": status,
            "breakdown": {
                "adp": {"total": round(adp_total, 2), "count": len(adp_txns)},
                "cash_payments": {"total": round(cash_total, 2), "count": len(unique_cash)},
                "other": {"total": round(other_total, 2), "count": len(other_payroll)},
            },
            "target_pct": self.budget.target_labor_pct,
            "alert_threshold_pct": self.budget.alert_threshold_pct,
            "detected_cash_labor": cash_labor,
        }

    def detect_cash_labor(
        self, bank_txns: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Detect likely cash/Zelle payments to employees from bank transactions.

        Matches debits against employee names/aliases from config.
        Flags round-amount ATM withdrawals as potential cash labor.

        Returns:
            List of dicts with txn, match_reason, and matched_employee.
        """
        if not self.config.employees:
            return []

        flagged = []
        # Build lookup: lowercase alias → employee name
        alias_map: dict[str, str] = {}
        for emp in self.config.employees:
            if not emp.active:
                continue
            for alias in emp.aliases:
                alias_map[alias.lower()] = emp.name
            # Also match on employee name itself
            alias_map[emp.name.lower()] = emp.name

        for txn in bank_txns:
            if txn.get("type") != "debit":
                continue
            # Skip already-categorized payroll transactions
            if txn.get("category") == "payroll":
                continue

            desc = txn.get("description", "").lower()
            amount = abs(txn.get("amount", 0))

            # Check 1: Zelle/transfer description matches employee name/alias
            if any(keyword in desc for keyword in ("zelle", "venmo", "transfer")):
                for alias, emp_name in alias_map.items():
                    if alias in desc:
                        flagged.append({
                            "txn": txn,
                            "match_reason": "employee_alias",
                            "matched_employee": emp_name,
                        })
                        break

            # Check 2: Round-amount ATM/cash withdrawals ($100, $200, $500, etc.)
            elif any(keyword in desc for keyword in ("atm", "cash withdraw")):
                if amount >= 100 and amount % 100 == 0:
                    flagged.append({
                        "txn": txn,
                        "match_reason": "round_atm_withdrawal",
                        "matched_employee": "unknown",
                    })

        return flagged

    def get_labor_trend(self, months: int = 3) -> list[dict[str, Any]]:
        """Load bank and toast data for the last N months and compute labor trends.

        Returns:
            List of monthly snapshots with month, labor_pct, total_labor,
            net_sales, status, and trend direction.
        """
        from bizops.utils.storage import load_bank_transactions, load_toast_reports

        snapshots = []
        today = datetime.now()

        for i in range(months - 1, -1, -1):
            target = today.replace(day=1) - timedelta(days=i * 28)
            year_month = target.strftime("%Y-%m")
            start = f"{year_month}-01"
            if target.month == 12:
                end_dt = target.replace(year=target.year + 1, month=1, day=1) - timedelta(days=1)
            else:
                end_dt = target.replace(month=target.month + 1, day=1) - timedelta(days=1)
            end = end_dt.strftime("%Y-%m-%d")

            bank_txns = load_bank_transactions(self.config, start, end)
            toast = load_toast_reports(self.config, start, end)

            if bank_txns or toast:
                lc = self.calculate_labor_cost(bank_txns, toast)
                snapshots.append({
                    "month": year_month,
                    "labor_pct": lc["labor_pct"],
                    "total_labor": lc["total_labor"],
                    "net_sales": lc["net_sales"],
                    "status": lc["status"],
                })
            else:
                snapshots.append({
                    "month": year_month,
                    "labor_pct": 0.0,
                    "total_labor": 0.0,
                    "net_sales": 0.0,
                    "status": "no_data",
                })

        # Add trend direction
        for i, snap in enumerate(snapshots):
            if i == 0 or snap["labor_pct"] == 0:
                snap["trend"] = "flat"
            else:
                prev = snapshots[i - 1]["labor_pct"]
                if prev == 0:
                    snap["trend"] = "flat"
                elif snap["labor_pct"] > prev:
                    snap["trend"] = "up"
                elif snap["labor_pct"] < prev:
                    snap["trend"] = "down"
                else:
                    snap["trend"] = "flat"

        return snapshots

    def check_labor_alerts(
        self, labor_data: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Check current labor data against budget thresholds.

        Returns:
            List of alert dicts with type, severity, and message.
        """
        alerts = []
        pct = labor_data.get("labor_pct", 0)

        if pct >= self.budget.alert_threshold_pct:
            alerts.append({
                "type": "critical",
                "severity": "high",
                "message": f"Labor cost at {pct}% — above {self.budget.alert_threshold_pct}% threshold!",
                "source": "labor",
            })
        elif pct >= self.budget.target_labor_pct:
            alerts.append({
                "type": "warning",
                "severity": "medium",
                "message": f"Labor cost at {pct}% — above {self.budget.target_labor_pct}% target.",
                "source": "labor",
            })

        # Cash labor detection count
        cash_count = len(labor_data.get("detected_cash_labor", []))
        if cash_count > 0:
            alerts.append({
                "type": "info",
                "severity": "low",
                "message": f"{cash_count} potential cash labor payment(s) detected — review recommended.",
                "source": "labor",
            })

        return alerts
