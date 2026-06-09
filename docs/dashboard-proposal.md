# Dashboard proposal — `hgm-web`

A browser-based front end for the Hologram SE workflow, built on the existing `hgm` CLI's diagnostic engine plus a thin API layer wrapping live Hologram data and a Postgres-backed audit/knowledge store.

## Why this matters

The CLI already does the hard analytical work: parsing AT logs across vendors, ranking diagnostic hypotheses, decoding response lines, explaining SIM states, drafting customer replies. But a CLI is the *wrong shape* for several of the things an SE actually does day-to-day:

- **Browsing.** Scanning 200 SIMs across 5 customers to find the 3 in trouble is a table problem, not a command problem.
- **Collaboration.** Sharing a diagnosis with an account manager or product engineer is friction-heavy from a terminal.
- **Compounding knowledge.** Every triage session today produces insight that's lost the moment the ticket closes. A persistent layer captures it.
- **Customer-facing.** Eventually some SE work — onboarding walkthroughs, log paste-and-diagnose — could move to a customer self-service portal. That has to be browser-based.

A dashboard turns the CLI from "tool the SE uses solo" into "platform the SE team works on top of."

## Core architectural insight: thin web shell over a fat CLI core

The CLI's `triage/` package is intentionally I/O-free. Every meaningful function takes structured input and returns structured output:

```
parse(text) → ParsedLog
analyze(log) → Diagnosis
draft_reply(diagnosis) → str
explain_state(sim_dict) → StateExplanation
decode_response(line) → str | None
lookup(name) → ATCommand | None
```

This means the entire backend for `hgm-web` is fundamentally a **FastAPI wrapper around imports**. Endpoints take HTTP request bodies, call the existing functions, return JSON. The analytical investment we've already made is reused 1:1.

```
                   ┌────────────────────┐
                   │   Browser (React)  │
                   └──────────┬─────────┘
                              │  REST + SSE
                   ┌──────────▼─────────┐
                   │   FastAPI shell    │
                   │   ─ thin auth      │
                   │   ─ thin routing   │
                   └──────────┬─────────┘
                              │  direct imports
                   ┌──────────▼─────────┐
                   │   hgm CLI core     │
                   │   ─ parser         │
                   │   ─ signals        │
                   │   ─ analyzer       │
                   │   ─ oracle         │
                   │   ─ at_reference   │
                   │   ─ reply drafter  │
                   │   ─ client (api)   │
                   └──────────┬─────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
    ┌──────────────┐ ┌────────────┐ ┌──────────────┐
    │ Hologram API │ │  Postgres  │ │ Object store │
    │ (live)       │ │ (audit/KB) │ │ (raw logs)   │
    └──────────────┘ └────────────┘ └──────────────┘
```

The Postgres layer is the only genuinely new component.

## Page-by-page tour

Each page below names a clear purpose, lists the key features, and identifies which CLI function it reuses. Layout is sketched in ASCII to make the information density tangible.

### 1. Triage Workbench

**The killer page.** The single thing an SE will use 30 times a day. Inputs a customer message + AT log, produces a complete triage summary and a draft reply.

