# 🏪 BizOps — Agentic CLI for Small Business Operations

**Stop drowning in invoices, receipts, and spreadsheets.** BizOps is a command-line tool that automates the operational busywork of running a small business — pulling invoices from Gmail, categorizing expenses, generating P&L reports, and answering natural language questions about your finances with AI.

Built by a small business owner who got tired of manual data entry.

---

## Quick Start

```bash
# Install
pip install bizops

# With AI features (Claude API + MCP)
pip install "bizops[agent]"

# First-time setup
bizops config setup --credentials ~/Downloads/credentials.json --defaults

# Pull this week's invoices from Gmail
bizops invoices pull --period week

# Track & categorize expenses
bizops expenses track --period month

# Generate P&L report
bizops expenses report --period month

# Ask AI about your business
export ANTHROPIC_API_KEY='sk-ant-...'
bizops ask "what did I spend on produce this month?"
```

---

## What It Does

### Phase 1 — Invoice Processing
- **Gmail integration** — Connects to your business Gmail via OAuth2 (read-only)
- **Smart extraction** — Pulls amounts, dates, invoice numbers from email bodies
- **Transaction segregation** — Classifies emails as Payments OUT, Deposits IN, or Orders
- **Vendor matching** — Auto-categorizes invoices by sender patterns
- **Deduplication** — MD5 hash + subject/date/amount dedup prevents double-counting
- **Excel export** — Multi-sheet workbooks (Summary, Payments OUT, Deposits IN, Orders) with branded formatting

### Phase 2 — Expense Tracking & P&L
- **Toast POS parsing** — Extracts daily sales, tax, tips, refunds from Toast daily summary emails
- **13 expense categories** — Food supplies, produce, meat, utilities, rent, payroll, and more
- **3-tier categorization** — Vendor config → keyword matching → fallback to miscellaneous
- **P&L workbooks** — 4-tab Excel reports (Sales Summary, Expenses, P&L, Vendor Summary)
- **Terminal dashboard** — Rich panels showing revenue, expenses, and net profit

### Phase 3 — AI Agent Layer
- **Natural language queries** — `bizops ask "which vendor costs the most?"`
- **AI insights** — Anomaly detection, spending trends, cost-saving opportunities
- **MCP server** — 7 tools exposing business data to Claude Desktop and other AI assistants
- **Streaming responses** — Real-time Rich Markdown output from Claude API

---

## Commands

### Invoices

```bash
# Pull invoices from Gmail
bizops invoices pull --period week
bizops invoices pull --period month --vendor "sysco"

# List processed invoices
bizops invoices list --status unpaid

# Export to Excel (multi-sheet: Summary, Payments OUT, Deposits IN, Orders)
bizops invoices export --period month
bizops invoices export --output ./march_invoices.xlsx
```

### Expenses

```bash
# Track and categorize expenses with P&L summary
bizops expenses track --period month
bizops expenses track --source toast --period week

# Generate P&L Excel workbook
bizops expenses report --period month
bizops expenses report --output ./march_pl.xlsx

# Quick terminal P&L summary
bizops expenses summary --period month
```

### AI (requires `ANTHROPIC_API_KEY`)

```bash
# Ask anything about your business data
bizops ask "what did I spend on produce this month?"
bizops ask "which vendor costs the most?"
bizops ask "am I spending more on utilities than last quarter?"

# Get automated insights
bizops ask insights --period month
bizops ask insights --period quarter --category produce
```

### Configuration

```bash
bizops config setup --credentials ~/creds.json --defaults
bizops config vendors                       # List configured vendors
bizops config add-vendor "Roma Foods" --email roma-foods.com --category produce
bizops config show                          # Show current config
bizops status                               # Connection & data status
```

---

## MCP Server

BizOps includes an MCP (Model Context Protocol) server that exposes your business data to AI tools like Claude Desktop.

### Available Tools

| Tool | Description |
|------|-------------|
| `get_invoices` | Get invoices filtered by period & vendor |
| `get_expenses` | Categorized expense data & P&L |
| `get_toast_sales` | Daily POS sales breakdown |
| `get_vendor_summary` | Vendor spend rankings |
| `get_pl_summary` | Simplified profit & loss view |
| `list_expense_categories` | Categories + keyword triggers |
| `list_vendors` | Configured vendor details |

### Setup

