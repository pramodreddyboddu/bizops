# CLAUDE.md — Project Context for Claude Code

## What is BizOps?

BizOps is a Python CLI tool for small business operations automation. It pulls invoices from Gmail, extracts amounts/vendors/dates, deduplicates them, categorizes by vendor, and exports to formatted Excel workbooks.

## Tech Stack

- **Python 3.11+** with **Typer** (CLI framework) + **Rich** (terminal output)
- **Gmail API** via google-api-python-client for email access
- **openpyxl** for Excel workbook generation
- **Pydantic Settings** for config management
- **pytest** for testing

## Project Layout

```
src/bizops/
├── cli.py           — Main Typer app, command registration
├── mcp_server.py    — MCP server exposing business data to AI tools
├── commands/        — CLI command groups
│   ├── invoices.py  — Invoice pull, list, export commands
│   ├── expenses.py  — Expense tracking, reporting, summary
│   ├── ask.py       — AI-powered questions & insights (Claude API)
│   ├── config.py    — Configuration management
│   └── _export.py   — Multi-sheet Excel export with transaction segregation
├── connectors/      — External service connectors
│   ├── gmail.py     — Gmail API OAuth2 connector
│   └── anthropic_client.py — Claude API streaming client
├── parsers/         — Data extraction
│   ├── invoice.py   — Invoice email parser
│   ├── toast.py     — Toast POS daily summary parser
│   └── expenses.py  — Expense categorization engine
└── utils/           — Config, display helpers, local storage
```

## Key Design Decisions

- CLI entry point: `bizops` → `src/bizops/cli.py:app`
- Config stored as JSON at `~/Documents/BizOps/bizops_config.json`
- Processed invoices stored as JSON at `output/data/invoices_YYYY-MM.json`
- Gmail uses OAuth2 with read-only scope
- Vendor matching is email-pattern based (configured per vendor)
- Dedup uses MD5 hash of vendor+amount+date
- Transaction segregation: payment (money OUT), deposit (money IN), order (informational), other (spam/noise — dropped)
- DoorDash "Payment to" = gross sales summary (order), "Your DoorDash payment" = actual bank deposit (deposit)
- Om Produce "received payment from Desi Delight" = money OUT (payment)

## Build Commands

```bash
pip install -e ".[dev]"    # Install in dev mode
pytest                      # Run tests
pytest --cov=bizops         # Run with coverage
ruff check src/             # Lint
mypy src/bizops/            # Type check
```

## Current Status

- Phase 1: Invoice processing (COMPLETE)
- Phase 2: Expense tracking + Toast POS (COMPLETE)
- Phase 3: AI agent layer + MCP (COMPLETE)
- Phase 4: CI/CD + packaging (COMPLETE)

## Conventions

- All CLI output goes through `utils/display.py` helpers for consistency
- Vendor configs use Pydantic models with email pattern matching
- Date ranges resolved via `_resolve_date_range()` in invoices.py
- Excel exports use green header theme (#2F5233) matching Desi Delight branding

## Architecture Rules for All New Code

- Every new parser goes in src/bizops/parsers/ and follows the InvoiceParser pattern (class with config, parse method, extract helpers)
- Every new command group goes in src/bizops/commands/ as a Typer sub-app, registered in cli.py
- All display output uses helpers from utils/display.py — never print() directly
- All data storage uses utils/storage.py patterns — JSON files organized by month
- Config additions go in utils/config.py as Pydantic models
- Tests go in tests/ matching the module name (test_toast_parser.py for parsers/toast.py)
- Excel exports use the green header theme (#2F5233) and follow _export.py patterns
- Run pytest after every file change. Run ruff check src/ before committing.
