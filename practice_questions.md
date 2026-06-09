# Hologram SE I — Interview Prep Practice Set

A self-study workbook of 30 questions modeled on the format of the take-home (`assignment.txt`). Mixed across modem/connectivity debugging, SQL reasoning, API troubleshooting, and Python tasks, with two cross-domain "real ticket" scenarios at the end.

**Format:** short-answer. Pseudocode is fine where it makes sense. The goal is reasoning, not perfection.

**Suggested approach:**
- Tackle a section at a time rather than all at once.
- Try to answer without consulting docs first; *then* check docs and revise. Time yourself loosely (aim 3–8 min per question).
- Write your answers under each `**Your answer:**` heading. Send back when ready and I'll review.

---

## Section A — Modem & Connectivity Debugging (8 questions)

### A1. CREG status code recall

For each of the following `+CREG`/`+CEREG`/`+CGREG` status values (the second number in the response), explain what it means and what the SE should consider doing:

- `0`
- `1`
- `2`
- `3`
- `4`
- `5`
- `8`

**Your answer:**

---

### A2. Decode this log

A customer ships you the following AT capture from a Quectel BG96 in the US:

```
AT+CPIN?
+CPIN: READY
OK
AT+CSQ
+CSQ: 19,99
OK
AT+CGDCONT=1,"IP","hologram"
OK
AT+CEREG?
+CEREG: 0,1
OK
AT+CGATT?
+CGATT: 1
OK
AT+CGACT=1,1
OK
AT+CGPADDR=1
+CGPADDR: 1,"100.66.18.214"
OK
AT+QIOPEN=1,0,"TCP","example.com",443,0,1
+QIOPEN: 0,566
```

(a) What is happening end-to-end up to the last command?
(b) What does the `+QIOPEN: 0,566` response indicate (you'll need to research Quectel's QIOPEN error codes — code 566 is "DNS parse failed")?
(c) Where in the stack does the failure live, and what's your top hypothesis?
(d) What's the next thing you'd ask the customer?

**Your answer:**

---

### A3. Distinguishing three "won't connect" patterns

Three different customers each report "device won't connect." Their AT logs show, respectively:

- **Customer 1:** `+CPIN: READY`, `+CSQ: 22,99`, `+CEREG: 0,3`, no other errors.
- **Customer 2:** `+CPIN: READY`, `+CSQ: 99,99`, `+CEREG: 0,2` (stuck), `+COPS=?` returns no networks.
- **Customer 3:** `+CPIN: READY`, `+CSQ: 18,99`, `+CEREG: 0,1`, `+CGATT: 1`, `+CGACT=1,1` returns ERROR.

For each, identify (a) the most likely failure layer (RF / SIM / network-auth / APN / data-plane), (b) the most likely root cause, and (c) what *one* additional piece of information from the customer would most efficiently confirm or rule out your hypothesis.

**Your answer:**

---

### A4. PDP cause codes

Match each of these 3GPP SM/EMM cause codes to the most likely real-world meaning *and* one thing you'd ask the customer to verify:

- Cause 7: GPRS services not allowed
- Cause 8: GPRS services and non-GPRS services not allowed
- Cause 13: Roaming not allowed in this tracking area
- Cause 33: Requested service option not subscribed
- Cause 41: Semantic error in the TFT operation

**Your answer:**

---

### A5. PSM design tradeoffs

A customer is building a battery-powered asset tracker that pings home with GPS coordinates every 15 minutes and accepts on-demand "where are you" downlink commands from a backend. They've enabled PSM (Power Saving Mode) with `T3324 = 30s`, `T3412 = 1h` and are reporting that:

- Battery life looks great.
- The 15-minute pings work.
- The "where are you" downlinks fail roughly 90% of the time.

(a) What's the conflict between the customer's PSM config and their requirements?
(b) What two configuration changes would you propose, and what tradeoffs does each create?
(c) Is eDRX (Extended Discontinuous Reception) part of the answer here? Why or why not?

**Your answer:**

---

### A6. Reasoning about eUICC

A customer has 200 Hologram Hyper SIMs deployed across the EU. Each SIM has two profiles installed: a primary EU-region profile (active on all 200) and a global-fallback profile (provisioned but inactive). Last night, 17 devices stopped reporting. Logs from a sample show the active profile is stuck at `+CEREG: 0,2` and `+CSQ: 99,99`, while the fallback profile is healthy on a working device nearby.

