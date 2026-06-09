"""`hgm sim ...` — single-SIM inspection and triage commands."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

import typer

from hologram_cli.client import HologramAPIError, HologramClient
from hologram_cli.config import load_profile
from hologram_cli.output import Format, print_error, print_warning, render_kv_table, render_rows_table
from hologram_cli.triage.oracle import explain_state

app = typer.Typer(help="Inspect and triage individual SIMs.", no_args_is_help=True)


def _get_client(profile_name: Optional[str], mock: bool) -> HologramClient:
    profile = load_profile(profile_name)
    if not profile.has_credentials and not mock:
        print_warning("no API credentials configured — falling back to mock mode. Set HOLOGRAM_API_KEY for live data.")
        mock = True
    return HologramClient(profile=profile, mock=mock)


@app.command("show")
def sim_show(
    identifier: str = typer.Argument(..., help="ICCID, IMEI, device ID, or SIM name."),
    output: Format = typer.Option(Format.table, "--output", "-o"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Named profile from ~/.hologram/config.toml."),
    mock: bool = typer.Option(False, "--mock", help="Force mock mode (no API calls)."),
) -> None:
    """One-shot triage view for a single SIM.

    Resolves the identifier (ICCID / IMEI / device ID / name), fetches the SIM
    record, and prints the data points an SE needs to triage a single-SIM ticket:
    state, plan, last session, RAT, country, signal, IMEI, tags, and any state
    quirks.
    """
    client = _get_client(profile, mock)
    try:
        sim = client.get_sim(identifier)
    except HologramAPIError as e:
        print_error(str(e))
        raise typer.Exit(code=1)

    last = sim.get("last_session") or {}
    plan = sim.get("plan") or {}
    period = sim.get("current_period") or {}

    rows: list[tuple[str, object]] = [
        ("ICCID", sim.get("iccid")),
        ("Name", sim.get("name") or "—"),
        ("State", sim.get("state")),
        ("Status", sim.get("status")),
        ("Tags", ", ".join(sim.get("tags") or []) or "—"),
        ("Device ID", sim.get("deviceid") or "—"),
        ("Link ID", sim.get("linkid") or "—"),
        ("IMEI", sim.get("imei") or "—"),
        ("Modem", sim.get("modem") or "—"),
        ("Plan", plan.get("name") or "—"),
        ("Plan limit (MB)", plan.get("limit_mb") if plan else "—"),
        ("Used this period (MB)", period.get("used_mb") if period else "—"),
        ("Last session", _fmt_session(last) if last else "no recorded sessions"),
    ]
    profiles = sim.get("euicc_profiles")
    if profiles:
        rows.append(("eUICC profiles", _fmt_profiles(profiles)))

    render_kv_table(f"SIM {sim.get('iccid')}", rows, output)


@app.command("sessions")
def sim_sessions(
    identifier: str = typer.Argument(..., help="ICCID, IMEI, device ID, or SIM name."),
    output: Format = typer.Option(Format.table, "--output", "-o"),
    profile: Optional[str] = typer.Option(None, "--profile"),
    mock: bool = typer.Option(False, "--mock"),
) -> None:
    """List recent connectivity sessions for a SIM.

    In mock mode, returns the single most-recent session from fixture data.
    Live mode pulls from /usage/data and groups into sessions.
    """
    client = _get_client(profile, mock)
    try:
        sim = client.get_sim(identifier)
    except HologramAPIError as e:
        print_error(str(e))
        raise typer.Exit(code=1)

    last = sim.get("last_session")
    if not last:
        print_warning(f"no sessions on record for {sim.get('iccid')}")
        return

    rows = [[
        _fmt_ts(last["ts"]),
        last.get("country") or "—",
        last.get("operator") or "—",
        last.get("rat") or "—",
        last.get("rsrp") or "—",
        last.get("bytes") or 0,
    ]]
    render_rows_table(
        f"Recent sessions for {sim.get('iccid')}",
        ["timestamp (UTC)", "country", "operator", "RAT", "RSRP (dBm)", "bytes"],
        rows,
        output,
    )


@app.command("trace")
def sim_trace(
    identifier: str = typer.Argument(...),
    output: Format = typer.Option(Format.table, "--output", "-o"),
    profile: Optional[str] = typer.Option(None, "--profile"),
    mock: bool = typer.Option(False, "--mock"),
) -> None:
    """Walk the activation/state history of a SIM.

    Useful when diagnosing "why hasn't this SIM come online" — shows the state
    transitions in order, so you can see whether the SIM has cleared each
    expected step (INACTIVE → LIVE-PENDING → LIVE) and how long each took.
    """
    client = _get_client(profile, mock)
    try:
        sim = client.get_sim(identifier)
    except HologramAPIError as e:
        print_error(str(e))
        raise typer.Exit(code=1)

    history = sim.get("state_history") or []
    if not history:
        print_warning("no state history available for this SIM")
        return

    history = sorted(history, key=lambda e: e["ts"])
    rows = []
    for i, entry in enumerate(history):
        delta = ""
        if i > 0:
            seconds = entry["ts"] - history[i - 1]["ts"]
            delta = _fmt_duration(seconds)
        rows.append([_fmt_ts(entry["ts"]), entry["state"], delta or "—"])
    render_rows_table(
        f"State transitions for {sim.get('iccid')}",
        ["timestamp (UTC)", "state", "delta from previous"],
        rows,
        output,
    )


@app.command("why-paused")
def sim_why_paused(
    identifier: str = typer.Argument(...),
    output: Format = typer.Option(Format.table, "--output", "-o"),
    profile: Optional[str] = typer.Option(None, "--profile"),
    mock: bool = typer.Option(False, "--mock"),
) -> None:
    """Explain WHY a SIM is in its current state.

    Works for any state, not just paused ones — for PAUSED-SYS the oracle tries
    to identify the trigger (data cap, balance), for LIVE-PENDING it explains
    propagation timing, for DEAD it explains permanence, etc.
    """
    client = _get_client(profile, mock)
    try:
        sim = client.get_sim(identifier)
    except HologramAPIError as e:
        print_error(str(e))
        raise typer.Exit(code=1)

    explanation = explain_state(sim)
    rows: list[tuple[str, object]] = [
        ("State", explanation.state),
        ("Severity", explanation.severity),
        ("Summary", explanation.summary),
        ("Explanation", explanation.explanation),
    ]
    if explanation.next_actions:
        rows.append(("Next actions", "\n".join(f"• {a}" for a in explanation.next_actions)))
    render_kv_table(f"State explanation for {sim.get('iccid')}", rows, output)


# ---- formatting helpers -------------------------------------------------


def _fmt_ts(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _fmt_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    if seconds < 86400:
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m"
    return f"{seconds // 86400}d {(seconds % 86400) // 3600}h"


def _fmt_session(s: dict) -> str:
    age = int(time.time() - s["ts"])
    return (
        f"{_fmt_ts(s['ts'])} ({_fmt_duration(age)} ago) — "
        f"{s.get('operator', '?')} {s.get('rat', '?')} in {s.get('country', '?')}, "
        f"RSRP {s.get('rsrp', '?')} dBm, {s.get('bytes', 0)} bytes"
    )


def _fmt_profiles(profiles: list[dict]) -> str:
    return "\n".join(
        f"  [{'active' if p['active'] else 'inactive'}] #{p['index']} {p.get('carrier', '?')} ({p['iccid']})"
        for p in profiles
    )
