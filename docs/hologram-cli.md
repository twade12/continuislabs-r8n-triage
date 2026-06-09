# hologram-cli reference

Complete command reference for `hgm`, the Solutions Engineer CLI for Hologram.

- [Installation](#installation)
- [Configuration and credentials](#configuration-and-credentials)
- [Output formats](#output-formats)
- [Mock mode](#mock-mode)
- [Command reference](#command-reference)
  - [`hgm at parse`](#hgm-at-parse) — diagnose AT command logs
  - [`hgm at lookup`](#hgm-at-lookup) — AT command reference and response decoder
  - [`hgm at explain`](#hgm-at-explain) — describe a diagnosis rule
  - [`hgm sim show`](#hgm-sim-show) — single-SIM triage view
  - [`hgm sim sessions`](#hgm-sim-sessions) — recent connectivity sessions
  - [`hgm sim trace`](#hgm-sim-trace) — state transition history
  - [`hgm sim why-paused`](#hgm-sim-why-paused) — explain current SIM state
- [Diagnosis rules reference](#diagnosis-rules-reference)
- [Mock fixture SIMs](#mock-fixture-sims)
- [Architecture overview](#architecture-overview)

---

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"   # editable install with pytest
```

Verify:

```bash
hgm --version
# hologram-cli 0.1.0
```

The package requires Python 3.10+. On Python 3.10 the [`tomli`](https://pypi.org/project/tomli/) backport is installed automatically; on 3.11+ the standard-library `tomllib` is used.

## Configuration and credentials

Credentials can be supplied three ways, in order of precedence:

1. **Environment variables.**
   ```bash
   export HOLOGRAM_API_KEY="..."
   export HOLOGRAM_ORG_ID=12345
   export HOLOGRAM_BASE_URL="https://dashboard.hologram.io/api/1"   # optional
   ```

2. **Config file** at `~/.hologram/config.toml` (path overridable via `HOLOGRAM_CONFIG`):
   ```toml
   default_profile = "personal"

   [profiles.personal]
   api_key = "..."
   org_id = 12345

   [profiles.acme]
   api_key = "..."
   org_id = 67890
   ```
   Then select a profile with `hgm sim show <id> --profile acme`.

3. **Mock mode** (`--mock`) bypasses credentials entirely and uses fixture data. If no credentials are configured and `--mock` is not specified, network commands automatically fall back to mock mode with a warning.

Authentication on the wire is HTTP Basic with username `apikey` and the API key as the password, per the [Hologram REST API docs](https://docs.hologram.io/api/v1).

## Output formats

Every command that produces structured output accepts `--output` / `-o`:

| Format | Use case |
|---|---|
| `table` (default) | Live triage in the terminal — colored, easy to scan |
| `json` | Piping into `jq`, scripts, or feeding to other tools |
| `markdown` | Pasting into tickets, Slack, or PR descriptions |

Example:

```bash
hgm at parse mylog.log -o markdown > diagnosis.md
hgm sim show 893810... --mock -o json | jq '.["Used this period (MB)"]'
```

## Mock mode

`--mock` makes any network-touching command return canned fixture data instead of calling the API. The fixture set covers SIMs in every interesting state — see [Mock fixture SIMs](#mock-fixture-sims) below. Mock mode is automatically engaged when no credentials are configured.

The AT-log analyzer (`hgm at parse`) does not use the network and is unaffected by mock mode.

---

## Command reference

### `hgm at parse`

Diagnose a captured AT command log.

```
hgm at parse [PATH] [--reply] [--sender NAME] [-o {table,json,markdown}]
```

**Arguments**
- `PATH` — path to a log file. Use `-` (or omit and pipe via stdin) to read from stdin.

**Options**
- `--reply` — also draft a customer-facing reply based on the top hypothesis.
- `--sender NAME` — name to sign the reply with (default: `[Your name]`).
- `-o`, `--output` — output format.

**Examples**

```bash
# Triage a fixture and draft a reply:
hgm at parse fixtures/at_logs/02_registration_denied_creg03_ublox.log --reply

# Pipe a live capture from minicom/screen:
cat /tmp/session.log | hgm at parse - --reply --sender "Tom"

# Get markdown for ticket pasting:
hgm at parse mylog.log -o markdown
```

**Output structure**

The analyzer returns a `Diagnosis` containing:
- `health` — `healthy` / `degraded` / `broken`
- `summary` — short headline describing the most likely failure
- `vendor` and `module` — auto-detected from the log (Quectel BG96, u-blox SARA-R5, etc.)
- `hypotheses` — up to three ranked possibilities, each with:
  - `confidence` — `high` / `medium` / `low`
  - `rule_id` — internal rule identifier (use `hgm at explain` to look up)
  - `explanation` — what the analyzer thinks is happening and why
  - `evidence` — specific log lines supporting the hypothesis
  - `next_actions` — ranked technical steps to verify or resolve
  - `customer_summary` — pre-drafted plain-language reply (used when `--reply` is set)

### `hgm at lookup`

AT command reference and response-line decoder. Two related but distinct uses:

```
hgm at lookup <command>             # show command reference
hgm at lookup --decode '<line>'     # explain what a response line means
hgm at lookup --search <keyword>    # find commands by keyword
hgm at lookup --list [--vendor V]   # list all commands, optionally filtered
```

**Examples**

```bash
# What does AT+QIOPEN do?
hgm at lookup AT+QIOPEN

# Leading "AT+" optional, case-insensitive:
hgm at lookup cgpaddr

# Decode a captured response line:
hgm at lookup --decode '+CGPADDR: 1,"100.66.18.214"'
hgm at lookup --decode '+CEREG: 0,3'
hgm at lookup --decode '+QPING: 565,"hologram.io",32,0,0'
hgm at lookup --decode '+CME ERROR: 30'

# Search:
hgm at lookup --search ping
hgm at lookup --search "RAT"

# Browse:
hgm at lookup --list --vendor quectel
hgm at lookup --list --vendor nordic
```

**What's covered**

The reference catalogues ~30 commands across vendors:

- **Standard 3GPP** (TS 27.007): `+CPIN`, `+CFUN`, `+CSQ`, `+CESQ`, `+CREG`, `+CGREG`, `+CEREG`, `+CGDCONT`, `+CGATT`, `+CGACT`, `+CGPADDR`, `+COPS`, `+CEER`, `+CPSMS`, `+CEDRXS`, `+CSCON`
- **Quectel:** `+QCSQ`, `+QCFG`, `+QPING`, `+QIOPEN`, `+QESIM`, `+QENG`, `+QIDNSCFG`
- **u-blox:** `+UCGED`, `+UPING`, `+UBANDMASK`, `+URAT`
- **SIMCom:** `+CMNB`, `+CSERVINFO`
- **Telit:** `#SGACT`, `#SD`
- **Sierra Wireless:** `+KSRAT`
- **Nordic:** `%XSYSTEMMODE`, `%XSNRSQ`

**Response decoders** are registered for the most common URCs an SE encounters mid-triage: `+CEREG/+CGREG/+CREG`, `+CSQ`, `+CESQ`, `+QCSQ`, `+CGPADDR` (with carrier-grade NAT detection), `+COPS` (forbidden-PLMN detection), `+CGATT`, `+CPSMS`, `+CPIN`, `+QPING`, `+CME ERROR`. Each decoder converts the raw line into a plain-language explanation, including domain context like "this IP is in the carrier-grade NAT range, normal for cellular sessions" or "status 3 usually means SIM activation hasn't propagated yet."

**Adding new commands.** Edit `src/hologram_cli/triage/at_reference.py` and append to the `_add(...)` block at the bottom. Decoders are registered by adding a function to `_DECODERS`. No code-path changes needed.

### `hgm at explain`

Print the docstring of a specific diagnosis rule.

```
hgm at explain <rule_id>
```

**Example**

```bash
hgm at explain registration_denied_hss
hgm at explain modem_unresponsive
```

### `hgm sim show`

One-shot triage view for a single SIM.

```
hgm sim show <identifier> [--profile NAME] [--mock] [-o ...]
```

**Arguments**
- `identifier` — accepts ICCID, IMEI, device ID, or SIM name. The CLI heuristically picks the right lookup.

**Output includes**

ICCID • Name • State • Status • Tags • Device ID • Link ID • IMEI • Modem • Plan • Plan limit (MB) • Used this period (MB) • Last session (timestamp + age, country, operator, RAT, RSRP, bytes) • eUICC profile list (if applicable)

**Examples**

```bash
hgm sim show 8938100000123450010 --mock
hgm sim show 350201234567001 --profile acme              # by IMEI
hgm sim show fleet-truck-east-12 --mock                  # by name
```

### `hgm sim sessions`

List recent connectivity sessions for a SIM.

```
hgm sim sessions <identifier> [--profile NAME] [--mock] [-o ...]
```

In mock mode, returns the most recent session from fixture data. Live mode pulls from `/usage/data` and groups into sessions.

### `hgm sim trace`

Walk the activation/state history of a SIM.

```
hgm sim trace <identifier> [--profile NAME] [--mock] [-o ...]
```

Shows every state transition (e.g. `INACTIVE → TEST-ACTIVATE → LIVE-PENDING → LIVE`) with timestamps and time-deltas. Useful when triaging "why hasn't this SIM come online" — you can see exactly where in the activation ladder a SIM is stuck.

### `hgm sim why-paused`

Explain *why* a SIM is in its current state.

```
hgm sim why-paused <identifier> [--profile NAME] [--mock] [-o ...]
```

The name is historical — this command works for any state, not just paused ones. The state oracle covers:

| State | What the oracle does |
|---|---|
| `LIVE` | Confirms healthy. Flags if no session in >7 days (offline device). |
| `LIVE-PENDING` | Differentiates "normal propagation, <10 min old" from "stuck, >10 min". |
| `PAUSED-USER` | Identifies as manual pause; suggests resume path. |
| `PAUSED-SYS` | Cross-references usage vs plan limit; surfaces likely cause (data cap, balance, policy). |
| `TEST-ACTIVATE` | Reports remaining quota out of 100 KB / 10 SMS. |
| `DEAD` | Flags as terminal — replacement SIM required. |
| `INACTIVE` | Confirms claimed-but-not-activated state. |

Severity (`info` / `warning` / `critical`) is rendered alongside the explanation.

---

## Diagnosis rules reference

The analyzer runs a fixed set of rules over a parsed AT log. Each rule examines specific evidence and returns a hypothesis when its pattern matches. The top hypotheses are ranked by confidence and returned.

| Rule ID | Triggers when | Confidence |
|---|---|---|
| `modem_unresponsive` | ≥3 bare `AT` commands with no response | high |
| `sim_pin_locked` | `+CPIN: SIM PIN`, `SIM PUK`, `PH-SIM PIN`, `PH-NET PIN`, etc. | high |
| `sim_not_inserted` | `+CPIN: NOT INSERTED` or `+CME ERROR: 10` on `+CCID` | high |
| `wrong_apn` | `+CGACT` errors with `+CEER` cause 33 OR APN ≠ `hologram` | high (with cause 33), medium otherwise |
| `roaming_denied` | `+COPS=?` scan returns at least one PLMN with status 3 (forbidden) | high |
| `registration_denied_hss` | `+CREG/+CEREG: 0,3` AND no forbidden PLMN scan present | high |
| `searching_no_register` | `+CEREG: 0,2` AND (NB-IoT-locked via any vendor's RAT-mode command OR weak RSRP) | medium |
| `band_locked` | `+CSQ: 99,99` AND `+COPS=?` returns no networks | medium |
| `marginal_signal` | RSRP ≤ −115 dBm anywhere in log (parsed from `+QCSQ`, `+RSRP`, OR standard `+CESQ`) | high (with ping timeouts), medium otherwise |
| `dns_failure` | Pings to numeric IPs succeed but pings to hostnames all fail | high |
| `test_quota_exhausted` | Healthy attach + IP allocated + ALL pings fail | medium |
| `psm_aggressive` | `+CPSMS: 1` (PSM enabled) | high |
| `euicc_wrong_profile` | Multiple eUICC profiles + active profile cannot register | high |

Special hypotheses (synthesized when no rule matches):
- `healthy_baseline` — `+CEREG: 0,1` AND `+CGATT: 1` AND `+CGACT` succeeds AND **an application-layer probe succeeded** (a `+QPING` reply with code 0, a `+UUPING` reply, or a socket `CONNECT`). Without that last criterion the analyzer no longer claims `healthy` — too easy to mask DNS failures, marginal signal, or quota exhaustion.
- `appears_attached` — attach is healthy but no application-layer probe is captured. Confidence: medium. Recommends running a ping test to confirm the data path.
- `unknown` — log doesn't contain enough signal to make a confident call.

Disambiguation: when both `roaming_denied` and `registration_denied_hss` could fire, the presence of a forbidden-PLMN scan result is the deciding signal — without it, the analyzer treats the registration denial as a likely fresh-activation propagation issue (which resolves with time) rather than a true roaming denial (which requires a profile change).

---

## Mock fixture SIMs

Available in mock mode. Use any of these identifiers with `hgm sim show|why-paused|trace|sessions`:

| ICCID | State | Notes |
|---|---|---|
| `8938100000123450010` | LIVE | Healthy, recent session, fleet-truck-east-12 |
| `8938100000123450020` | LIVE-PENDING | Activated 7 min ago, propagation in progress |
| `8938100000123450030` | PAUSED-SYS | Exceeded 10 MB plan with 12.4 MB usage |
| `8938100000123450040` | PAUSED-USER | Manually paused 3 days ago, decom-pending |
| `8938100000123450050` | TEST-ACTIVATE | 82 KB of 100 KB used; about to auto-promote |
| `8938100000123450060` | DEAD | Terminal — deactivated 90 days ago |
| `8938100000123450070` | LIVE | eUICC Hyper SIM with two profiles, EU pilot |

Identifiers also resolve by IMEI, device ID, or SIM name — see `mock_data.py` for the full fixture schema.

---

## Architecture overview

```
                    ┌──────────────────────┐
                    │   hgm (Typer app)    │
                    └──────────┬───────────┘
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
        ┌──────────┐     ┌──────────┐     ┌──────────┐
        │ commands │     │ commands │     │ commands │
        │   /at    │     │   /sim   │     │  (more)  │
        └─────┬────┘     └─────┬────┘     └──────────┘
              │                │
              ▼                ▼
        ┌────────────────────┐     ┌──────────────────┐
        │  triage            │     │     client       │
        │  ├ parser          │     │  (httpx + auth)  │
        │  ├ signals (vendor │     └────────┬─────────┘
        │  │   adapter)      │              │
        │  ├ analyzer        │     ┌────────▼─────────┐
        │  ├ at_reference    │     │ live API or mock │
        │  ├ oracle          │     │     fixtures     │
        │  └ reply           │     └──────────────────┘
        └────────────────────┘
```

**Triage layer is fully offline.** The parser, signal adapter, analyzer, AT reference, oracle, and reply drafter operate purely on text input or fixture dicts — no network dependency, no auth requirement, no flakiness. This is by design: triage tooling that depends on a live API doesn't work when the API is what's being triaged.

**The vendor adapter (`signals.py`) keeps rules vendor-agnostic.** Rules ask "what's the lowest RSRP in this log" or "is the modem RAT-locked to NB-IoT" without caring whether the answer comes from Quectel `+QCSQ`, u-blox `+UCGED`, standard `+CESQ`, SIMCom `+CMNB`, or Nordic `%XSYSTEMMODE`. Adding support for a new module family is a one-file change in the adapter.

**Client layer is httpx + Basic auth + retry.** Rate-limited (HTTP 429) responses are retried with exponential backoff up to 4 attempts. Mock mode short-circuits the HTTP path entirely.

**Output layer is format-agnostic.** Commands hand the formatter a dict-or-dataclass payload; the formatter renders to the requested format. Adding a new output format (HTML, slack-mrkdwn) is a one-place change.
