"""Expense engine — categorize invoices and POS data into a P&L structure.

Takes segregated invoice data (from _export.segregate_invoices) and optional
Toast POS reports, assigns expense categories, and produces revenue/expense
summaries suitable for P&L reporting.
"""

from __future__ import annotations

from typing import Any

from bizops.utils.config import BizOpsConfig, CategoryKeywords, ExpenseCategory


class ExpenseEngine:
    """Categorize expenses and build P&L summaries.

    Works with the enriched invoice dicts produced by
    ``commands._export.segregate_invoices()`` — the "payment" bucket items
    are the expenses to categorize.
    """

    def __init__(self, config: BizOpsConfig):
        self.config = config
        self._keywords: CategoryKeywords = config.category_keywords

    # ──────────────────────────────────────────────────────────
    #  Single-invoice categorization
    # ──────────────────────────────────────────────────────────

    def categorize_invoice(self, invoice: dict[str, Any]) -> str:
        """Assign an expense category to a single invoice.

        Priority:
          1. Vendor config category (from config.vendors)
          2. Zelle recipient name matched against category keywords
          3. Keyword matching on vendor name / subject / body
          4. Fallback to "miscellaneous"
        """
        vendor = (invoice.get("vendor") or "").strip()

        # 1. Check vendor config — only accept if it's a valid ExpenseCategory
        category = self._match_vendor_config(vendor)
        valid_categories = {c.value for c in ExpenseCategory}
        if category and category in valid_categories:
            return category

        # 2. Check Zelle recipient against keywords
        subject = (invoice.get("subject") or "").lower()
        if "zelle" in subject:
            recipient = vendor.lower()
            cat = self._match_keywords(recipient)
            if cat:
                return cat

        # 3. Keyword matching on vendor + subject + body
        search_text = " ".join([
            vendor.lower(),
            subject,
            (invoice.get("body") or "").lower(),
        ])
        cat = self._match_keywords(search_text)
        if cat:
            return cat

        # 4. Fallback
        return ExpenseCategory.miscellaneous

    # ──────────────────────────────────────────────────────────
    #  Bulk categorization with P&L structure
    # ──────────────────────────────────────────────────────────

    def categorize_all(
        self,
        invoices: list[dict[str, Any]],
        toast_reports: list[dict[str, Any]] | None = None,
        start_date: str = "",
        end_date: str = "",
    ) -> dict[str, Any]:
        """Categorize all invoices and combine with POS revenue data.

        Args:
            invoices: Enriched invoice dicts (the "payment" bucket from
                      ``segregate_invoices``).
            toast_reports: Optional list of Toast POS daily summary dicts,
                           each containing keys like ``gross_sales``,
                           ``net_sales``, ``tax``, ``tips``, ``date``.
            start_date: Period start (YYYY-MM-DD).
            end_date: Period end (YYYY-MM-DD).

        Returns:
            A dict with period, revenue, expenses_by_category, totals,
            and daily_sales.
        """
        toast_reports = toast_reports or []

        # ── Revenue from Toast POS ──
        revenue = self._aggregate_revenue(toast_reports)

        # ── Categorize expenses ──
        expenses_by_category: dict[str, list[dict[str, Any]]] = {
            cat.value: [] for cat in ExpenseCategory
        }

        for inv in invoices:
            category = self.categorize_invoice(inv)
            categorized = {**inv, "expense_category": category}
            expenses_by_category[category].append(categorized)

        # ── Totals ──
        total_expenses = sum(
            inv.get("amount") or 0
            for cat_list in expenses_by_category.values()
            for inv in cat_list
        )
        total_revenue = revenue.get("net_sales", 0.0)

        # ── Daily sales breakdown ──
        daily_sales = self._build_daily_sales(toast_reports)

        return {
            "period": {"start": start_date, "end": end_date},
            "revenue": revenue,
            "expenses_by_category": expenses_by_category,
            "totals": {
                "total_revenue": round(total_revenue, 2),
                "total_expenses": round(total_expenses, 2),
                "net_profit": round(total_revenue - total_expenses, 2),
            },
            "daily_sales": daily_sales,
        }

    # ──────────────────────────────────────────────────────────
    #  P&L summary
    # ──────────────────────────────────────────────────────────

    def generate_pl_summary(
        self,
        categorized: dict[str, Any],
    ) -> dict[str, Any]:
        """Generate a simplified P&L dict from categorize_all() output.

        Returns:
            A dict with revenue line, category expense totals, and bottom line.
        """
        revenue = categorized.get("revenue", {})
        expenses = categorized.get("expenses_by_category", {})
        totals = categorized.get("totals", {})

        category_totals: dict[str, float] = {}
        for cat, items in expenses.items():
            cat_total = sum(inv.get("amount") or 0 for inv in items)
            if cat_total > 0:
                category_totals[cat] = round(cat_total, 2)

        return {
            "period": categorized.get("period", {}),
            "revenue": {
                "gross_sales": revenue.get("gross_sales", 0.0),
                "net_sales": revenue.get("net_sales", 0.0),
                "tax_collected": revenue.get("tax", 0.0),
                "tips": revenue.get("tips", 0.0),
            },
            "expenses": category_totals,
            "total_expenses": totals.get("total_expenses", 0.0),
            "net_profit": totals.get("net_profit", 0.0),
        }

    # ──────────────────────────────────────────────────────────
    #  Internal helpers
    # ──────────────────────────────────────────────────────────

    def _match_vendor_config(self, vendor_name: str) -> str | None:
        """Check if vendor matches a configured vendor's category."""
        if not vendor_name:
            return None
        vendor_lower = vendor_name.lower()
        for vc in self.config.vendors:
            if vc.name.lower() == vendor_lower:
                return vc.category
            if any(alias.lower() == vendor_lower for alias in vc.aliases):
                return vc.category
        return None

    def _match_keywords(self, text: str) -> str | None:
        """Match text against category keyword lists.

        Returns the first matching ExpenseCategory value, or None.
        """
        if not text:
            return None
        text_lower = text.lower()

        keyword_map = self._keywords.model_dump()
        for category_name, keywords in keyword_map.items():
            for kw in keywords:
                if kw.lower() in text_lower:
                    return category_name
        return None

    def _aggregate_revenue(
        self, toast_reports: list[dict[str, Any]]
    ) -> dict[str, float]:
        """Sum up revenue fields from Toast POS daily reports."""
        gross = sum(r.get("gross_sales", 0) for r in toast_reports)
        net = sum(r.get("net_sales", 0) for r in toast_reports)
        tax = sum(r.get("tax", 0) for r in toast_reports)
        tips = sum(r.get("tips", 0) for r in toast_reports)

        return {
            "gross_sales": round(gross, 2),
            "net_sales": round(net, 2),
            "tax": round(tax, 2),
            "tips": round(tips, 2),
        }

    def _build_daily_sales(
        self, toast_reports: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Build a sorted list of daily sales entries from Toast reports."""
        daily = []
        for r in toast_reports:
            daily.append({
                "date": r.get("date", ""),
                "gross": r.get("gross_sales", 0),
                "net": r.get("net_sales", 0),
            })
        return sorted(daily, key=lambda d: d.get("date", ""))
