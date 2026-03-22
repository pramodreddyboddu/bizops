"""Configuration management for BizOps."""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

# ──────────────────────────────────────────────────────────────
#  Expense categories (Phase 2)
# ──────────────────────────────────────────────────────────────

class ExpenseCategory(StrEnum):
    """Expense categories for P&L classification."""

    food_supplies = "food_supplies"
    produce = "produce"
    meat = "meat"
    beverages = "beverages"
    cleaning = "cleaning"
    utilities = "utilities"
    rent = "rent"
    payroll = "payroll"
    pos_fees = "pos_fees"
    marketing = "marketing"
    insurance = "insurance"
    equipment = "equipment"
    miscellaneous = "miscellaneous"


class CategoryKeywords(BaseModel):
    """Keyword lists for automatic expense categorization.

    Each field maps to an ExpenseCategory and contains lowercase keywords
    matched against vendor names, email subjects, and body text.
    """

    food_supplies: list[str] = Field(
        default_factory=lambda: [
            "sysco", "us foods", "restaurant depot", "food service", "food supply",
        ]
    )
    produce: list[str] = Field(
        default_factory=lambda: ["produce", "fresh", "vegetable", "fruit", "om produce"]
    )
    meat: list[str] = Field(
        default_factory=lambda: ["meat", "halal", "yaman", "chicken", "beef", "lamb"]
    )
    beverages: list[str] = Field(
        default_factory=lambda: ["beverage", "drink", "soda", "juice", "water"]
    )
    cleaning: list[str] = Field(
        default_factory=lambda: ["cleaning", "janitorial", "sanitizer", "chemical"]
    )
    utilities: list[str] = Field(
        default_factory=lambda: [
            "electric", "gas", "water", "internet", "phone",
            "at&t", "gexa", "atmos", "utility",
        ]
    )
    rent: list[str] = Field(
        default_factory=lambda: ["rent", "lease", "kppsinvestments"]
    )
    payroll: list[str] = Field(
        default_factory=lambda: ["payroll", "wage", "salary", "gusto", "adp"]
    )
    pos_fees: list[str] = Field(
        default_factory=lambda: ["toast", "pos", "processing", "merchant fee"]
    )
    marketing: list[str] = Field(
        default_factory=lambda: ["advertising", "marketing", "signage", "sign", "flyer"]
    )
    insurance: list[str] = Field(
        default_factory=lambda: ["insurance", "policy", "premium"]
    )
    equipment: list[str] = Field(
        default_factory=lambda: ["equipment", "repair", "maintenance", "appliance"]
    )


# ──────────────────────────────────────────────────────────────


# Default paths (Windows-style for Pramod's setup, with cross-platform fallback)
DEFAULT_BASE_DIR = Path.home() / "Documents" / "BizOps"
DEFAULT_CONFIG_PATH = DEFAULT_BASE_DIR / "bizops_config.json"


class ProductItem(BaseModel):
    """A product in a vendor's catalog for ordering."""

    name: str
    sku: str = ""
    unit: str = "each"
    unit_cost: float = 0.0
    par_level: float = 0.0
    order_multiple: float = 1.0
    category: str = "food_supplies"
    active: bool = True


class OrderTemplate(BaseModel):
    """Recurring order template for a vendor."""

    vendor_name: str
    items: list[dict] = Field(default_factory=list)  # [{product_name, quantity}]
    frequency: str = "weekly"  # weekly, biweekly, monthly
    day_of_week: int = 1  # 0=Mon..6=Sun
    last_generated: str = ""
    enabled: bool = True


class FoodCostBudget(BaseModel):
    """Budget thresholds for food cost alerts."""

    target_food_cost_pct: float = 30.0
    alert_threshold_pct: float = 35.0
    category_budgets: dict[str, float] = Field(default_factory=dict)


class VendorConfig(BaseModel):
    """A known vendor for invoice matching."""

    name: str
    email_patterns: list[str] = Field(default_factory=list)
    category: str = "uncategorized"
    aliases: list[str] = Field(default_factory=list)
    products: list[ProductItem] = Field(default_factory=list)
    order_day: int = -1  # preferred order day (-1 = any)
    lead_time_days: int = 1

    def matches_email(self, sender: str) -> bool:
        """Check if an email sender matches this vendor."""
        sender_lower = sender.lower()
        return any(pattern.lower() in sender_lower for pattern in self.email_patterns)


class BizOpsConfig(BaseSettings):
    """Main configuration for BizOps CLI."""

    # Paths
    base_dir: Path = DEFAULT_BASE_DIR
    output_dir: Path = DEFAULT_BASE_DIR / "output"
    gmail_credentials_path: Path = DEFAULT_BASE_DIR / "credentials.json"
    gmail_token_path: Path = DEFAULT_BASE_DIR / "token.json"

    # Gmail settings
    gmail_label: str = "INBOX"
    gmail_max_results: int = 100

    # Invoice processing
    dedup_enabled: bool = True
    dedup_window_days: int = 7

    # Vendor list
    vendors: list[VendorConfig] = Field(default_factory=list)

    # Expense categorization (Phase 2)
    category_keywords: CategoryKeywords = Field(default_factory=CategoryKeywords)

    # Ordering & food cost
    order_templates: list[OrderTemplate] = Field(default_factory=list)
    food_cost_budget: FoodCostBudget = Field(default_factory=FoodCostBudget)

    # Excel output
    excel_template: str = "default"

    model_config = {"env_prefix": "BIZOPS_"}

    def ensure_dirs(self) -> None:
        """Create necessary directories if they don't exist."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)


def load_config(config_path: Path | None = None) -> BizOpsConfig:
    """Load config from JSON file, falling back to defaults."""
    path = config_path or DEFAULT_CONFIG_PATH

    if path.exists():
        raw = json.loads(path.read_text())
        return BizOpsConfig(**raw)

    return BizOpsConfig()


def save_config(config: BizOpsConfig, config_path: Path | None = None) -> None:
    """Save config to JSON file."""
    path = config_path or DEFAULT_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    data = config.model_dump(mode="json")
    # Convert Path objects to strings for JSON
    for key, value in data.items():
        if isinstance(value, Path):
            data[key] = str(value)

    path.write_text(json.dumps(data, indent=2, default=str))


# Pre-configured vendors for Desi Delight (example — users add their own)
DEFAULT_VENDORS = [
    VendorConfig(
        name="Sysco",
        email_patterns=["sysco.com", "sysco"],
        category="food_supplies",
    ),
    VendorConfig(
        name="Restaurant Depot",
        email_patterns=["restaurantdepot", "jetro"],
        category="food_supplies",
    ),
    VendorConfig(
        name="Toast POS",
        email_patterns=["toasttab.com", "toast"],
        category="pos_reports",
    ),
]