Add to your Claude Desktop config (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "bizops": {
      "command": "python",
      "args": ["-m", "bizops.mcp_server"],
      "env": {
        "PYTHONPATH": "/path/to/bizops/src"
      }
    }
  }
}
```

Or run standalone:
```bash
python -m bizops.mcp_server
```

---

## Installation

### Prerequisites
- Python 3.11+
- A Gmail account with Google Cloud API credentials ([setup guide](docs/gmail-setup.md))

### From PyPI
```bash
pip install bizops

# With AI features
pip install "bizops[agent]"
```

### From Source
```bash
git clone https://github.com/pramod/bizops.git
cd bizops
pip install -e ".[dev,agent]"
```

---

## Configuration

BizOps stores config at `~/Documents/BizOps/bizops_config.json`.

### Environment Variables

```bash
export BIZOPS_BASE_DIR=/path/to/bizops
export BIZOPS_OUTPUT_DIR=/path/to/output
export BIZOPS_GMAIL_LABEL=INBOX
export ANTHROPIC_API_KEY=sk-ant-...    # For AI features
```

### Expense Categories

13 built-in categories with configurable keyword triggers:

| Category | Example Keywords |
|----------|-----------------|
| Food Supplies | sysco, us foods, restaurant depot |
| Produce | produce, vegetables, fruits |
| Meat | halal, meat, chicken, lamb |
| Beverages | coca-cola, pepsi, drinks |
| Utilities | electric, gas, water, gexa, atmos |
| Rent | rent, lease, property |
| Payroll | payroll, wages, salary |
| POS Fees | toast, square, stripe |
| And more... | cleaning, marketing, insurance, equipment |

---

## Project Structure

```
bizops/
├── src/bizops/
│   ├── cli.py                  # Main Typer app + entry point
│   ├── mcp_server.py           # MCP server (7 tools, 2 resources)
│   ├── commands/
│   │   ├── invoices.py         # Invoice pull/list/export
│   │   ├── expenses.py         # Expense tracking & P&L reporting
│   │   ├── ask.py              # AI questions & insights (Claude API)
│   │   ├── config.py           # Configuration management
│   │   └── _export.py          # Excel export engine
│   ├── connectors/
│   │   ├── gmail.py            # Gmail API OAuth2 connector
│   │   └── anthropic_client.py # Claude API streaming client
│   ├── parsers/
│   │   ├── invoice.py          # Invoice email parser
│   │   ├── toast.py            # Toast POS daily summary parser
│   │   └── expenses.py         # Expense categorization engine
│   └── utils/
│       ├── config.py           # Pydantic settings + vendor models
│       ├── display.py          # Rich output helpers
│       └── storage.py          # Local JSON storage
├── tests/                      # 107 tests
│   ├── test_invoice_parser.py  # 17 tests
│   ├── test_toast_parser.py    # 38 tests
│   ├── test_expense_engine.py  # 22 tests
│   ├── test_ask.py             # 11 tests
│   └── test_mcp_server.py      # 19 tests
├── .github/workflows/
│   ├── ci.yml                  # Lint + test on push/PR
│   └── publish.yml             # PyPI publish on release
├── pyproject.toml
└── README.md
```

---

## Tech Stack

| Component | Choice | Why |
|-----------|--------|-----|
| CLI Framework | [Typer](https://typer.tiangolo.com/) | Type-hint driven, Rich integration |
| Terminal UI | [Rich](https://rich.readthedocs.io/) | Tables, panels, streaming markdown |
| Email | Gmail API (OAuth2) | Direct access, read-only scope |
| Excel | openpyxl | Full formatting control, multi-sheet |
| Config | Pydantic Settings | Validation, env vars, type safety |
| AI | Anthropic SDK | Claude for NL queries + insights |
| MCP | MCP SDK | Expose data to AI assistants |
| Testing | pytest | 107 tests, mocked API calls |

---

## Development

```bash
# Install with all dependencies
pip install -e ".[dev,agent]"

# Run tests
pytest

# Run with coverage
pytest --cov=bizops --cov-report=term-missing

# Lint
ruff check src/

# Type check
mypy src/bizops/
```

---

## Who Is This For?

- **Small restaurant owners** tired of manually processing vendor invoices
- **Ethnic grocery stores** juggling multiple suppliers with email-based billing
- **Small retailers** who want automated expense tracking without enterprise software
- **Any small business** where the owner is also the bookkeeper

---

## License

MIT

---

## Author

Built by [Pramod](https://github.com/pramod) — owner of Desi Delight Marketplace, Princeton TX.

Born from real frustration with manual invoice processing. If you run a small business and spend hours on data entry, this tool is for you.