(a) What's the most likely root cause of the 17-device outage?
(b) Why didn't the fallback profile activate automatically on the affected devices?
(c) What two short-term and two long-term actions would you propose?
(d) Where does Conductor fit into the long-term plan?

**Your answer:**

---

### A7. Power vs. config triage

A customer reports that their device "boots fine, runs AT commands fine for about 30 seconds, then becomes unresponsive and we have to power-cycle." After the power-cycle, the same pattern repeats. Their log captures look healthy up to the point the modem goes quiet — there's no error, just no further response.

What's your top hypothesis, and what specific test would you ask the customer to run to confirm or rule it out without sending the device to a hardware lab?

**Your answer:**

---

### A8. Multi-symptom log

```
AT+CPIN?
+CPIN: READY
OK
AT+QCSQ
+QCSQ: "CAT-M1",-112,-118,80,-15
OK
AT+CEREG?
+CEREG: 0,1
OK
AT+CGATT?
+CGATT: 1
OK
AT+CGACT=1,1
OK
AT+CGPADDR=1
+CGPADDR: 1,"100.64.10.55"
OK
AT+QPING=1,"8.8.8.8",1,4
OK
+QPING: 0,"8.8.8.8",32,890,255
+QPING: 569,"8.8.8.8",32,0,0
+QPING: 0,"8.8.8.8",32,1240,255
+QPING: 569,"8.8.8.8",32,0,0
+QPING: 0,2,4,2,890,1240,1065
```

(a) The session shows attach succeeding, but pings are losing 50% of packets with very high latency on the ones that succeed. What's the most likely cause?
(b) Is this a Hologram-side issue, a customer-side issue, or ambiguous? Defend your answer.
(c) What's the customer-facing reply you'd send?

**Your answer:**

---

## Section B — SQL Reasoning (7 questions)

Use the schema from the take-home, with two additional tables added for these questions:

```
devices(device_id, org_id, status)             -- status: active | inactive | test
usage(device_id, date, mb_used)
links(device_id, iccid, imei)

state_changes(device_id, ts, old_state, new_state)   -- ts is a timestamp
sessions(device_id, session_start, session_end, country, operator, rat, bytes)
```

### B1. Activated SIMs that have never connected

Write a query that returns all `active` devices that have **no usage record at all** (not just zero usage, but no row in `usage` for any date). This is the "we activated 50 SIMs but only 47 ever phoned home" question.

**Your answer:**

SELECT d.device_id FROM devices as d
JOIN usage as u
ON d.device_id = u.device_id
WHERE u.device_id NOT IN (SELECT device_id FROM usage WHERE mb_used > 0 AND mb_used IS NOT NULL)
AND d.status = "active";

---

### B2. Top 10 orgs by usage

Return the top 10 orgs by total MB used in the last 30 days, with columns: `org_id`, `total_mb`, `active_device_count`. Sort descending by `total_mb`.

**Your answer:**

SELECT d.org_id, SUM(du.used) as total_mb, COUNT(du.device_id) as active_device_count FROM devices as d
JOIN (SELECT device_id, SUM(mb_used) as used FROM usage
  WHERE date >= (CURDATE() - INTERVAL 1 MONTH )
  GROUP by device_id) as du
ON d.device_id = du.device_id
WHERE d.status = "active"
GROUP BY d.org_id
ORDER BY d.total_mb DESC LIMIT 10;

---

### B3. Month-over-month spike