```
┌───────────────────────────────────────────────────────────────────────────────┐
│  Triage Workbench                                  ticket #4421  [save] [send] │
├──────────────────────────────────┬────────────────────────────────────────────┤
│  Customer message                │  Diagnosis                                 │
│  ┌────────────────────────────┐  │  ┌──────────────────────────────────────┐  │
│  │ "Device won't connect, we  │  │  │  BROKEN  Registration denied — SIM   │  │
│  │  activated yesterday..."   │  │  │  activation likely not yet propagated │  │
│  └────────────────────────────┘  │  │                                      │  │
│                                  │  │  vendor: u-blox SARA-R510M8S         │  │
│  AT log                          │  │  confidence: HIGH    rule: ...       │  │
│  ┌────────────────────────────┐  │  │                                      │  │
│  │  AT+CEREG?                 │  │  │  Evidence:                           │  │
│  │  +CEREG: 0,3   ◀──[click]  │  │  │  • line 37: +CEREG -> status 3       │  │
│  │  AT+CGATT=1                │  │  │    [decode]                          │  │
│  │  +CME ERROR: 30            │  │  │  • line 27: +CSQ rssi=16 (RF fine)   │  │
│  │  ...                       │  │  │  • line 45: AT+CGATT failed: CME:30  │  │
│  └────────────────────────────┘  │  │                                      │  │
│                                  │  │  Next actions:                       │  │
│  ICCID (resolves SIM card)       │  │  • Wait 30–60 min, re-check          │  │
│  ┌────────────────────────────┐  │  │  • Look up state in dashboard        │  │
│  │  893810000... [▼ matches]  │  │  │  • Escalate L3 if still denied       │  │
│  └────────────────────────────┘  │  └──────────────────────────────────────┘  │
│                                  │                                            │
│  Customer info (auto-populated)  │  Draft reply              [edit inline]   │
│  ┌────────────────────────────┐  │  ┌──────────────────────────────────────┐  │
│  │ FleetCo / Tom Smith         │  │  │  Hi Tom,                            │  │
│  │ 245 SIMs, $12K/mo plan      │  │  │                                      │  │
│  │ 3 prior tickets             │  │  │  I can see what's happening in your  │  │
│  └────────────────────────────┘  │  │  log — your device has good signal   │  │
│                                  │  │  ...                                 │  │
│                                  │  └──────────────────────────────────────┘  │
└──────────────────────────────────┴────────────────────────────────────────────┘
```

**Features:**

- **Paste-and-go.** Drop a log, click Diagnose, get hypotheses + evidence + draft reply in one action. No multi-step flow.
- **Inline decoding.** Click any AT command or response in the log → tooltip popup with the `at_reference` decoder output. Hovering `+CEREG: 0,3` explains it without leaving the page.
- **Side-by-side editing.** The drafted reply is fully editable inline. The SE can tweak tone, add specifics, then send.
- **ICCID-aware.** Paste an ICCID anywhere and the workbench auto-fetches SIM state from the API and cross-references with the log. ("The log shows registration denied; the SIM is in LIVE-PENDING state, activated 12 minutes ago — consistent with HSS propagation delay.")
- **Customer context.** Pulls org info, plan, recent tickets, and known quirks for this customer (from the codex — see below) so the reply draft can reference the customer's specific situation.
- **One-click integrations.** Send to Zendesk / Salesforce / Slack with one click. The diagnosis becomes a ticket comment, the reply goes to the customer, the action is audited.

**CLI reuse:** `parse()`, `analyze()`, `draft_reply()`, `decode_response()`, `client.get_sim()`.

### 2. SIM Detail

Like `hgm sim show` but interactive. The page you land on when clicking through from any other view.

