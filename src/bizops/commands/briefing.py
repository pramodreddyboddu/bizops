"""Daily owner briefing command."""

from __future__ import annotations

import typer
from rich.console import Console

from bizops.utils.config import load_config
from bizops.utils.display import (
    create_briefing_panel,
    get_spinner,
    print_warning,
)

console = Console()
app = typer.Typer(no_args_is_help=False)


@app.callback(invoke_without_command=True)
def briefing(
    date: str = typer.Option(
        None, "--date", "-d", help="Date (YYYY-MM-DD). Defaults to yesterday."
    ),
) -> None:
    """Daily owner briefing — everything you need to know in one view."""
    from bizops.parsers.briefing import BriefingEngine
    from bizops.utils.storage import save_briefing

    config = load_config()
    engine = BriefingEngine(config)

    with get_spinner() as spinner:
        spinner.add_task("Generating daily briefing...", total=None)
        data = engine.generate_briefing(date)

    # Save for MCP access
    save_briefing(config, data, data["briefing_date"])

    console.print(create_briefing_panel(data))

    # Summary line
    alerts = data.get("sections", {}).get("alerts", [])
    if alerts:
        high = sum(1 for a in alerts if a.get("severity") == "high")
        if high:
            print_warning(f"{high} high-priority alert(s) — see above.")
