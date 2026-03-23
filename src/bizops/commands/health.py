"""Business health score CLI command."""

from __future__ import annotations

import typer
from rich.console import Console

from bizops.utils.config import load_config
from bizops.utils.display import create_health_score_panel, get_spinner

console = Console()
app = typer.Typer(no_args_is_help=False)


@app.callback(invoke_without_command=True)
def health_score() -> None:
    """Your business health score — one number that tells you everything."""
    from bizops.parsers.health_score import HealthScoreEngine

    config = load_config()

    with get_spinner() as spinner:
        spinner.add_task("Calculating health score...", total=None)
        engine = HealthScoreEngine(config)
        data = engine.calculate_score()

    console.print(create_health_score_panel(data))