```
┌────────────────────────────────────────────────────────────────────────────────┐
│  SIM 893810000012345001  ─  fleet-truck-east-12  ─  [pause] [resume] [tag]    │
├────────────────────────────────────────────────────────────────────────────────┤
│                                                                                │
│  ╔═══════════════════════╗  ╔═══════════════════════════════════════════════╗  │
│  ║  STATUS: CONNECTED    ║  ║  Why?                                          ║  │
│  ║  Plan: Global 100MB   ║  ║                                                ║  │
│  ║  Used: 47.2 / 100 MB  ║  ║  SIM is in LIVE state with recent sessions.   ║  │
│  ║  Last seen: 15 min ago║  ║  No action needed.                            ║  │
│  ╚═══════════════════════╝  ╚═══════════════════════════════════════════════╝  │
│                                                                                │
│  Sessions timeline                                                             │
│  ┌──────────────────────────────────────────────────────────────────────────┐  │
│  │   ▌▌▌  ▌  ▌▌▌▌▌    ▌  ▌▌▌▌    ▌▌      ▌▌▌▌▌▌                            │  │
│  │  Mon  Tue   Wed   Thu  Fri   Sat    Sun                                  │  │
│  └──────────────────────────────────────────────────────────────────────────┘  │
│                                                                                │
│  State history                                                                 │
│  ┌──────────────────────────────────────────────────────────────────────────┐  │
│  │  2026-04-28 03:14  LIVE                                                  │  │
│  │  2026-04-28 03:04  LIVE-PENDING                                          │  │
│  │  2026-04-28 03:04  TEST-ACTIVATE                                         │  │
│  │  2026-04-28 02:54  INACTIVE                                              │  │
│  └──────────────────────────────────────────────────────────────────────────┘  │
│                                                                                │
│  Tickets [3]                              eUICC profiles                       │
│  ┌──────────────────────────────────┐    ┌──────────────────────────────────┐  │
│  │  #4421 (open)  reg denied        │    │  ✓ EU-Multi (active)             │  │
│  │  #4109 (closed) wrong APN        │    │  ○ Global-Fallback               │  │
│  │  #3984 (closed) marginal signal  │    │  [switch profile]                │  │
│  └──────────────────────────────────┘    └──────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────────────┘
```

**Features:**

- **State + Why combined.** Always show the state oracle's explanation alongside the raw state. Severity color-coded.
- **Sessions timeline.** Visual histogram of activity, useful to instantly see "this device went silent two days ago" or "this device is talking constantly."
- **Quick actions.** Pause / Resume / Tag / Change Plan / Switch Profile (for Hyper SIMs). Every action prompts confirmation and writes to the audit log.
- **Cross-references.** Ticket history (open + closed), past diagnoses, related SIMs (same fleet, same customer).
- **Map view (optional).** If location is reported in the last session, drop a pin.

**CLI reuse:** `client.get_sim()`, `explain_state()`.

### 3. Org Overview

For an SE working across multiple customers, the "where's the trouble?" page for a single org.

```
┌───────────────────────────────────────────────────────────────────────────────┐
│  FleetCo (org #4421)                                              [filter]    │
├───────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  Fleet at a glance              Anomalies                                     │
│  ┌──────────────────────────┐  ┌─────────────────────────────────────────┐   │
│  │  245 SIMs total          │  │ ⚠ 5 SIMs paused-sys this week           │   │
│  │  ░░░░░░░░░░░░░░░░░ 233   │  │   all on Global-100MB plan               │   │
│  │  CONNECTED                │  │   suggested: bump plan size              │   │
│  │  ▓▓▓▓ 7   PAUSED-SYS     │  │                                          │   │
│  │  ▓▓ 3     LIVE-PENDING   │  │ ⚠ 12 SIMs zero usage > 7 days           │   │
│  │  ▓ 2      OTHER          │  │   may be powered off or decommissioned   │   │
│  └──────────────────────────┘  └─────────────────────────────────────────┘   │
│                                                                               │
│  Usage trend (30 days)                                                        │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │      ▁▁▂▃▃▄▅▅▅▅▆▆▇▇█▇▆▆▅▆▇▇▇▆▆▆▇                                       │ │
│  │   Apr 1            Apr 15             Apr 30                            │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                               │
│  SIMs in trouble  [12]                                                        │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │  ICCID            Name              State        Issue                  │ │
│  │  893810...001    truck-east-12    LIVE         (none)                   │ │
│  │  893810...002    truck-east-13    PAUSED-SYS   data cap (12.4/10 MB)   │ │
│  │  893810...003    truck-east-14    PAUSED-SYS   data cap (12.4/10 MB)   │ │
│  │  ...                                                                     │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────────────────────┘
```

**Features:**

