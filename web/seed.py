"""One-shot seed for codex entries, conductor policies, and recent switches.

Idempotent — run on startup; only inserts if tables are empty.
"""
from __future__ import annotations

import time

from web import db


SEED_CODEX = [
    {
        "title": "Quectel BG95 + Verizon: SIM lock on first attach",
        "vendor": "quectel",
        "module": "BG95-M3",
        "carrier": "Verizon",
        "rat": "cat-m1",
        "symptom_tags": ["registration_denied_hss", "creg-0-3", "cause-7"],
        "diagnosis": (
            "Verizon requires explicit IMEI-to-ICCID linking on the carrier "
            "dashboard before allowing attach. Without that binding, +CREG: 0,3 "
            "with EMM cause 7 ('EPS services not allowed') fires repeatedly."
        ),
        "fix": (
            "Customer / SE submits ICCID + IMEI to the carrier's MDN binding "
            "form. Wait ~2 hrs for propagation. Power-cycle the device, "
            "verify with AT+CEREG?."
        ),
        "ticket_refs": ["#4109", "#4221", "#4287"],
    },
    {
        "title": "SIMCom SIM7080G boots into NB-IoT only on factory firmware",
        "vendor": "simcom",
        "module": "SIM7080G",
        "carrier": "AT&T",
        "rat": "nb-iot",
        "symptom_tags": ["searching_no_register", "creg-0-2"],
        "diagnosis": (
            "Some 1529B07 firmware revisions of the SIM7080G ship with CMNB=2 "
            "(NB-IoT only) by default. In US AT&T deployments where Cat-M is "
            "available but NB-IoT is patchy, this causes silent 'searching forever'."
        ),
        "fix": (
            "Set CMNB to 3 (Cat-M + NB-IoT preferred) and persist:\n"
            "  AT+CMNB=3\n  AT&W\n  AT+CFUN=1,1   # restart radio"
        ),
        "ticket_refs": ["#3984"],
    },
    {
        "title": "Hyper SIM in EU stuck on US-Multi profile during pre-deployment testing",
        "vendor": "quectel",
        "module": "BG770A",
        "carrier": "Vodafone DE",
        "rat": "cat-m1",
        "symptom_tags": ["euicc_wrong_profile", "fallback_didnt_trigger"],
        "diagnosis": (
            "Hyper SIMs ship with US-Multi as the active profile by default. "
            "Devices powered on in the EU for the first time will see no "
            "registration on the active profile and won't auto-switch unless "
            "a Conductor failover policy is in place."
        ),
        "fix": (
            "Either (1) preconfigure profile via Conductor before shipment, "
            "or (2) deploy a 'switch on N failed attaches' Conductor policy "
            "scoped to the affected fleet."
        ),
        "ticket_refs": ["#4421"],
    },
    {
        "title": "Marginal LTE-M signal at warehouse loading docks (RSRP < -115 dBm)",
        "vendor": None,
        "module": None,
        "carrier": None,
        "rat": "cat-m1",
        "symptom_tags": ["marginal_signal"],
        "diagnosis": (
            "Metal-roof loading-dock environments routinely degrade LTE-M "
            "signal below the -115 dBm threshold even when overall building "
            "coverage is fine. Customers see intermittent connectivity."
        ),
        "fix": (
            "External patch antenna mounted on the dock-door frame (NOT on the roof). "
            "Use 50-ohm coax, keep cable run < 3 m. NB-IoT may also be a viable "
            "alternative — better link budget at the cost of throughput."
        ),
    },
    {
        "title": "Quectel EC25 DNS failure on AT&T after firmware update",
        "vendor": "quectel",
        "module": "EC25-G",
        "carrier": "AT&T",
        "rat": "cat-1",
        "symptom_tags": ["dns_failure"],
        "diagnosis": (
            "EC25 firmware EC25GGBR07A11M1G regressed AT&T DNS — the modem "
            "uses carrier-issued DNS but those servers respond intermittently "
            "for some APN profiles. Pings to numeric IPs work fine."
        ),
        "fix": (
            'Override DNS at the modem: AT+QIDNSCFG=1,"8.8.8.8","1.1.1.1"\n'
            "Persist with AT&W if firmware supports it. Long-term: roll back "
            "to A11M1G or upgrade to A12M1G+."
        ),
    },
    {
        "title": "PSM masking real outage: T3324=10s with cron-style data sends",
        "vendor": None,
        "module": None,
        "carrier": None,
        "rat": "cat-m1",
        "symptom_tags": ["psm_aggressive"],
        "diagnosis": (
            "When customer firmware sends data on a cron (e.g. every 5 min) "
            "but T3324 (active timer) is 10s, the modem is in deep sleep "
            "between cycles — 99% of the time. Platform sees the device as "
            "'offline' for long stretches, but it's actually fine."
        ),
        "fix": (
            "Either (1) tune T3324 to match the application's longest expected "
            "downlink response window, or (2) disable PSM (AT+CPSMS=0) and "
            "use eDRX alone for power savings without the always-asleep penalty."
        ),
    },
]


SEED_POLICIES = [
    ("Auto-fallback after 5 min unregistered", "tag:fleet:trucks",
     "switch_to_next_profile if unregistered_seconds > 300"),
    ("Switch to US profile when device reports US country code",
     "all", "switch_to:us-multi if last_session.country == 'US'"),
    ("Cost-aware fallback for EU fleet",
     "tag:region:eu", "switch_to:eu-multi if monthly_overage_pct > 20"),
]


SEED_SWITCHES = [
    ("8938100000123450070", "EU-Multi", "Global-FB", "policy:Auto-fallback after 5 min unregistered"),
    ("8938100000123450071", "EU-Multi", "Global-FB", "policy:Auto-fallback after 5 min unregistered"),
    ("8938100000123450072", "EU-Multi", "Global-FB", "policy:Auto-fallback after 5 min unregistered"),
    ("8938100000123450074", "US-Multi", "EU-Multi", "policy:Switch to US profile when device reports US country code"),
    ("8938100000123450075", "EU-Multi", "Global-FB", "manual:SE override"),
]


def seed_if_empty() -> None:
    """Idempotent. Reads counts, then commits seeds in a single transaction.

    Important: do NOT call other db.* helpers inside an open db.conn() — each
    helper opens its own connection and SQLite serializes writes per file, so
    nested usage will deadlock.
    """
    with db.conn() as c:
        need_codex = c.execute("SELECT COUNT(*) FROM codex_entries").fetchone()[0] == 0
        need_policies = c.execute("SELECT COUNT(*) FROM conductor_policies").fetchone()[0] == 0
        need_switches = c.execute("SELECT COUNT(*) FROM conductor_switches").fetchone()[0] == 0

    if need_codex:
        for entry in SEED_CODEX:
            db.save_codex(**entry)
    if need_policies:
        for name, scope, rule in SEED_POLICIES:
            db.save_policy(name, scope, rule)
        with db.conn() as c:
            c.execute("UPDATE conductor_policies SET triggered_count = 14 WHERE name LIKE 'Auto-fallback%'")
            c.execute("UPDATE conductor_policies SET triggered_count = 23 WHERE name LIKE 'Switch to US%'")
    if need_switches:
        for iccid, old, new, trigger in SEED_SWITCHES:
            db.save_switch(iccid, old, new, trigger)
