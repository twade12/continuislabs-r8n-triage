# hologram-cli

A Solutions-Engineer-friendly Python CLI wrapper around the [Hologram REST API](https://docs.hologram.io/api/v1) plus offline triage tooling for AT command logs.

This is a personal prep project for the Hologram SE I role — it demonstrates the kind of internal tooling that makes day-to-day SE work faster: SIM triage in one command, deterministic AT-log diagnosis with draft customer replies, and a state oracle that explains *why* a SIM is in its current state.

## What's in here

```
.
├── src/hologram_cli/        # Python package
│   ├── cli.py               # Typer app — entry point for `hgm`
│   ├── client.py            # REST API client with HTTP Basic auth + mock mode
│   ├── config.py            # ~/.hologram/config.toml profile management
│   ├── output.py            # table / json / markdown formatters
│   ├── mock_data.py         # fixture SIMs in every interesting state
│   ├── commands/
│   │   ├── at.py            # `hgm at parse|lookup|explain`
│   │   └── sim.py           # `hgm sim show|sessions|trace|why-paused`
│   └── triage/
│       ├── parser.py        # AT log → structured exchanges
│       ├── signals.py       # vendor-agnostic RSRP / RAT-lock helpers
│       ├── analyzer.py      # 13 diagnosis rules covering common fault modes
│       ├── at_reference.py  # AT command catalogue + response decoders
│       ├── reply.py         # customer-reply drafter
│       └── oracle.py        # SIM-state explanation engine
├── fixtures/at_logs/        # 12 synthetic AT logs (one per fault mode)
├── tests/                   # pytest suite — 29 tests, parser + analyzer end-to-end
├── docs/hologram-cli.md     # full CLI reference
└── pyproject.toml
```

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run an AT log through the analyzer:
hgm at parse fixtures/at_logs/02_registration_denied_creg03_ublox.log --reply

# Look up an AT command or decode a captured response line:
hgm at lookup AT+QIOPEN
hgm at lookup --decode '+CGPADDR: 1,"100.66.18.214"'

# Inspect a mock SIM (no API key required):
hgm sim show 8938100000123450030 --mock
hgm sim why-paused 8938100000123450030 --mock

# Run the test suite (89 tests):
pytest
```

## Design notes

**Triage brain is fully offline.** The AT-log analyzer never touches the network. It works on raw modem captures piped or passed in, and ships with 12 fixture logs covering the most common SE-encountered fault modes (registration denial, APN mismatch, marginal signal, band lock, PSM, eUICC fallback, etc.). Each fixture has an expected diagnosis the test suite enforces.

**Mock mode for everything else.** Network commands fall back to mock fixtures when no API key is configured. This means the CLI is fully usable for development and demos without an API account.

**Output formats are first-class.** Every command supports `--output table|json|markdown`. The markdown form is meant to be pasted directly into tickets or Slack threads; the table form is for live triage; JSON is for piping to other tools.

**Conductor-aware.** The analyzer includes a rule for the eUICC profile-fallback failure mode that Hologram's new [Conductor](https://www.globenewswire.com/news-release/2026/04/22/3279317/0/en/Hologram-launches-Conductor-a-SIM-orchestration-tool-for-IoT-teams-managing-fleets-at-scale.html) product is built to solve. The diagnosis output references Conductor APIs and policy-based failover as the long-term fix.

## Documentation

- [docs/hologram-cli.md](docs/hologram-cli.md) — complete CLI reference, every command and option
- [fixtures/at_logs/](fixtures/at_logs/) — synthetic AT logs, each with a header explaining the scenario, expected diagnosis, and customer-facing guidance

## Status

This is a working v0.1 — installable, tested, and demoable end-to-end. Subsequent waves planned (per the original proposal):

- **Wave 3:** "Codex" knowledge-base layer that captures resolved-ticket patterns (modem × carrier × country × firmware) for compounding triage value over time.
- **Wave 4:** MCP server exposing CLI operations as agent tools, plus a Triage Co-Pilot that drafts replies but never auto-sends.
