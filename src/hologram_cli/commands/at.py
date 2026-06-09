"""`hgm at ...` — AT command log analysis."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer

from hologram_cli.output import Format, print_error, print_message, render_diagnosis, render_reply
from hologram_cli.triage import analyze, draft_reply, parse
from hologram_cli.triage import at_reference

app = typer.Typer(help="Parse and diagnose modem AT command logs.", no_args_is_help=True)


@app.command("parse")
def at_parse(
    path: Optional[Path] = typer.Argument(None, help="Path to an AT log file. Use '-' to read from stdin."),
    output: Format = typer.Option(Format.table, "--output", "-o", help="Output format."),
    reply: bool = typer.Option(False, "--reply", help="Also draft a customer-facing reply."),
    sender_name: str = typer.Option("[Your name]", "--sender", help="Name to sign the customer reply with."),
) -> None:
    """Diagnose a captured AT command log.

    Reads a log file (or stdin), parses the modem exchanges, runs the diagnosis
    rules, and prints the top hypotheses with evidence and recommended actions.

    Examples:

      hgm at parse fixtures/at_logs/02_registration_denied_creg03_ublox.log

      cat session.log | hgm at parse - --reply

      hgm at parse mylog.log -o markdown   # paste-ready output for tickets
    """
    text = _read_input(path)
    log = parse(text)
    diagnosis = analyze(log)
    render_diagnosis(diagnosis, output)
    if reply:
        render_reply(draft_reply(diagnosis, sender_name=sender_name), output)


@app.command("explain")
def at_explain(rule_id: str = typer.Argument(..., help="Rule ID to look up.")) -> None:
    """Explain what a specific diagnosis rule looks for and why it fires."""
    from hologram_cli.triage.analyzer import _RULES

    sample_inputs: dict[str, str] = {}  # placeholder for future per-rule docs
    for rule in _RULES:
        if rule.__name__.endswith(rule_id) or rule_id in rule.__name__:
            doc = (rule.__doc__ or "").strip()
            typer.echo(f"rule: {rule.__name__}\n")
            typer.echo(doc or "(no docstring)")
            return
    typer.echo(f"No rule matching '{rule_id}'. Available rules:")
    for rule in _RULES:
        typer.echo(f"  - {rule.__name__}")
    raise typer.Exit(code=1)


@app.command("lookup")
def at_lookup(
    name: Optional[str] = typer.Argument(None, help="AT command name (e.g. AT+QIOPEN, +CGPADDR, CEREG)."),
    decode: Optional[str] = typer.Option(None, "--decode", help="Decode a single response/URC line (e.g. '+CGPADDR: 1,\"100.66.18.214\"')."),
    search: Optional[str] = typer.Option(None, "--search", help="Search commands by name, purpose, or syntax keyword."),
    list_all: bool = typer.Option(False, "--list", help="List all known commands grouped by vendor."),
    vendor: Optional[str] = typer.Option(None, "--vendor", help="Filter --list to one vendor (3gpp, quectel, ublox, simcom, telit, sierra, nordic)."),
) -> None:
    """Look up AT commands and decode response lines.

    Examples:

      hgm at lookup AT+QIOPEN              # show command reference
      hgm at lookup CGPADDR                # leading "AT+" optional
      hgm at lookup --decode '+CEREG: 0,3' # explain what a response means
      hgm at lookup --decode '+CGPADDR: 1,"100.66.18.214"'
      hgm at lookup --search ping          # find ping-related commands
      hgm at lookup --list --vendor quectel
    """
    chosen = sum(x is not None and x is not False for x in (name, decode, search, list_all if list_all else None))
    if chosen == 0:
        print_error("specify a command name, --decode, --search, or --list")
        raise typer.Exit(code=2)

    if decode is not None:
        result = at_reference.decode_response(decode)
        if result is None:
            print_error(f"no decoder registered for: {decode!r}")
            print_message("Available decoders: " + ", ".join(at_reference._DECODERS.keys()))
            raise typer.Exit(code=1)
        print_message(result)
        return

    if search is not None:
        hits = at_reference.search(search)
        if not hits:
            print_message(f"no commands match {search!r}")
            return
        print_message(f"{len(hits)} command(s) match {search!r}:\n")
        for c in hits:
            print_message(f"  AT{c.name}  [{c.vendor}]  {c.purpose}")
        return

    if list_all:
        cmds = at_reference.list_commands(vendor=vendor)
        current_vendor = None
        for c in cmds:
            if c.vendor != current_vendor:
                print_message(f"\n[{c.vendor}]")
                current_vendor = c.vendor
            print_message(f"  AT{c.name:14s}  {c.purpose}")
        return

    if name is not None:
        cmd = at_reference.lookup(name)
        if cmd is None:
            print_error(f"command not found: {name}")
            print_message(f"Try `hgm at lookup --search {name}` for partial matches.")
            raise typer.Exit(code=1)
        _render_command(cmd)


def _render_command(c) -> None:
    print_message(f"[bold]AT{c.name}[/bold]   [dim]({c.vendor})[/dim]\n")
    print_message(c.purpose + "\n")
    if c.syntax:
        print_message("[bold]Syntax[/bold]")
        for s in c.syntax:
            print_message(f"  {s}")
        print_message("")
    if c.parameters:
        print_message("[bold]Parameters[/bold]")
        for k, v in c.parameters.items():
            print_message(f"  {k}: {v}")
        print_message("")
    if c.response_format:
        print_message(f"[bold]Response[/bold]\n  {c.response_format}\n")
    if c.common_errors:
        print_message("[bold]Common errors[/bold]")
        for k, v in c.common_errors.items():
            print_message(f"  {k}: {v}")
        print_message("")
    if c.example:
        print_message("[bold]Example[/bold]")
        for line in c.example.split("\\n"):
            print_message(f"  {line}")
        print_message("")
    if c.docs_url:
        print_message(f"[dim]Docs: {c.docs_url}[/dim]")


def _read_input(path: Optional[Path]) -> str:
    if path is None or str(path) == "-":
        return sys.stdin.read()
    if not path.exists():
        typer.echo(f"error: {path} not found", err=True)
        raise typer.Exit(code=2)
    return path.read_text()