- **Anomaly callouts** computed by the dashboard scheduler: "5 SIMs paused-sys all on the same plan" is the kind of insight worth surfacing without an SE having to ask.
- **Filterable SIM table** with sticky search, multi-select, bulk actions.
- **Usage trends** to spot growth, drops, or unusual patterns.
- **Open tickets summary** at the org level so SE can see what's outstanding.

**CLI reuse:** `client.list_sims()`, `explain_state()` for each problematic SIM.

### 4. Fleet Health (cross-org)

For SE managers and CSMs. "Across all our customers, what's the state of the world?"

```
┌────────────────────────────────────────────────────────────────────────────────┐
│  Fleet Health   ─   all orgs                                                   │
├────────────────────────────────────────────────────────────────────────────────┤
│                                                                                │
│  Cross-cutting issues this week                                                │
│                                                                                │
│  Issue                              SIMs   Orgs   Δ vs last wk                │
│  registration_denied_hss            127    14     ▲ 22%                       │
│  marginal_signal                     89    19     ▼ 5%                        │
│  paused-sys (data cap)              34    8      ▲ 8%                        │
│  euicc_wrong_profile                 12    3      ▲ NEW                       │
│  dns_failure                          8    2      ▲ NEW                       │
│                                                                                │
│  ────────────────────────────────────────────────────────────────────────     │
│                                                                                │
│  Hot orgs (most open issues)                                                   │
│                                                                                │
│  AcmeFleet      28 SIMs in trouble  • 5 SIM activations stuck > 1 hour        │
│  IoTPro         19 SIMs in trouble  • mass paused-sys on Global-50            │
│  GreenEnergy    14 SIMs in trouble  • marginal signal across 14 sites          │
│                                                                                │
│  ────────────────────────────────────────────────────────────────────────     │
│                                                                                │
│  By module (last 30 days)                                                      │
│                                                                                │
│  Module           Total   Diagnosed-broken   Most common fault                │
│  Quectel BG96     5,213   2.1%               wrong_apn                        │
│  Quectel BG95-M3  3,891   3.4%               searching_no_register            │
│  u-blox SARA-R5     871   1.8%               registration_denied_hss          │
│  Telit ME910C1      342   2.9%               wrong_apn                        │
│  ...                                                                          │
└────────────────────────────────────────────────────────────────────────────────┘
```

**Features:**

- **Aggregated diagnoses** across all triaged logs. "Are we seeing a spike in registration denials this week?"
- **Hot org list** to drive proactive customer outreach.
- **Module-level patterns** to inform engineering and product. ("BG95 has 1.6× the wrong_apn rate of BG96 — is there a firmware issue?")
- **Trends with deltas** to flag unusual movement.

**Powered by the audit log.** This page only works because every triage in the workbench writes a structured record. See § 5.

### 5. Audit Log + Codex Knowledge Base

This is the highest-leverage idea in the proposal. The user explicitly asked about audit logs across AT command logs / hardware types / hardware versions, and the cleanest design treats audit + KB as a *single* compounding system.

#### Schema (Postgres)

