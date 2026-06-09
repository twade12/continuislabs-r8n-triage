# Fiverr Project Listing

---

## Project Name

**IoT Cellular Fleet Triage Platform — CLI + Browser Dashboard for SIM Diagnostics**

---

## Industry

1. IoT & Embedded Systems
2. Telecommunications
3. Software Development & Engineering
4. DevOps & Internal Tooling
5. Data Analytics & Visualization
6. SaaS / Cloud Infrastructure

---

## Project Duration

**2–3 weeks**

---

## Project Description

**The Client**

Hologram is a global IoT cellular platform that provides SIM cards, connectivity management APIs, and fleet orchestration tooling to hardware companies worldwide. Their Solutions Engineering team supports customers spanning agriculture, logistics, industrial sensing, and asset tracking — all of whom depend on reliable LTE-M and NB-IoT connectivity for their deployed devices.

**Their Goals**

The SE team needed internal tooling to cut the time from "customer files a ticket" to "root cause identified and reply drafted" — a workflow that currently required manually reading raw AT command modem logs, cross-referencing carrier knowledge, and navigating between the API, dashboard, and documentation in parallel. Specifically:

- Diagnose modem connectivity failures from raw AT command logs in seconds, not minutes
- Automatically draft customer-facing replies with accurate technical context and next steps
- Surface why a SIM is in its current state (PAUSED-SYS, LIVE-PENDING, etc.) without digging through the API docs
- Build an institutional knowledge base ("Codex") so resolved cases compound into future triage speed
- Give customers a self-service path for basic diagnostics without engaging SE

**What Was Built**

The project delivered two integrated components:

**1. `hgm` — A Python CLI wrapping the Hologram REST API and AT-log analyzer**

A `hgm` command with two sub-trees:

- `hgm at parse <log>` — runs an AT command log through a 13-rule deterministic analyzer covering: modem unresponsive, SIM not inserted, SIM PIN locked, wrong APN, roaming denied, HSS propagation delay, RAT/band config mismatch, marginal RF, DNS failure, PSM over-aggressiveness, test-quota exhaustion, and eUICC wrong-profile fallback. Each hit produces a confidence-ranked hypothesis, evidence with line numbers, ranked next actions, and a ready-to-send customer-facing summary.
- `hgm at lookup` / `hgm at explain` — AT command reference and response decoder (covers Quectel and u-blox command sets)
- `hgm sim show` / `hgm sim why-paused` / `hgm sim trace` — SIM state oracle that explains in plain language why a SIM is in its current state and what to do next, driven by the Hologram state machine (LIVE → PAUSED-SYS → DEAD, etc.)
- All commands support `--output table|json|markdown`. The markdown form pastes directly into tickets or Slack.
- Full mock mode: the CLI works end-to-end with no API key — critical for demos and development.

The test suite covers 89 cases: parser unit tests, per-rule end-to-end tests against 12 synthetic AT logs (one per fault mode), and state oracle tests across every documented SIM state.

**2. `hgm-web` — A FastAPI + HTMX browser dashboard**

A five-phase internal tool built as a FastAPI application that imports the CLI's triage modules directly (no logic duplication), with HTMX for live interactivity and Jinja2 templates:

- **Phase 1 — Triage Workbench:** Paste a raw AT log, get a diagnosis, ranked hypotheses, evidence, and a draft reply — all in-browser. Optionally attach a SIM ICCID to correlate state oracle data alongside the log analysis.
- **Phase 2 — SIM Index, Audit Log, Codex KB, AT Reference:** Browse all SIMs with state/tag filters; review triage session history; build and search the Codex knowledge base of resolved cases; look up and decode AT commands interactively.
- **Phase 3 — Fleet Health Dashboard:** Aggregated view of fault patterns across the fleet over the last 30 days — rule hit counts, module breakdowns, state distribution, and "hot group" flagging for tags with clustered failures.
- **Phase 4 — Bulk Operations, Onboarding Wizard, Conductor Console:** Dry-run bulk SIM operations with ICCID multi-select; a step-by-step SIM onboarding guide; Conductor eUICC profile management with manual profile switching and policy creation/toggling.
- **Phase 5 — Customer Self-Service Portal:** A scoped, customer-facing view where end users can run AT log diagnostics and view their own SIM list without SE involvement.

The dashboard is backed by SQLite for the audit trail, Codex entries, bulk op history, and Conductor policy log — giving SE leads a persistent record of every triage session and outcome.

**Challenges and How They Were Handled**

*Vendor format divergence.* Quectel and u-blox modems report the same logical information in syntactically different ways. The AT log parser was designed with vendor-specific response decoders that normalize to a common structure before any rule sees the data — rules are written against the normalized form and work across both vendors without branching.

*Avoiding false positives in the rule engine.* Thirteen rules covering thirteen distinct failure modes creates risk of misclassification — for example, a SIM stuck searching (+CEREG: 2) looks identical whether the cause is a band-mask problem, marginal signal, or a roaming denial. Each rule was designed with explicit preconditions that require positive confirming evidence (a forbidden PLMN in the scan, a measured RSRP below threshold, a non-default RAT lock) before firing. Catch-all hypotheses are only returned when no specific rule matches.

*Logic reuse across CLI and web.* The triage brain — parser, analyzer, signal helpers, oracle — lives entirely in the Python package. The FastAPI app imports those modules directly rather than re-implementing or calling a subprocess. This means a fix to the analyzer automatically appears in both the CLI and the web without coordination.

*Demoing without live credentials.* Hologram API access is account-gated. The entire CLI and dashboard work against a rich mock data set (SIMs in every documented state, complete state history, eUICC profiles, session records) so SE can demo, develop, and train against realistic data without an API key configured.

---

## Attachments

The following marketing materials accompany this project:

- [Feature Overview Sheet](marketing_feature_overview.md) — one-page capability summary suitable for sharing with stakeholders or including in a portfolio
- [System Architecture Overview](marketing_architecture.md) — technical one-pager showing how the components fit together, for technically-oriented audiences
