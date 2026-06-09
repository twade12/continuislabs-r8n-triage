# System Architecture Overview
### IoT Cellular Fleet Triage Platform

---

## Bird's-Eye View

```
┌─────────────────────────────────────────────────────────────────────┐
│                        hgm-web  (FastAPI)                           │
│                                                                     │
│  /triage     /sims     /audit    /codex    /fleet    /conductor     │
│  /at         /bulk     /onboard  /search   /portal                  │
│                        │                                            │
│              Jinja2 templates + HTMX partials                       │
│              SQLite (audit log · Codex · bulk ops · policies)       │
└────────────────────────┬────────────────────────────────────────────┘
                         │ imports directly (no subprocess, no HTTP)
┌────────────────────────▼────────────────────────────────────────────┐
│                    hologram_cli  (Python package)                   │
│                                                                     │
│  triage/                                                            │
│    parser.py       AT log → structured exchanges                    │
│    analyzer.py     13 diagnosis rules → ranked Hypothesis list      │
│    signals.py      vendor-agnostic RSRP / RAT-lock helpers          │
│    at_reference.py AT command catalogue + response decoders         │
│    reply.py        draft customer-facing reply from diagnosis       │
│    oracle.py       SIM state → plain-language explanation           │
│                                                                     │
│  commands/                                                          │
│    at.py           hgm at parse | lookup | explain                  │
│    sim.py          hgm sim show | sessions | trace | why-paused     │
│                                                                     │
│  client.py         Hologram REST API (HTTP Basic) + mock fallback   │
│  mock_data.py      fixture SIMs in every documented state           │
│  output.py         table | json | markdown formatters               │
└────────────────────────┬────────────────────────────────────────────┘
                         │
          ┌──────────────┴──────────────┐
          │                             │
   Hologram REST API              Mock fixtures
   (live, requires key)           (no key needed)
```

---

## Key Design Decisions

### 1 — Triage logic is the package; everything else is a shell

The AT-log parser, 13 diagnosis rules, signal helpers, and state oracle live entirely inside `hologram_cli`. The CLI and the web app are thin shells that import and invoke that core. There is no HTTP boundary between the dashboard and the analyzer — a fix to a rule propagates to both consumers with no coordination.

### 2 — Mock-first, API-optional

Every command and every dashboard route has a fully functional path with no Hologram API key. The `client.py` module checks for a key at call time and falls back to `mock_data.py` if absent. This means the platform is:
- Instantly demoable in any environment
- Testable in CI without credential management
- Fully usable for training and onboarding before API access is provisioned

### 3 — AT log parsing is vendor-agnostic

The parser normalizes Quectel and u-blox AT responses to a common exchange structure. Diagnosis rules are written against the normalized form and work across both module families without vendor-specific branching in the rule layer.

### 4 — SQLite is the right persistence layer here

The audit trail, Codex KB, bulk op log, and Conductor policy store are all single-process, single-server data — SQLite's zero-config, zero-dependency profile is appropriate. The schema is straightforward and the database file (`web/hgm-web.sqlite`) is trivially portable.

---

## Data Flow: Triage Workbench (Phase 1)

```
Browser
  │  POST /triage/diagnose  (raw_log, iccid?, sender, persist?)
  ▼
FastAPI route (web/main.py)
  │
  ├─ parse(raw_log)           → ParsedLog
  │    (triage/parser.py)
  │
  ├─ analyze(log)             → Diagnosis  [13 rules, ranked hypotheses]
  │    (triage/analyzer.py)
  │
  ├─ draft_reply(diagnosis)   → str        [customer-ready text]
  │    (triage/reply.py)
  │
  ├─ explain_state(sim)       → StateExplanation  (if iccid supplied)
  │    (triage/oracle.py)
  │
  ├─ find_similar_codex(...)  → [CodexEntry]  (Phase 3 similarity)
  │    (web/db.py)
  │
  └─ save_triage(...)         → session_id   (if persist="on")
       (web/db.py)

  → TemplateResponse: partials/triage_result.html
       (HTMX swaps this into the workbench page without a full reload)
```

---

## Test Coverage

```
tests/
  test_parser.py        Exchange extraction, vendor detection, response parsing
  test_analyzer.py      End-to-end rule tests — one fixture log per fault mode
  test_signals.py       RSRP extraction, RAT-lock detection
  test_oracle.py        State oracle across all documented SIM states

89 tests · all deterministic · no network required · no API key required
```

---

## Planned Extensions (Roadmap)

| Wave | What |
|------|------|
| 3 | Codex auto-suggestion from historical triage patterns (modem × carrier × country × firmware) |
| 4 | MCP server exposing CLI operations as agent tools; Triage Co-Pilot that drafts replies but never auto-sends |

---

*Python 3.10+ · FastAPI · Jinja2 · HTMX · SQLite · Typer · Rich · pytest*