```sql
CREATE TABLE triage_sessions (
  id              UUID PRIMARY KEY,
  ts              TIMESTAMPTZ DEFAULT NOW(),
  se_user_id      UUID REFERENCES users(id),
  org_id          BIGINT,                    -- nullable
  iccid           TEXT,                      -- nullable
  imei            TEXT,                      -- nullable
  vendor          TEXT,                      -- detected from log
  module          TEXT,
  module_firmware TEXT,
  raw_log         TEXT NOT NULL,             -- AT log as captured
  customer_msg    TEXT,                      -- the customer's complaint
  diagnosis       JSONB NOT NULL,            -- top hypothesis ranks
  reply_drafted   TEXT,
  reply_sent      TEXT,                      -- after SE edit
  outcome         TEXT,                      -- resolved | escalated | abandoned
  outcome_cause   TEXT,                      -- customer-confirmed root cause
  ticket_ref      TEXT,                      -- e.g. zendesk:#4421
  resolution_min  INT                        -- time to close
);

CREATE INDEX ON triage_sessions (vendor, module, (diagnosis->>'top_rule_id'));
CREATE INDEX ON triage_sessions (org_id, ts DESC);
CREATE INDEX ON triage_sessions USING GIN (diagnosis);

CREATE TABLE codex_entries (
  id              UUID PRIMARY KEY,
  source_session  UUID REFERENCES triage_sessions(id),
  title           TEXT NOT NULL,
  vendor          TEXT,
  module          TEXT,
  module_firmware TEXT,
  carrier         TEXT,
  mcc             TEXT,
  mnc             TEXT,
  rat             TEXT,                      -- cat-m1 | nb-iot | lte | 5g
  symptom_tags    TEXT[],                    -- e.g. ['creg-0-3','cause-8','attach-fail']
  diagnosis       TEXT,                      -- free text
  fix             TEXT,                      -- free text
  contributor     UUID REFERENCES users(id),
  created_at      TIMESTAMPTZ DEFAULT NOW(),
  upvotes         INT DEFAULT 0,
  ticket_refs     TEXT[]
);

CREATE INDEX ON codex_entries (vendor, module, carrier);
CREATE INDEX ON codex_entries USING GIN (symptom_tags);
```

#### What gets written when

| Event | Writes |
|---|---|
| SE clicks "Diagnose" in the workbench | New `triage_sessions` row with `raw_log`, `diagnosis`, `vendor`, `module`. |
| SE edits the drafted reply and sends | `reply_sent` populated. |
| SE marks ticket resolved with cause | `outcome`, `outcome_cause`, `resolution_min`. |
| SE clicks "Save to KB" on a resolved session | New `codex_entries` row, linked to source session. |
| Customer confirms root cause via reply | `outcome_cause` updated. |

#### What this enables

**A. Auto-suggest similar cases during triage.**
Workbench query on every diagnose call: *"Find codex entries where `vendor=quectel`, `module=BG95`, `carrier='Verizon'`, and any of the detected symptom tags match."* Show top 3 in a sidebar with one-click "this looks similar — apply" action.

**B. Pattern detection cron.**
Daily job: *"Find any (vendor, module, carrier, symptom) combination that's appeared in ≥5 triage sessions this week, hasn't been documented in codex yet, and produced ≥3 different SE-edited replies."* Surface as "candidate KB entries" for an SE to review and write up.

**C. Module-level fault rates** for the Fleet Health page.
*"GROUP BY module, top_rule_id ORDER BY count DESC LIMIT 5 per module"* gives you the table from § 4 directly.

**D. Compliance-friendly audit trail.**
Every diagnosis run, every action taken, every customer reply sent is in the table with timestamps, SE identity, and the underlying log. For regulated customers (medical, automotive) this is non-negotiable.

**E. Time-to-resolution metrics by category.**
*"Median resolution time for `wrong_apn` is 45 min; for `roaming_denied` is 2.3 hours."* Drives operational improvement.

#### UI: Codex search & contribution

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Codex                                                          [+ new entry] │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Filter:  vendor [quectel ▼]  module [BG95-M3 ▼]  symptom [creg-0-3 ▼]      │
│                                                                              │
│  4 entries match                                                             │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  Quectel BG95 + Verizon: SIM lock fix                                │   │
│  │  vendor: quectel    module: BG95-M3    carrier: Verizon              │   │
│  │  rat: cat-m1        symptoms: creg-0-3, cause-7                      │   │
│  │                                                                      │   │
│  │  Verizon requires explicit IMEI-to-ICCID linking on the carrier      │   │
│  │  dashboard before allowing attach. Without it, +CREG: 0,3 with        │   │
│  │  EMM cause 7 ("EPS services not allowed") fires.                     │   │
│  │                                                                      │   │
│  │  Fix: customer/SE submits ICCID + IMEI to the carrier's MDN          │   │
│  │  binding form, wait ~2 hrs.                                          │   │
│  │                                                                      │   │
│  │  by Tom Smith • 2026-04-12 • 7 tickets reference • [▲ 12]            │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│  ...                                                                         │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Why this compounds.** After 100 entries, an SE searching "Quectel BG95 + Verizon + +CREG 0,3" gets pre-resolved cases instead of starting from scratch. After 1,000, you can run rules like *"any new ticket matching ≥2 codex entries auto-applies the most-upvoted fix as the first reply draft."*

