"""Output formatters used by every command. Keep formatting decisions out of
command logic so the same payload can be rendered to the terminal, JSON, or
markdown for ticket pasting."""
from __future__ import annotations

import json
from dataclasses import is_dataclass, asdict
from enum import Enum
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from hologram_cli.triage.analyzer import Diagnosis, Hypothesis

_console = Console()


class Format(str, Enum):
    table = "table"
    json = "json"
    markdown = "markdown"


def render_diagnosis(diagnosis: Diagnosis, fmt: Format) -> None:
    if fmt is Format.json:
        _console.print_json(json.dumps(diagnosis.as_dict(), indent=2))
        return
    if fmt is Format.markdown:
        _console.print(_diagnosis_markdown(diagnosis), markup=False, highlight=False)
        return
    _render_diagnosis_table(diagnosis)


def render_reply(reply: str, fmt: Format) -> None:
    if fmt is Format.json:
        _console.print_json(json.dumps({"reply": reply}, indent=2))
        return
    if fmt is Format.markdown:
        _console.print(reply, markup=False, highlight=False)
        return
    _console.print(Panel(reply, title="Draft customer reply", border_style="cyan"))


def render_kv_table(title: str, rows: list[tuple[str, Any]], fmt: Format) -> None:
    if fmt is Format.json:
        _console.print_json(json.dumps({k: _coerce(v) for k, v in rows}, indent=2))
        return
    if fmt is Format.markdown:
        lines = [f"## {title}", ""]
        lines.extend(f"- **{k}:** {v}" for k, v in rows)
        _console.print("\n".join(lines), markup=False, highlight=False)
        return
    table = Table(title=title, show_header=False, header_style="bold")
    table.add_column("field", style="dim")
    table.add_column("value")
    for k, v in rows:
        table.add_row(str(k), str(v))
    _console.print(table)


def render_rows_table(title: str, columns: list[str], rows: list[list[Any]], fmt: Format) -> None:
    if fmt is Format.json:
        out = [dict(zip(columns, [_coerce(v) for v in row])) for row in rows]
        _console.print_json(json.dumps(out, indent=2))
        return
    if fmt is Format.markdown:
        lines = [f"## {title}", "", "| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
        for row in rows:
            lines.append("| " + " | ".join(str(v) for v in row) + " |")
        _console.print("\n".join(lines), markup=False, highlight=False)
        return
    table = Table(title=title, header_style="bold")
    for c in columns:
        table.add_column(c)
    for row in rows:
        table.add_row(*(str(v) for v in row))
    _console.print(table)


def print_message(msg: str) -> None:
    _console.print(msg)


def print_warning(msg: str) -> None:
    _console.print(f"[yellow]warning:[/yellow] {msg}")


def print_error(msg: str) -> None:
    _console.print(f"[red]error:[/red] {msg}")


# ---- internals ----------------------------------------------------------


def _coerce(v: Any) -> Any:
    if is_dataclass(v):
        return asdict(v)
    if isinstance(v, Enum):
        return v.value
    return v


def _render_diagnosis_table(diagnosis: Diagnosis) -> None:
    health_color = {"healthy": "green", "degraded": "yellow", "broken": "red"}.get(diagnosis.health, "white")
    header = Text()
    header.append(diagnosis.health.upper(), style=f"bold {health_color}")
    header.append("  ")
    header.append(diagnosis.summary)
    detected = []
    if diagnosis.vendor:
        detected.append(diagnosis.vendor)
    if diagnosis.module:
        detected.append(diagnosis.module)
    subtitle = " / ".join(detected) if detected else "vendor: unknown"
    _console.print(Panel(header, title="diagnosis", subtitle=subtitle, border_style=health_color))

    for i, h in enumerate(diagnosis.hypotheses, start=1):
        _render_hypothesis(h, i)


def _render_hypothesis(h: Hypothesis, index: int) -> None:
    conf_color = {"high": "red", "medium": "yellow", "low": "blue"}.get(h.confidence, "white")
    title = f"#{index}  {h.title}"
    body = Text()
    body.append("confidence: ", style="dim")
    body.append(h.confidence, style=f"bold {conf_color}")
    body.append(f"   rule: {h.rule_id}\n\n", style="dim")
    body.append(h.explanation + "\n")
    if h.evidence:
        body.append("\nevidence:\n", style="bold")
        for e in h.evidence:
            body.append(f"  • {e}\n")
    if h.next_actions:
        body.append("\nnext actions:\n", style="bold")
        for a in h.next_actions:
            body.append(f"  • {a}\n")
    _console.print(Panel(body, title=title, border_style=conf_color))


def _diagnosis_markdown(diagnosis: Diagnosis) -> str:
    lines = [
        f"# Diagnosis: {diagnosis.summary}",
        "",
        f"**Health:** {diagnosis.health}    **Vendor:** {diagnosis.vendor or 'unknown'}    **Module:** {diagnosis.module or 'unknown'}",
        "",
    ]
    for i, h in enumerate(diagnosis.hypotheses, start=1):
        lines.append(f"## #{i} — {h.title}")
        lines.append("")
        lines.append(f"_Confidence: {h.confidence}    Rule: `{h.rule_id}`_")
        lines.append("")
        lines.append(h.explanation)
        lines.append("")
        if h.evidence:
            lines.append("**Evidence**")
            lines.extend(f"- {e}" for e in h.evidence)
            lines.append("")
        if h.next_actions:
            lines.append("**Next actions**")
            lines.extend(f"- {a}" for a in h.next_actions)
            lines.append("")
    return "\n".join(lines)
