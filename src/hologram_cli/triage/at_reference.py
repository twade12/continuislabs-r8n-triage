"""AT command reference data + response decoders.

This module exists so an SE can answer "what does AT+QIOPEN do?" or
"what does +CGPADDR: 1,\"100.66.18.214\" actually mean?" without leaving
the terminal. It powers the `hgm at lookup` subcommand.

Two related but distinct services:

  - **Command reference**: a static catalogue of AT commands keyed by name
    (e.g. "+CEREG", "+QIOPEN") with purpose, syntax, parameters, and example.
    Mostly retrieval — like a man page.

  - **Response decoder**: given a single response/URC line, produce a
    plain-language description. This is the genuinely useful half: a customer
    pastes a log line, the SE pastes it into `hgm at lookup --decode`, and
    out comes the meaning. Decoders are registered per command name and
    consume the parser's existing helpers where possible.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from hologram_cli.triage.parser import (
    parse_cesq,
    parse_cgatt,
    parse_cops,
    parse_cops_scan,
    parse_cpsms,
    parse_creg,
    parse_csq,
    parse_qcsq,
)

ResponseDecoder = Callable[[str], str | None]


@dataclass
class ATCommand:
    name: str  # canonical command name including '+' or '#' prefix; uppercase, no leading "AT"
    vendor: str  # "3gpp" | "quectel" | "ublox" | "simcom" | "telit" | "sierra" | "nordic"
    purpose: str
    syntax: list[str] = field(default_factory=list)
    parameters: dict[str, str] = field(default_factory=dict)
    response_format: str | None = None
    common_errors: dict[str, str] = field(default_factory=dict)
    example: str | None = None
    docs_url: str | None = None


# ---- response decoders --------------------------------------------------

# Status-3 codes for CREG/CGREG/CEREG. The numeric semantics are 3GPP TS 27.007.
_REG_STATUS = {
    0: "not registered, not searching",
    1: "registered, home network",
    2: "not registered, searching",
    3: "registration denied",
    4: "unknown (out of coverage)",
    5: "registered, roaming",
    6: "registered for SMS only, home",
    7: "registered for SMS only, roaming",
    8: "attached for emergency only",
}

_RAT_NAMES = {
    0: "GSM",
    1: "GSM Compact",
    2: "UTRAN",
    3: "GSM w/EGPRS",
    4: "UTRAN w/HSDPA",
    5: "UTRAN w/HSUPA",
    6: "UTRAN w/HSDPA+HSUPA",
    7: "E-UTRAN (LTE)",
    8: "EC-GSM-IoT",
    9: "E-UTRAN (NB-S1)",
}


def _decode_creg_family(family: str) -> ResponseDecoder:
    family_doc = {
        "CREG": "circuit-switched (legacy 2G/3G voice/SMS)",
        "CGREG": "GPRS / packet-switched (2G/3G data)",
        "CEREG": "EPS / LTE",
    }[family]

    def decode(line: str) -> str | None:
        if not line.upper().startswith(f"+{family}:"):
            return None
        v = parse_creg(line)
        if v is None:
            return f"+{family} response, but the format wasn't recognised."
        n, stat = v
        meaning = _REG_STATUS.get(stat, "unknown status code")
        net_unsol = {0: "off", 1: "+CREG: <stat> only", 2: "+CREG: <stat>,<lac>,<ci>"}.get(n, f"mode {n}")
        return (
            f"{family} reports registration status for the {family_doc} domain.\n"
            f"  field 1 (<n>={n}): URC mode = {net_unsol}\n"
            f"  field 2 (<stat>={stat}): {meaning}\n"
            f"  → status {stat} usually means: " + _REG_STATUS_GUIDANCE.get(stat, "see 3GPP TS 27.007")
        )
    return decode


_REG_STATUS_GUIDANCE = {
    0: "device hasn't tried yet, or is unable to. Check power, antenna, SIM.",
    1: "everything fine on the registration side; data attach can proceed.",
    2: "device is actively scanning but not finding a usable cell. Possible RAT/band/SIM issue.",
    3: "the network is rejecting registration. Common causes: SIM activation not yet propagated, account-level issue, carrier-side blocking.",
    4: "unrecoverable from device perspective without intervention; treat as out-of-coverage.",
    5: "registered, but on a visited network (roaming). Check coverage agreement applies.",
}


def _decode_csq(line: str) -> str | None:
    v = parse_csq(line)
    if v is None:
        return None
    rssi, ber = v
    if rssi == 99:
        return "+CSQ: 99,99 — no signal measurement available (modem not registered, or radio off)."
    rssi_dbm = -113 + 2 * rssi  # 0 = -113 dBm, 31 = -51 dBm
    quality = (
        "excellent" if rssi >= 20 else
        "good" if rssi >= 15 else
        "marginal" if rssi >= 10 else
        "poor"
    )
    return (
        f"+CSQ: {rssi},{ber} — RSSI ≈ {rssi_dbm} dBm ({quality}). "
        "BER is reported as 99 by most LTE modules — that field is legacy 2G."
    )


def _decode_cesq(line: str) -> str | None:
    info = parse_cesq(line)
    if info is None:
        return None
    parts = []
    if info["rsrp_dbm"] is not None:
        rsrp = info["rsrp_dbm"]
        rating = (
            "excellent (>= -90 dBm)" if rsrp >= -90 else
            "good (-90 to -100 dBm)" if rsrp >= -100 else
            "fair (-100 to -110 dBm)" if rsrp >= -110 else
            "marginal (-110 to -118 dBm — at LTE-M sensitivity edge)" if rsrp >= -118 else
            "below LTE-M sensitivity"
        )
        parts.append(f"RSRP = {rsrp} dBm — {rating}")
    if info["rsrq_db"] is not None:
        parts.append(f"RSRQ = {info['rsrq_db']:.1f} dB")
    return "+CESQ extended signal quality.\n  " + "\n  ".join(parts) if parts else "+CESQ — all measurements n/a."


def _decode_qcsq(line: str) -> str | None:
    info = parse_qcsq(line)
    if info is None:
        return None
    return (
        f"+QCSQ on {info['rat']}: RSSI {info['rssi']} dBm, RSRP {info['rsrp']} dBm, "
        f"SINR {info['sinr']/10:.1f} dB, RSRQ {info['rsrq']} dB. "
        f"RSRP < -115 dBm sits at LTE-M sensitivity edge."
    )


def _decode_cgpaddr(line: str) -> str | None:
    m = re.match(r'^\+CGPADDR:\s*(?P<cid>\d+),"(?P<ip>[^"]+)"', line)
    if not m:
        return None
    ip = m["ip"]
    is_cgnat = ip.startswith(("100.64.", "100.65.", "100.66.", "100.67.", "100.68.", "100.69.",
                              "100.70.", "100.71.", "100.72.", "100.73.", "100.74.", "100.75.",
                              "100.76.", "100.77.", "100.78.", "100.79.", "100.80.", "100.81.",
                              "100.82.", "100.83.", "100.84.", "100.85.", "100.86.", "100.87.",
                              "100.88.", "100.89.", "100.90.", "100.91.", "100.92.", "100.93.",
                              "100.94.", "100.95.", "100.96.", "100.97.", "100.98.", "100.99.",
                              "100.100.", "100.101.", "100.102.", "100.103.", "100.104.", "100.105.",
                              "100.106.", "100.107.", "100.108.", "100.109.", "100.110.", "100.111.",
                              "100.112.", "100.113.", "100.114.", "100.115.", "100.116.", "100.117.",
                              "100.118.", "100.119.", "100.120.", "100.121.", "100.122.", "100.123.",
                              "100.124.", "100.125.", "100.126.", "100.127."))
    note = ""
    if is_cgnat:
        note = (
            "\n  This IP is in the carrier-grade NAT range (100.64.0.0/10) — normal for "
            "Hologram cellular sessions. The device is NOT directly addressable from the "
            "internet; inbound traffic must use Spacebridge or webhooks."
        )
    return f"PDP context {m['cid']} is active and has been allocated IP {ip}.{note}"


def _decode_cops(line: str) -> str | None:
    if line.startswith("+COPS: ("):
        scan = parse_cops_scan(line)
        if not scan:
            return "+COPS=? returned an empty scan — modem found no usable networks."
        out = ["+COPS=? operator scan results:"]
        stat_label = {0: "unknown", 1: "available", 2: "current", 3: "FORBIDDEN"}
        for entry in scan:
            label = stat_label.get(entry["stat"], f"stat {entry['stat']}")
            rat = _RAT_NAMES.get(entry["act"], f"AcT {entry['act']}")
            out.append(f"  • {entry['long']} ({entry['plmn']}) — {label}, {rat}")
        if any(e["stat"] == 3 for e in scan):
            out.append("\n  At least one PLMN is FORBIDDEN — the network is explicitly rejecting "
                       "this SIM. Usually means the active profile lacks a roaming agreement here.")
        return "\n".join(out)
    info = parse_cops(line)
    if info is None:
        return None
    if info.get("operator"):
        rat = _RAT_NAMES.get(info.get("act", -1), "RAT n/a")
        return f"Modem is currently camped on {info['operator']} via {rat} (selection mode {info['mode']})."
    return f"+COPS: <mode>={info['mode']} — selection mode only, no operator currently camped."


def _decode_cgatt(line: str) -> str | None:
    v = parse_cgatt(line)
    if v is None:
        return None
    return (
        "+CGATT: 1 — modem is packet-data attached (GPRS/EPS attach succeeded)."
        if v == 1 else
        "+CGATT: 0 — modem is NOT data-attached. Cannot send/receive IP traffic."
    )


def _decode_cpsms(line: str) -> str | None:
    info = parse_cpsms(line)
    if info is None:
        return None
    if info["enabled"] == 0:
        return "+CPSMS: 0 — Power Saving Mode is disabled."
    out = ["+CPSMS: 1 — Power Saving Mode is enabled."]
    if info.get("t3324_bits"):
        out.append(f"  T3324 (active timer) = '{info['t3324_bits']}' (modem stays awake this long after activity)")
    if info.get("t3412_bits"):
        out.append(f"  T3412 (extended periodic TAU) = '{info['t3412_bits']}'")
    out.append("  Devices in PSM are only paged briefly during the periodic TAU window.")
    return "\n".join(out)


def _decode_cme_error(line: str) -> str | None:
    m = re.match(r"^\+CME ERROR:\s*(.+)$", line)
    if not m:
        return None
    code = m.group(1).strip()
    catalogue = {
        "10": "SIM not inserted",
        "11": "SIM PIN required",
        "12": "SIM PUK required",
        "13": "SIM failure",
        "14": "SIM busy",
        "15": "SIM wrong",
        "30": "no network service",
        "31": "network timeout",
        "100": "unknown / generic failure (often = PDP context activation refused)",
    }
    meaning = catalogue.get(code, "(see 3GPP TS 27.007 Annex A.18)")
    return f"+CME ERROR: {code} — {meaning}"


def _decode_cpin(line: str) -> str | None:
    m = re.match(r"^\+CPIN:\s*(.+)$", line)
    if not m:
        return None
    state = m.group(1).strip()
    catalogue = {
        "READY": "SIM unlocked and ready for use.",
        "SIM PIN": "SIM PIN required — enter with AT+CPIN=\"<pin>\".",
        "SIM PUK": "SIM blocked — needs PUK to unblock: AT+CPIN=\"<puk>\",\"<new pin>\".",
        "SIM PIN2": "SIM PIN2 required (rarely seen on M2M SIMs).",
        "SIM PUK2": "SIM PUK2 required.",
        "PH-SIM PIN": "Phone-to-SIM PIN locked (modem-bound to a specific SIM).",
        "PH-NET PIN": "Network personalisation lock active (carrier lock).",
        "NOT INSERTED": "Modem cannot detect a SIM. Check seating, contacts, hardware.",
        "BUSY": "SIM is responding but not ready yet.",
    }
    meaning = catalogue.get(state.upper(), "")
    return f"+CPIN: {state} — {meaning}" if meaning else f"+CPIN: {state}"


def _decode_qping(line: str) -> str | None:
    m = re.match(r'^\+QPING:\s*(?P<code>-?\d+),"(?P<host>[^"]+)",(?P<bytes>\d+),(?P<time>\d+),(?P<ttl>\d+)', line)
    if not m:
        # Summary line: +QPING: <code>,<sent>,<received>,<lost>,<min>,<max>,<avg>
        m2 = re.match(r"^\+QPING:\s*(?P<code>-?\d+),(?P<sent>\d+),(?P<recv>\d+),(?P<lost>\d+)", line)
        if m2:
            return (
                f"+QPING summary: sent={m2['sent']}, received={m2['recv']}, lost={m2['lost']}. "
                f"Result code {m2['code']} (0 = success, non-zero = failure)."
            )
        return None
    code = int(m["code"])
    if code == 0:
        return f"+QPING success: {m['bytes']} bytes from {m['host']} in {m['time']} ms (ttl={m['ttl']})."
    qping_errors = {
        565: "DNS lookup failed (could not resolve hostname)",
        566: "DNS parse failed (invalid response from DNS server)",
        567: "destination unreachable",
        568: "transmit timeout",
        569: "destination unreachable / packet timeout",
    }
    meaning = qping_errors.get(code, "ping failed (vendor-specific error code)")
    return f"+QPING failed for {m['host']} — code {code}: {meaning}."


_DECODERS: dict[str, ResponseDecoder] = {
    "+CREG": _decode_creg_family("CREG"),
    "+CGREG": _decode_creg_family("CGREG"),
    "+CEREG": _decode_creg_family("CEREG"),
    "+CSQ": _decode_csq,
    "+CESQ": _decode_cesq,
    "+QCSQ": _decode_qcsq,
    "+CGPADDR": _decode_cgpaddr,
    "+COPS": _decode_cops,
    "+CGATT": _decode_cgatt,
    "+CPSMS": _decode_cpsms,
    "+CPIN": _decode_cpin,
    "+QPING": _decode_qping,
    "+CME ERROR": _decode_cme_error,
}


def decode_response(line: str) -> str | None:
    line = line.strip()
    for prefix, decoder in _DECODERS.items():
        if line.upper().startswith(prefix.upper()):
            result = decoder(line)
            if result:
                return result
    return None


# ---- command reference --------------------------------------------------

_COMMANDS: dict[str, ATCommand] = {}


def _add(cmd: ATCommand) -> None:
    _COMMANDS[cmd.name.upper()] = cmd


_add(ATCommand(
    name="+CPIN",
    vendor="3gpp",
    purpose="Query or enter SIM PIN. The first thing to check on any 'won't connect' ticket.",
    syntax=["AT+CPIN?  (read SIM lock state)", "AT+CPIN=\"<pin>\"  (enter PIN)", "AT+CPIN=\"<puk>\",\"<new_pin>\"  (unblock with PUK)"],
    response_format='+CPIN: READY | SIM PIN | SIM PUK | NOT INSERTED | ...',
    common_errors={"+CME ERROR: 10": "SIM not inserted", "+CME ERROR: 11": "SIM PIN required",
                    "+CME ERROR: 12": "SIM PUK required", "+CME ERROR: 13": "SIM failure"},
    example='AT+CPIN?\\n+CPIN: READY\\nOK',
))

_add(ATCommand(
    name="+CFUN",
    vendor="3gpp",
    purpose="Modem functionality level — controls radio on/off and reset.",
    syntax=["AT+CFUN=0  (full minimum functionality / radio off)",
            "AT+CFUN=1  (full functionality / radio on)",
            "AT+CFUN=4  (airplane mode — radio off but UART/SIM kept up)",
            "AT+CFUN=1,1  (full functionality + reset, vendor-specific)"],
    common_errors={"+CME ERROR: 14": "SIM busy"},
    example="AT+CFUN=0\\nOK\\nAT+CFUN=1\\nOK   # radio reset",
))

_add(ATCommand(
    name="+CSQ",
    vendor="3gpp",
    purpose="Signal quality (RSSI). Legacy command, kept for compatibility — for LTE/Cat-M prefer +CESQ or +QCSQ.",
    syntax=["AT+CSQ"],
    response_format='+CSQ: <rssi>,<ber>',
    parameters={"rssi": "0..31 (each unit = 2 dB; 0 = -113 dBm, 31 = -51 dBm); 99 = unknown",
                 "ber": "0..7 bit error rate; 99 = unknown (almost always 99 on LTE)"},
    example='AT+CSQ\\n+CSQ: 21,99\\nOK   # ~-71 dBm RSSI',
))

_add(ATCommand(
    name="+CESQ",
    vendor="3gpp",
    purpose="Extended signal quality. The standard way to read RSRP/RSRQ on LTE-M and NB-IoT modems that don't support vendor-specific commands like +QCSQ.",
    syntax=["AT+CESQ"],
    response_format='+CESQ: <rxlev>,<ber>,<rscp>,<ecno>,<rsrq>,<rsrp>',
    parameters={"rsrp": "0..97 → -141..-44 dBm (rsrp_dBm = idx - 141); 255 = n/a",
                 "rsrq": "0..34 → -20..-3 dB (rsrq_dB = -20 + 0.5*idx); 255 = n/a"},
    example='AT+CESQ\\n+CESQ: 99,99,255,255,15,23\\nOK   # rsrp idx 23 = -118 dBm (marginal)',
))

_add(ATCommand(
    name="+CEREG",
    vendor="3gpp",
    purpose="EPS / LTE network registration status. The most important triage command on any LTE-M / Cat-1 ticket.",
    syntax=["AT+CEREG?  (current status)", "AT+CEREG=<n>  (set URC verbosity 0–4)"],
    response_format='+CEREG: <n>,<stat>[,<tac>,<ci>,<AcT>]',
    parameters={"stat": "0=not searching, 1=registered home, 2=searching, 3=registration denied, 4=unknown, 5=registered roaming"},
    example='AT+CEREG?\\n+CEREG: 0,1\\nOK',
    docs_url="https://www.3gpp.org/DynaReport/27007.htm",
))

_add(ATCommand(
    name="+CGREG",
    vendor="3gpp",
    purpose="GPRS / packet-switched (2G/3G data) registration. On LTE-only deployments, expect 0,0 here even when CEREG is healthy.",
    syntax=["AT+CGREG?"],
    response_format='+CGREG: <n>,<stat>',
    parameters={"stat": "same encoding as +CEREG"},
))

_add(ATCommand(
    name="+CREG",
    vendor="3gpp",
    purpose="Circuit-switched (legacy 2G/3G voice/SMS) registration. Less relevant on Cat-M / NB-IoT deployments.",
    syntax=["AT+CREG?"],
    response_format='+CREG: <n>,<stat>',
))

_add(ATCommand(
    name="+CGDCONT",
    vendor="3gpp",
    purpose="Define or query PDP contexts (APN configuration). For Hologram SIMs the APN must be exactly 'hologram'.",
    syntax=['AT+CGDCONT=<cid>,"<pdp_type>","<APN>"   (write)',
            'AT+CGDCONT?   (read all defined contexts)',
            'AT+CGDCONT=?  (read supported PDP types)'],
    response_format='+CGDCONT: <cid>,"<pdp_type>","<APN>","<address>",<auth>,...',
    example='AT+CGDCONT=1,"IP","hologram"\\nOK',
))

_add(ATCommand(
    name="+CGATT",
    vendor="3gpp",
    purpose="Attach to / detach from packet-switched service.",
    syntax=["AT+CGATT?   (query)", "AT+CGATT=1   (attach)", "AT+CGATT=0   (detach)"],
    response_format='+CGATT: <state>',
    parameters={"state": "0 = detached, 1 = attached"},
    common_errors={"+CME ERROR: 30": "no network service"},
))

_add(ATCommand(
    name="+CGACT",
    vendor="3gpp",
    purpose="Activate or deactivate a PDP context (i.e. bring up the data session).",
    syntax=["AT+CGACT=1,<cid>   (activate)", "AT+CGACT=0,<cid>   (deactivate)", "AT+CGACT?   (query state)"],
    common_errors={"ERROR": "Activation refused. Check APN, plan, account state. Use AT+CEER for cause.",
                    "+CME ERROR: 100": "Unknown / generic failure — usually APN-related on Hologram SIMs."},
    example='AT+CGACT=1,1\\nOK',
))

_add(ATCommand(
    name="+CGPADDR",
    vendor="3gpp",
    purpose="Read the IP address allocated to a PDP context. Useful to confirm context activation actually got an IP.",
    syntax=["AT+CGPADDR=<cid>"],
    response_format='+CGPADDR: <cid>,"<address>"',
    example='AT+CGPADDR=1\\n+CGPADDR: 1,"100.66.18.214"\\nOK   # CGNAT IP, normal for cellular',
))

_add(ATCommand(
    name="+COPS",
    vendor="3gpp",
    purpose="Operator selection. Read current operator, scan available operators, or manually select a network.",
    syntax=["AT+COPS?   (current)", "AT+COPS=?  (scan — slow, can take 60+ s)",
            'AT+COPS=<mode>[,<format>,<oper>[,<AcT>]]   (set)'],
    response_format='+COPS: <mode>,<format>,"<oper>",<AcT>   or   list of (stat,long,short,plmn,act) tuples',
    parameters={"stat": "1=available, 2=current, 3=FORBIDDEN (no roaming agreement)"},
))

_add(ATCommand(
    name="+CEER",
    vendor="3gpp",
    purpose="Extended error report. Run this after any unexpected ERROR / +CME ERROR to get the cause code.",
    syntax=["AT+CEER"],
    example='AT+CGACT=1,1\\nERROR\\nAT+CEER\\n+CEER: "No PDP context activated","SM","Cause: 33 - requested service option not subscribed"\\nOK',
))

_add(ATCommand(
    name="+CPSMS",
    vendor="3gpp",
    purpose="Power Saving Mode configuration. Putting the modem to sleep between paging windows for battery savings.",
    syntax=["AT+CPSMS=<mode>[,,,<requested_T3412>,<requested_T3324>]"],
    parameters={"T3324": "Active timer — how long the modem stays in connected state after data activity",
                 "T3412": "Extended periodic TAU — how often the modem briefly wakes for tracking-area updates"},
    example='AT+CPSMS=1,,,"00000010","00000001"   # T3412=60s, T3324=10s',
))

_add(ATCommand(
    name="+CEDRXS",
    vendor="3gpp",
    purpose="Extended Discontinuous Reception (eDRX) configuration. Less aggressive than PSM — modem stays attached but reduces paging frequency.",
    syntax=["AT+CEDRXS=<mode>,<actType>,\"<requested_eDRX_value>\""],
))

_add(ATCommand(
    name="+CSCON",
    vendor="3gpp",
    purpose="Signaling connection status indication. Reports whether the modem is in RRC IDLE or RRC CONNECTED.",
    syntax=["AT+CSCON?"],
    response_format='+CSCON: <n>,<state>',
    parameters={"state": "0 = idle, 1 = connected"},
))

# Quectel-specific commands seen on BG/EC/EG modules.
_add(ATCommand(
    name="+QCSQ",
    vendor="quectel",
    purpose="Quectel-specific signal quality with full RSRP/RSRQ/SINR breakdown plus the active RAT.",
    syntax=["AT+QCSQ"],
    response_format='+QCSQ: "<RAT>",<rssi>,<rsrp>,<sinr>,<rsrq>',
    example='AT+QCSQ\\n+QCSQ: "CAT-M1",-79,-92,142,-9\\nOK',
))

_add(ATCommand(
    name="+QCFG",
    vendor="quectel",
    purpose="Modem configuration umbrella command. Many subcommands — band mask, RAT mode, network scan order, etc.",
    syntax=['AT+QCFG="iotopmode"[,<mode>]   (0=Cat-M only, 1=NB-IoT only, 2=both)',
            'AT+QCFG="band"[,<gsmBand>,<lteBand>,<m1Band>,<save>]',
            'AT+QCFG="nwscanseq"[,<order>]'],
    example='AT+QCFG="iotopmode",2,1   # enable both Cat-M and NB-IoT',
))

_add(ATCommand(
    name="+QPING",
    vendor="quectel",
    purpose="Quectel-built-in ICMP ping. Useful for confirming data path without involving an external host.",
    syntax=['AT+QPING=<contextID>,"<host>"[,<timeout>,<count>]'],
    common_errors={"565": "DNS lookup failed", "566": "DNS parse failed", "567": "destination unreachable",
                    "568": "transmit timeout", "569": "ICMP packet timeout"},
    example='AT+QPING=1,"8.8.8.8",1,4',
))

_add(ATCommand(
    name="+QIOPEN",
    vendor="quectel",
    purpose="Open a TCP/UDP socket to a remote host. Quectel's connection-oriented socket primitive.",
    syntax=['AT+QIOPEN=<contextID>,<connectID>,"<service_type>","<host>",<remote_port>,<local_port>,<access_mode>'],
    parameters={"service_type": '"TCP" | "UDP" | "TCP LISTENER" | "UDP SERVICE"',
                 "access_mode": "0=buffer, 1=direct push, 2=transparent"},
    response_format='+QIOPEN: <connectID>,<err>   (err=0 → success)',
    common_errors={"550": "unknown error", "566": "DNS parse failed", "567": "destination unreachable",
                    "569": "operation timeout"},
))

_add(ATCommand(
    name="+QESIM",
    vendor="quectel",
    purpose="Manage embedded UICC profiles on Hologram Hyper SIMs (and other eUICC SIMs supported by Quectel modules).",
    syntax=['AT+QESIM="list"   (list installed profiles)',
            'AT+QESIM="active"   (show active profile index)',
            'AT+QESIM="enable",<index>   (switch active profile)'],
    response_format='+QESIM: "list",<idx>,"<iccid>",<active>',
))

_add(ATCommand(
    name="+QENG",
    vendor="quectel",
    purpose="Engineering / serving-cell info. Cell ID, PCI, EARFCN, signal — the deep RF view.",
    syntax=['AT+QENG="servingcell"', 'AT+QENG="neighbourcell"'],
))

_add(ATCommand(
    name="+QIDNSCFG",
    vendor="quectel",
    purpose="Configure DNS servers per PDP context. Override carrier-assigned DNS when needed (e.g. carrier DNS is blocked).",
    syntax=['AT+QIDNSCFG=<contextID>   (read)',
            'AT+QIDNSCFG=<contextID>,"<primary>","<secondary>"   (write)'],
    example='AT+QIDNSCFG=1,"8.8.8.8","1.1.1.1"',
))

# u-blox commands seen on SARA-R5, SARA-R412, LARA-R6.
_add(ATCommand(
    name="+UCGED",
    vendor="ublox",
    purpose="u-blox cell environment description. Detailed RF measurements (RSRP, RSRQ, EARFCN, etc).",
    syntax=["AT+UCGED=<mode>"],
))

_add(ATCommand(
    name="+UPING",
    vendor="ublox",
    purpose="u-blox ICMP ping.",
    syntax=['AT+UPING="<host>"'],
    response_format='+UUPING: <id>,<bytes>,"<host>","<addr>",<ttl>,<rtt>   (success URC)\n+UUPINGER: <id>,"Timeout"   (failure URC)',
))

_add(ATCommand(
    name="+UBANDMASK",
    vendor="ublox",
    purpose="u-blox band mask configuration. Reads/sets the bitmask of LTE bands the modem will scan.",
    syntax=["AT+UBANDMASK?   (read)", "AT+UBANDMASK=<RAT>,<mask_low>[,<mask_high>]   (write)"],
    parameters={"RAT": "0 = Cat-M1, 1 = NB-IoT"},
))

_add(ATCommand(
    name="+URAT",
    vendor="ublox",
    purpose="u-blox RAT selection. Picks LTE-M, NB-IoT, GSM, or a preference order across them.",
    syntax=["AT+URAT?", "AT+URAT=<RAT>[,<RAT2>[,<RAT3>]]"],
    parameters={"RAT": "7 = LTE Cat-M1, 8 = NB-IoT, others vary by module"},
))

# SIMCom commands seen on SIM7080G, SIM7600G-H.
_add(ATCommand(
    name="+CMNB",
    vendor="simcom",
    purpose="SIMCom RAT-mode lock. Picks Cat-M, NB-IoT, or both.",
    syntax=["AT+CMNB?", "AT+CMNB=<mode>"],
    parameters={"mode": "1 = Cat-M, 2 = NB-IoT, 3 = both"},
))

_add(ATCommand(
    name="+CSERVINFO",
    vendor="simcom",
    purpose="SIMCom serving cell information. Equivalent to Quectel +QENG=\"servingcell\".",
    syntax=["AT+CSERVINFO"],
))

# Telit commands.
_add(ATCommand(
    name="#SGACT",
    vendor="telit",
    purpose="Telit-specific PDP context activation that returns the IP. Equivalent of +CGACT=1,1 followed by +CGPADDR.",
    syntax=["AT#SGACT=<cid>,<stat>"],
    example='AT#SGACT=1,1\\n#SGACT: "100.66.42.18"\\nOK',
))

_add(ATCommand(
    name="#SD",
    vendor="telit",
    purpose="Telit socket dial — open a TCP connection. Equivalent to Quectel +QIOPEN with TCP.",
    syntax=['AT#SD=<connID>,<txProt>,<rPort>,"<IPaddr>"[,<closureType>,<lPort>,<connMode>]'],
))

# Sierra commands.
_add(ATCommand(
    name="+KSRAT",
    vendor="sierra",
    purpose="Sierra Wireless RAT-mode selection on HL-series modules.",
    syntax=["AT+KSRAT?", "AT+KSRAT=<rat>"],
    parameters={"rat": "0 = LTE-M & NB-IoT, 1 = Cat-M only, 2 = NB-IoT only"},
))

# Nordic commands.
_add(ATCommand(
    name="%XSYSTEMMODE",
    vendor="nordic",
    purpose="Nordic nRF9160 system mode. Pick LTE-M, NB-IoT, GNSS, and preference between LTE modes.",
    syntax=["AT%XSYSTEMMODE?", "AT%XSYSTEMMODE=<ltem>,<nbiot>,<gnss>,<lte_pref>"],
    parameters={"ltem": "0/1 enable", "nbiot": "0/1 enable", "lte_pref": "0=auto, 1=LTE-M pref, 2=NB-IoT pref"},
))

_add(ATCommand(
    name="%XSNRSQ",
    vendor="nordic",
    purpose="Nordic SNR / signal strength readout.",
    syntax=["AT%XSNRSQ?"],
))


def lookup(name: str) -> ATCommand | None:
    n = name.upper().strip()
    if n.startswith("AT"):
        n = n[2:].lstrip(" ")
    if not n.startswith(("+", "#", "%", "&")) and n in _COMMANDS:
        return _COMMANDS[n]
    return _COMMANDS.get(n)


def list_commands(vendor: str | None = None) -> list[ATCommand]:
    items = list(_COMMANDS.values())
    if vendor is not None:
        items = [c for c in items if c.vendor == vendor]
    return sorted(items, key=lambda c: (c.vendor, c.name))


def search(query: str) -> list[ATCommand]:
    q = query.lower().strip()
    if not q:
        return []
    return [
        c for c in _COMMANDS.values()
        if q in c.name.lower() or q in c.purpose.lower() or any(q in s.lower() for s in c.syntax)
    ]