### 6. AT Command Reference Browser

Web version of `hgm at lookup`. Standalone page, also embedded as tooltips throughout the dashboard.

```
┌────────────────────────────────────────────────────────────────────────────────┐
│  AT Command Reference                                  [search...] [+ contrib] │
├────────────────────────────────────────────────────────────────────────────────┤
│                                                                                │
│  Tabs:  [Browse]  [Decode]  [Cheat sheets]                                     │
│                                                                                │
│  Decode a response line                                                        │
│  ┌──────────────────────────────────────────────────────────────────────────┐ │
│  │  +CGPADDR: 1,"100.66.18.214"                                             │ │
│  └──────────────────────────────────────────────────────────────────────────┘ │
│                                                              [Decode]          │
│                                                                                │
│  Result                                                                        │
│  ┌──────────────────────────────────────────────────────────────────────────┐ │
│  │  PDP context 1 is active and has been allocated IP 100.66.18.214.        │ │
│  │  This IP is in the carrier-grade NAT range (100.64.0.0/10) — normal     │ │
│  │  for Hologram cellular sessions. The device is NOT directly addressable  │ │
│  │  from the internet; inbound traffic must use Spacebridge or webhooks.    │ │
│  └──────────────────────────────────────────────────────────────────────────┘ │
│                                                                                │
│  Related commands                                                              │
│  • AT+CGACT  Activate or deactivate a PDP context                              │
│  • AT+CGDCONT  Define or query PDP contexts (APN configuration)                │
└────────────────────────────────────────────────────────────────────────────────┘
```

**Cheat sheets** are pre-built decision trees: "Modem won't connect" → flowchart of which AT commands to run in what order, with expected good vs bad responses inline. Designed to be the page a new SE has open during their first 30 days.

**CLI reuse:** the entire `at_reference` module — same dataset for both surfaces.

### 7. Conductor Console

The Hologram-specific feature most worth building, given Conductor just launched. Visualises eUICC profiles and policies for fleets of Hyper SIMs.

```
┌────────────────────────────────────────────────────────────────────────────────┐
│  Conductor   ─   FleetCo   ─   245 Hyper SIMs                                  │
├────────────────────────────────────────────────────────────────────────────────┤
│                                                                                │
│  Profile distribution                                                          │
│  ┌──────────────────────────────────────────────────────────────────────────┐ │
│  │   EU-Multi      ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ 198 SIMs                              │ │
│  │   US-Multi      ▓▓▓▓▓▓ 41 SIMs                                          │ │
│  │   Global-FB      ▓ 6 SIMs (failover-active)                             │ │
│  └──────────────────────────────────────────────────────────────────────────┘ │
│                                                                                │
│  Active failover policies  [3]                                                 │
│  ┌──────────────────────────────────────────────────────────────────────────┐ │
│  │  P1: Auto-fallback after 5 min unregistered                              │ │
│  │      Scope: tag:fleet:trucks                                             │ │
│  │      Triggered: 14 times this week                                       │ │
│  │      [edit] [disable] [view audit]                                       │ │
│  │                                                                          │ │
│  │  P2: Switch to US-Multi when device reports US country code              │ │
│  │      Scope: all SIMs                                                     │ │
│  │      Triggered: 23 times this week                                       │ │
│  │      [edit] [disable] [view audit]                                       │ │
│  └──────────────────────────────────────────────────────────────────────────┘ │
│                                                                                │
│  Recent profile switches                                                       │
│  ┌──────────────────────────────────────────────────────────────────────────┐ │
│  │  ICCID         Old → New              Trigger          When             │ │
│  │  893810...070  EU-Multi → Global-FB   policy P1        2 min ago        │ │
│  │  893810...071  EU-Multi → Global-FB   policy P1        4 min ago        │ │
│  │  893810...074  US-Multi → EU-Multi    policy P2        12 min ago       │ │
│  └──────────────────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────────────┘
```

