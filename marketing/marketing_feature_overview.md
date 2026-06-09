# IoT Cellular Fleet Triage Platform
### Feature Overview

---

## What It Is

A purpose-built internal tooling suite for IoT solutions engineering teams. It turns a raw modem AT command log into a ranked diagnosis, a customer-ready reply, and a set of next actions — in under a second, from the command line or a browser.

---

## Core Capabilities

### AT Log Analyzer — 13 Diagnosis Rules

| Rule | What It Catches |
|------|----------------|
| Modem unresponsive | Hardware / serial-layer failure before network |
| SIM not inserted | UICC detection failure |
| SIM PIN locked | PIN or PUK security gate |
| Wrong APN | PDP context activation failing on bad APN string |
| Roaming denied | Carrier explicitly rejecting registration (+COPS stat 3) |
| HSS propagation delay | Registration denied on recently activated SIM |
| Searching / no register | RAT lock or NB-IoT coverage mismatch |
| Band locked | Band mask excluding local tower bands |
| Marginal RF signal | RSRP at or below LTE-M sensitivity threshold |
| DNS failure | IP path healthy, hostname resolution broken |
| Test quota exhausted | TEST-ACTIVATE 100 KB allowance used up |
| PSM over-aggressive | "Device disappearing" is expected PSM behavior |
| eUICC wrong profile | Active profile failing, fallback not triggered |

Each diagnosis includes: confidence rating, supporting evidence with log line numbers, ranked next actions, and a customer-facing plain-language summary ready to paste into a ticket.

---

### SIM State Oracle

Maps every Hologram SIM state to a plain-language explanation and set of next actions:

- `LIVE` — online, or online but silent for 7+ days (warning)
- `LIVE-PENDING` — activation in progress vs. stuck propagation
- `PAUSED-USER` / `PAUSED-SYS` — manual vs. system pause (data cap, balance)
- `TEST-ACTIVATE` — testing window with quota tracking
- `DEAD` / `INACTIVE` — terminal and inventory states

---

### Browser Dashboard — 5 Phases

```
Phase 1  Triage Workbench       Paste log → diagnosis + reply, in-browser
Phase 2  Fleet Browse           SIM index, audit trail, Codex KB, AT reference
Phase 3  Fleet Health           30-day rule trends, hot-group clustering
Phase 4  Operations             Bulk SIM ops, onboarding wizard, Conductor eUICC console
Phase 5  Self-Service Portal    Customer-scoped triage without SE involvement
```

---

### Codex Knowledge Base

A structured, searchable store of resolved triage cases — vendor, module, carrier, RAT, symptom tags, diagnosis, and fix. Each new triage session can be promoted to the Codex in one click, turning individual case resolutions into compounding institutional knowledge.

---

## Technical Highlights

- **Fully offline triage.** The AT log analyzer never touches the network.
- **Mock-first design.** Complete SIM fixture data set covers every documented state — fully demoable with no API key.
- **No logic duplication.** The web dashboard imports the CLI's triage modules directly; a single fix propagates everywhere.
- **Output formats:** `table` (live triage), `json` (pipe to other tools), `markdown` (paste into tickets or Slack).
- **89 automated tests** with per-rule end-to-end coverage against 12 synthetic AT logs.

---

## Tech Stack

Python 3.10+ · FastAPI · Jinja2 · HTMX · SQLite · Typer · Rich · pytest · uvicorn

---

*Built for IoT Solutions Engineering teams managing LTE-M / NB-IoT fleets at scale.*
