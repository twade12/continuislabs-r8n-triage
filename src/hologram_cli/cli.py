"""Top-level Typer app. Sub-apps are registered from `commands/`."""
from __future__ import annotations

import typer

from hologram_cli import __version__
from hologram_cli.commands import at as at_cmd
from hologram_cli.commands import sim as sim_cmd

app = typer.Typer(
    name="hgm",
    help=(
        "hologram-cli — an SE-friendly wrapper around the Hologram REST API "
        "plus offline triage tooling for AT command logs.\n\n"
        "Set HOLOGRAM_API_KEY to use live API commands. Without it, network commands "
        "default to mock mode for development and testing."
    ),
    no_args_is_help=True,
)

app.add_typer(at_cmd.app, name="at", help="Analyze AT command logs.")
app.add_typer(sim_cmd.app, name="sim", help="Inspect and triage individual SIMs.")


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", help="Print version and exit."),
) -> None:
    if version:
        typer.echo(f"hologram-cli {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


if __name__ == "__main__":
    app()