**Features:**

- **Profile distribution chart** — at-a-glance "what's deployed where."
- **Policy editor** with form-based authoring (no JSON wrangling). Test a policy in dry-run mode before enabling.
- **Switch audit log** — every profile change is recorded, viewable per-SIM and per-policy.
- **Manual override** — for any single SIM, force a profile switch with a confirmation dialog.

This is also where the dashboard *itself* becomes a Conductor extension. If the Hologram team builds a Conductor partner ecosystem, `hgm-web` is plausibly the first community visualisation tool.

### 8. Onboarding Wizard

Step-by-step guided flow for activating a batch of new SIMs. The kind of thing a customer or a junior SE walks through linearly.

Steps:

1. **Upload ICCID list** — CSV, paste, or claim by activation code.
2. **Choose plan + region** — with tooltips explaining the tradeoffs.
3. **Tag for organisation** — ("fleet-trucks-q2-2026") for later filtering.
4. **Review** — summary of what's about to happen + estimated cost.
5. **Activate** — bulk activation with a progress bar.
6. **Verify first attach** — wait for first session within 30 min, surface failures inline with diagnosis.

Step 6 is the integration point with the rest of the dashboard: any SIM that doesn't attach in the expected window auto-routes through the analyzer and the customer/SE sees the diagnosis without having to open another page.

### 9. Bulk Operations Console

For SEs running fleet-wide changes. The operational counterpart to `hgm sims activate --csv`.

- Multi-select from any SIM table.
- Apply: pause, resume, change plan, add tag, remove tag, delete (with hard confirmation).
- Dry-run preview shows what will change before commit.
- Operations are queued; progress shown live; failures listed with retry option.
- Every bulk op is one row in the audit log, expandable to show per-SIM result.

**Built-in safety:** any bulk op affecting >10% of an org's SIMs requires a second SE's confirmation.

### 10. Customer Self-Service Portal (later)

A scoped subset of the dashboard, exposed to customers themselves. Conservative but high-leverage:

- **Triage workbench** — paste your AT log, see what we see. (No customer-context lookups; no cross-customer data.)
- **Their org overview** — their SIMs only, with health and anomaly callouts.
- **Read-only ticket history.**
- **Plan / billing summary.**

Not in v1. But the architecture should be designed so this is a permissions question, not a rebuild.

## Cross-cutting concerns

### Authentication & permissions

- SSO (Google / Okta) for SE staff.
- Role-based access:
  - **SE I**: read all org data, write to triage sessions, codex contributions.
  - **SE II / lead**: above + bulk operations + policy authoring.
  - **Manager / CSM**: read-only fleet-wide.
  - **Admin**: above + user management.
- Per-customer scoping for the eventual customer portal.

### Real-time updates

Server-sent events (SSE) over the FastAPI shell:

- Triage Workbench: live update as the diagnosis runs (especially valuable if the analyzer evolves to do longer-running analysis like reaching across the codex during diagnosis).
- SIM Detail: state changes broadcast in real-time.
- Conductor Console: profile-switch events stream in.

### Integrations

| Integration | Purpose |
|---|---|
| **Zendesk / Salesforce / Intercom** | Push diagnosis to ticket; pull customer messages. |
| **Slack** | DM + channel notifications: ticket assigned, SLA breach, anomaly detected. |
| **PagerDuty** | Severity-1 anomalies (mass disconnect, registration spike) page on-call. |
| **GitHub / Linear** | "Save bug" from a triage session creates a structured engineering issue. |
| **Hologram public API** | The actual data source for live SIM/usage queries. |

