"""Fixture data used in mock mode.

Models a small org with SIMs in every interesting state so commands can be
demoed and tested without API access. Real Hologram payloads are more
verbose; we keep just the fields the commands and the state oracle reason
over.
"""
from __future__ import annotations

import time

NOW = int(time.time())


def _t(seconds_ago: int) -> int:
    return NOW - seconds_ago


MOCK_SIMS: dict[str, dict] = {
    "8938100000123450010": {
        "iccid": "8938100000123450010",
        "state": "LIVE",
        "status": "Connected",
        "deviceid": 1001,
        "linkid": 2001,
        "name": "fleet-truck-east-12",
        "tags": ["fleet:trucks", "region:us-east"],
        "imei": "350201234567001",
        "modem": "Quectel BG96",
        "plan": {"id": 73, "name": "Hologram Global 100MB", "limit_mb": 100},
        "current_period": {"used_mb": 47.2, "billing_start_ts": _t(86400 * 12)},
        "last_session": {
            "ts": _t(900),
            "country": "US",
            "operator": "AT&T",
            "rat": "CAT-M1",
            "rsrp": -88,
            "bytes": 18432,
        },
        "state_history": [
            {"ts": _t(86400 * 30), "state": "INACTIVE"},
            {"ts": _t(86400 * 30 - 600), "state": "TEST-ACTIVATE"},
            {"ts": _t(86400 * 30 - 7200), "state": "LIVE-PENDING"},
            {"ts": _t(86400 * 30 - 7800), "state": "LIVE"},
        ],
    },
    "8938100000123450020": {
        "iccid": "8938100000123450020",
        "state": "LIVE-PENDING",
        "status": "Pending",
        "deviceid": 1002,
        "linkid": 2002,
        "name": "new-deployment-pilot",
        "tags": ["pilot"],
        "imei": None,
        "modem": None,
        "plan": {"id": 73, "name": "Hologram Global 100MB", "limit_mb": 100},
        "current_period": {"used_mb": 0, "billing_start_ts": _t(420)},
        "last_session": None,
        "state_history": [
            {"ts": _t(420), "state": "INACTIVE"},
            {"ts": _t(420), "state": "LIVE-PENDING"},
        ],
    },
    "8938100000123450030": {
        "iccid": "8938100000123450030",
        "state": "PAUSED-SYS",
        "status": "Paused by system",
        "deviceid": 1003,
        "linkid": 2003,
        "name": "warehouse-sensor-04",
        "tags": ["warehouse"],
        "imei": "350201234567003",
        "modem": "u-blox SARA-R412M",
        "plan": {"id": 71, "name": "Hologram Global 10MB", "limit_mb": 10},
        "current_period": {"used_mb": 12.4, "billing_start_ts": _t(86400 * 9)},
        "last_session": {
            "ts": _t(86400),
            "country": "US",
            "operator": "T-Mobile",
            "rat": "CAT-M1",
            "rsrp": -101,
            "bytes": 1024,
        },
        "pause_reason_hint": "data_cap_exceeded",
        "state_history": [
            {"ts": _t(86400 * 60), "state": "LIVE"},
            {"ts": _t(3600 * 6), "state": "PAUSE-PENDING-SYS"},
            {"ts": _t(3600 * 5), "state": "PAUSED-SYS"},
        ],
    },
    "8938100000123450040": {
        "iccid": "8938100000123450040",
        "state": "PAUSED-USER",
        "status": "Paused by user",
        "deviceid": 1004,
        "linkid": 2004,
        "name": "decom-pending-asset-7",
        "tags": ["decom"],
        "imei": "350201234567004",
        "modem": "Quectel BG95-M3",
        "plan": {"id": 73, "name": "Hologram Global 100MB", "limit_mb": 100},
        "current_period": {"used_mb": 3.1, "billing_start_ts": _t(86400 * 4)},
        "last_session": {
            "ts": _t(86400 * 3),
            "country": "US",
            "operator": "AT&T",
            "rat": "CAT-M1",
            "rsrp": -90,
            "bytes": 2048,
        },
        "state_history": [
            {"ts": _t(86400 * 60), "state": "LIVE"},
            {"ts": _t(86400 * 3), "state": "PAUSE-PENDING-USER"},
            {"ts": _t(86400 * 3 - 60), "state": "PAUSED-USER"},
        ],
    },
    "8938100000123450050": {
        "iccid": "8938100000123450050",
        "state": "TEST-ACTIVATE",
        "status": "In testing",
        "deviceid": 1005,
        "linkid": 2005,
        "name": "qa-bench-unit-3",
        "tags": ["qa"],
        "imei": "350201234567005",
        "modem": "Quectel BG96",
        "plan": None,
        "current_period": {"used_mb": 0.082, "billing_start_ts": _t(3600)},
        "last_session": {
            "ts": _t(120),
            "country": "US",
            "operator": "AT&T",
            "rat": "CAT-M1",
            "rsrp": -85,
            "bytes": 84000,
        },
        "state_history": [
            {"ts": _t(3600), "state": "INACTIVE"},
            {"ts": _t(3600 - 60), "state": "TEST-ACTIVATE-PENDING"},
            {"ts": _t(3600 - 660), "state": "TEST-ACTIVATE"},
        ],
    },
    "8938100000123450060": {
        "iccid": "8938100000123450060",
        "state": "DEAD",
        "status": "Deactivated",
        "deviceid": 1006,
        "linkid": 2006,
        "name": "decom-vehicle-22",
        "tags": ["decom", "archived"],
        "imei": "350201234567006",
        "modem": "u-blox SARA-R5",
        "plan": None,
        "current_period": None,
        "last_session": {
            "ts": _t(86400 * 90),
            "country": "US",
            "operator": "Verizon",
            "rat": "CAT-M1",
            "rsrp": -94,
            "bytes": 5120,
        },
        "state_history": [
            {"ts": _t(86400 * 200), "state": "LIVE"},
            {"ts": _t(86400 * 90), "state": "DEAD-PENDING"},
            {"ts": _t(86400 * 90 - 300), "state": "DEAD"},
        ],
    },
    "8938100000123450070": {
        "iccid": "8938100000123450070",
        "state": "LIVE",
        "status": "Connected",
        "deviceid": 1007,
        "linkid": 2007,
        "name": "eu-pilot-meter-01",
        "tags": ["pilot", "region:eu", "hyper-sim"],
        "imei": "350201234567007",
        "modem": "Quectel BG770A",
        "plan": {"id": 75, "name": "Hologram Global EU+US 50MB", "limit_mb": 50},
        "current_period": {"used_mb": 22.1, "billing_start_ts": _t(86400 * 7)},
        "last_session": {
            "ts": _t(1800),
            "country": "DE",
            "operator": "Vodafone DE",
            "rat": "CAT-M1",
            "rsrp": -89,
            "bytes": 9216,
        },
        "euicc_profiles": [
            {"index": 1, "iccid": "8938100000123450070", "active": True, "carrier": "EU-Multi"},
            {"index": 2, "iccid": "8938100000123450170", "active": False, "carrier": "Global-Fallback"},
        ],
        "state_history": [
            {"ts": _t(86400 * 14), "state": "LIVE"},
        ],
    },
}


def list_sims() -> list[dict]:
    return list(MOCK_SIMS.values())


def get_sim(identifier: str) -> dict | None:
    if identifier in MOCK_SIMS:
        return MOCK_SIMS[identifier]
    for sim in MOCK_SIMS.values():
        if sim.get("imei") == identifier:
            return sim
        if str(sim.get("deviceid")) == identifier:
            return sim
        if sim.get("name") == identifier:
            return sim
    return None