Return all devices whose total MB usage in the **most recent full calendar month** is at least 2× their total in the **prior calendar month** AND who used at least 50 MB in the recent month (so we don't flag devices whose usage went from 0.1 MB to 0.3 MB).

Columns: `device_id`, `org_id`, `prior_mb`, `recent_mb`, `multiplier`. Sort by `multiplier` descending.

**Your answer:**

---

### B4. Stuck in TEST-ACTIVATE

Using the `state_changes` table, return all devices whose **current state** is `TEST-ACTIVATE` (per the most recent row in `state_changes`) AND who entered that state more than 24 hours ago.

**Your answer:**

---

### B5. Daily usage rollup by RAT

Using the `sessions` table, return total bytes per day per RAT for the last 7 days. Columns: `date`, `rat`, `total_bytes`. Treat session start time as the day-bucket.

**Your answer:**

---

### B6. NULL trap

Consider the following query, which a teammate wrote to find devices in orgs that don't have a configured `default_plan_id`:

```sql
SELECT d.device_id
FROM devices d
LEFT JOIN orgs o ON d.org_id = o.org_id
WHERE o.default_plan_id != 12345;
```

(a) What's the bug in this query? (Consider: what does NULL `default_plan_id` do to the comparison?)
(b) Rewrite the query so it correctly returns devices in orgs whose `default_plan_id` is anything other than `12345` (including orgs with no configured plan).

**Your answer:**

---

### B7. Cross-border roaming detection

Return all devices that had sessions in **at least 2 distinct countries** in the last 7 days, along with the count of distinct countries. This is the "did any of our supposedly-domestic-only devices end up roaming?" check.

**Your answer:**

---

## Section C — API Troubleshooting & Design (7 questions)

### C1. Auth header construction

A junior engineer writes the following code to call the Hologram API:

```python
import requests
resp = requests.get(
    "https://dashboard.hologram.io/api/1/devices/",
    headers={"Authorization": f"Bearer {API_KEY}"},
    params={"orgid": ORG_ID},
)
```

The request returns a 401. Explain why, and rewrite the call correctly using either `requests.auth.HTTPBasicAuth` or a manually constructed header. (Hint: the Hologram API uses HTTP Basic auth, not Bearer tokens. The username is fixed.)

**Your answer:**

---

### C2. Partial failure in a bulk activation

A customer runs a bulk activation of 1,000 SIMs via `POST /links/cellular/bulkclaim`. The response comes back as:

```json
{
  "success": true,
  "data": {
    "claimed": 987,
    "failed": 13,
    "errors": [
      {"sim": "8938100000123450101", "reason": "already_claimed"},
      {"sim": "8938100000123450102", "reason": "invalid_iccid"},
      ...
    ]
  }
}
```

(a) Was the request successful or unsuccessful? Defend your answer.
(b) What would you tell the customer to do about the 13 failures?
(c) What's wrong with simply retrying the whole batch? Propose a better retry strategy.

**Your answer:**

---

### C3. Pagination

The Hologram REST API paginates list responses with `limit` and `offset` parameters and returns a `continues: true|false` flag plus a `data` array per page. Write **pseudocode** for a function `list_all_sims(orgid)` that returns every SIM in the org, handling pagination correctly. Bonus: handle the case where `continues` is true but `data` is empty (don't infinite-loop).

**Your answer:**

---

### C4. Retry-after-429

The API returns HTTP 429 when you exceed rate limits. Write pseudocode (or real code) for a `request_with_backoff(method, url, ...)` helper that:

- Retries on 429 responses.
- Uses exponential backoff (start at 1s, double each retry).
- Caps at 4 retries total.
- Respects a `Retry-After` header if present (use that value instead of the computed backoff).
- Raises after exhausting retries.

**Your answer:**

---

### C5. Webhook signature verification

You're designing the receiver side of an incoming webhook from a partner system that posts to an internal endpoint Hologram exposes. The partner signs each request with HMAC-SHA256 over the raw body, using a shared secret, and sends the signature in `X-Partner-Signature: sha256=<hex>`.

Write a Python function `verify_signature(raw_body: bytes, header: str, secret: str) -> bool` that returns True if and only if the signature is valid. Important: explain *why* you used your specific comparison method rather than `==`.

**Your answer:**

---

### C6. Designing an idempotency key

A customer is automating SIM activations from their inventory management system. Their system retries failed activation calls automatically, but they're seeing some SIMs activated twice (which double-bills). The Hologram activation endpoint doesn't currently support idempotency keys.

(a) Why are duplicate activations happening despite the customer thinking each SIM only gets activated once?
(b) Design (in plain language) an idempotency-key scheme the customer could implement *on their side* without API changes. What header/field would you use, what would the value be, and how does the client decide it's safe to retry?
(c) If you could change the API itself, what would you propose?

**Your answer:**

---

### C7. Conductor-style profile switch API

You're designing a new API endpoint to trigger a profile switch on a Hologram Hyper SIM. Sketch the request shape (URL, method, headers, body), the immediate response, and the eventual completion semantics (synchronous? async? webhook?). Justify each choice in 1–2 sentences.

**Your answer:**

---

## Section D — Python Tasks (6 questions)

### D1. First successful event by type

Given JSON of the same shape as in the take-home, write a Python function `first_success_by_type(events: list[dict]) -> dict[str, str]` that returns a dict mapping each event `type` to the timestamp of its **first** successful event (`result == "success"`). Types with no successful event should not appear in the output.

**Your answer:**

---

### D2. Group sessions by device

Given a list of session dicts:

```python
sessions = [
    {"device_id": 1001, "ts": 1730000000, "country": "US", "bytes": 1024},
    {"device_id": 1001, "ts": 1730003600, "country": "US", "bytes": 2048},
    {"device_id": 1002, "ts": 1730007200, "country": "DE", "bytes": 4096},
    ...
]
```

Return a dict mapping `device_id` to a list of sessions sorted by timestamp ascending.

**Your answer:**

---

### D3. Compute uptime ratio from events

Given a list of state-change events for a single device:

```python
events = [
    {"ts": 1730000000, "state": "online"},
    {"ts": 1730003600, "state": "offline"},
    {"ts": 1730005400, "state": "online"},
    {"ts": 1730009000, "state": "offline"},
]
```

Write `uptime_ratio(events: list[dict], window_start: int, window_end: int) -> float` that returns the fraction of the time window during which the device was `online`. Assume events are sorted by `ts`. The device's state at `window_start` is whatever the most recent event before `window_start` set it to (or `offline` if none exist).

**Your answer:**

---

### D4. ICCID validation

ICCIDs are 19- or 20-digit numbers ending in a Luhn-algorithm check digit. Write `is_valid_iccid(iccid: str) -> bool` that returns True iff:

- The string is all digits.
- Its length is 19 or 20.
- The Luhn check digit (the last digit) is correct given the preceding digits.

Bonus: write a test or two demonstrating it works on at least one valid and one invalid ICCID.

**Your answer:**

---

### D5. AT log line to dict

Write `parse_at_response_line(line: str) -> dict | None` that, given a single line of an AT response (e.g. `+CEREG: 0,1` or `+CSQ: 21,99` or `+COPS: 0,0,"AT&T",8`), returns a dict like:

```python
{"command": "CEREG", "fields": [0, 1]}
{"command": "CSQ",   "fields": [21, 99]}
{"command": "COPS",  "fields": [0, 0, "AT&T", 8]}
```

Return `None` for lines that aren't AT responses (e.g. `OK`, `ERROR`, blank). Type-coerce numeric fields to `int`, leave quoted strings as `str` (without quotes).

**Your answer:**

---

### D6. Concurrent fan-out with rate limit

You need to fetch the current state of 500 SIMs from the Hologram API. The API rate limit is 10 requests per second per API key. Write Python (using `asyncio` and `httpx`, or any other reasonable approach) that fetches all 500 efficiently while respecting the rate limit. Pseudocode is fine if you can clearly express the concurrency control.

**Your answer:**

---

## Cross-domain Scenarios (2 questions)

### CD1. Full ticket triage

A customer (let's call them "FleetCo") opens a ticket:

> *"We have 50 trackers deployed in pickup trucks across Texas. As of yesterday afternoon, 8 of them stopped reporting. The other 42 are fine. We've checked the fleet management dashboard and the affected trucks are physically present and powered on. The drivers say nothing has changed. What's wrong with your network?"*

Write the **triage runbook** you'd execute, in order, from the moment this ticket lands in your queue to the moment you respond to the customer. Be specific about:

- What data you'd pull and where from (Hologram dashboard, API, customer-supplied logs).
- Hypotheses you'd rule in or out at each step.
- Stop conditions: at what point would you reply to the customer with "this is your problem" vs. "this is our problem" vs. "I need more from you"?
- A draft reply at the end (assume root cause is "network outage at the regional carrier affecting LTE-M coverage in part of east Texas, currently active for ~6 hours, ETA unknown").

**Your answer:**

---

### CD2. Tooling proposal for a scaling customer

A mid-size customer is growing from 500 SIMs to a planned 10,000 over the next 12 months. They've told their account manager they're "concerned about visibility and management overhead at that scale." The AM has asked you (the SE) to put together a 1-page recommendation for the customer, focused on **what they should automate or instrument now, before they hit 10K SIMs**, so the growth doesn't break their ops.

Outline (bullet-point form is fine):
- The top 3–5 things they should set up before scaling.
- Which of those the customer should build vs. which Hologram features they should adopt.
- One thing you'd explicitly tell them *not* to spend time on yet.

**Your answer:**

---

## Reflection prompts (optional, for your own use)

After working through the set:

- Which section felt slowest? (That's where to dig in deeper before interview rounds.)
- Which question did you guess on and want to verify? (Flag those for the review.)
- Were any questions ambiguous in a way that would matter in a real customer conversation?

When you're ready, send the file back filled in and I'll review section-by-section, flag anything that's wrong, and offer alternative phrasings for the customer-facing replies.