### Mobile

A read-only mobile view (or PWA) for the SE on call:

- View open tickets.
- View any SIM detail.
- Receive push notifications for assigned tickets.
- *Cannot* execute actions (pause/resume/etc) from mobile — too easy to fat-finger a bulk op on a tiny screen.

### Search

A single global search bar (Cmd-K) that resolves any of:

- ICCID / IMEI / device ID / SIM name → SIM detail.
- Org name / org ID → Org overview.
- Ticket ref → Triage workbench preloaded with the ticket.
- AT command name → AT reference browser.
- Free text → codex search.

## Implementation phases

### Phase 1 — Personal MVP (week 1–2)

- FastAPI shell with three endpoints: `POST /triage`, `GET /sim/{id}`, `GET /at/lookup`.
- React app with two pages: Triage Workbench, SIM Detail.
- SQLite-backed `triage_sessions` table.
- Single-user, no auth.
- Mock-only data unless `HOLOGRAM_API_KEY` is set.

**Demoable.** Could ship this in a Hologram interview round as "here's what I built on top of the CLI."

### Phase 2 — Multi-org browsing (week 3–4)

- Real Hologram API integration with API key.
- Org Overview page + global search.
- Audit log endpoints + UI.
- Codex contribution flow (manual writes only — no auto-detection yet).

### Phase 3 — Compounding layer (month 2)

- Pattern-detection cron.
- Auto-suggest similar codex entries during triage.
- Fleet Health page.
- Postgres migration (from SQLite).

### Phase 4 — Operational features (month 3)

- Bulk ops console.
- Onboarding wizard.
- Conductor console.
- SSO + role-based permissions.
- Slack integration.

### Phase 5 — Customer-facing (month 4+)

- Customer self-service portal.
- Public-API rate limiting and per-customer scoping.
- White-label theming.

## Tech stack recommendation

| Layer | Choice | Why |
|---|---|---|
| Backend | FastAPI | Native async; pydantic for shared types; near-zero glue to the CLI. |
| Frontend | React + TypeScript + Vite | Standard, hireable, fast dev cycle. |
| UI library | Mantine or shadcn/ui | Strong default tables, forms, modals. |
| State | TanStack Query | Server-state caching matches the API-heavy nature of the app. |
| Database | Postgres (SQLite for dev) | JSONB indexing for the diagnosis blobs in audit log. |
| Auth | Auth.js + SSO | Skip rolling your own. |
| Hosting | Fly.io or Railway initially | Single Postgres + single backend + static frontend = ~$30/mo. |

## Open questions

1. **Where does the dashboard live operationally?** Internal Hologram tool, or open-source community project? Different design constraints. (My instinct: build internal first, open-source the codex schema later as a community contribution.)
2. **Is the customer portal a priority or a stretch goal?** It's the highest-impact long-term but the highest design risk. Reasonable to defer.
3. **Conductor API access.** What we can build into the Conductor Console depends on what the Conductor API exposes. Worth scoping with the product team early.
4. **Audit retention policy.** AT logs may contain ICCIDs and IMEIs (PII). What's the retention window? GDPR implications?
5. **Real-time vs. polled.** Some integrations (live profile-switch events) need streaming infrastructure. Worth introducing in Phase 3 or wait for explicit demand?

## What I'd build first if forced to pick one page

The **Triage Workbench**. It's the page that turns the CLI's analytical work into a visible product. It demos in 30 seconds. It writes the first audit-log rows that seed the codex. And every other page in this proposal references it (links into it from SIM Detail, the Org Overview's anomaly callouts, the Fleet Health stats).

If the Workbench is a hit, the other pages become "natural extensions." If it's not, the rest of this proposal is moot.
