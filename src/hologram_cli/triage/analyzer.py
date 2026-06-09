"""Diagnosis rules over a parsed AT log.

Each rule examines the parsed log and returns a Hypothesis if the failure
pattern matches. The top hypotheses are ranked by confidence and returned
in a Diagnosis. The rules are intentionally specific — generic catch-all
rules tend to mask more useful, specific findings.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import re

from hologram_cli.triage.parser import (
    ParsedLog,
    parse_cgatt,
    parse_cops,
    parse_cops_scan,
    parse_cpsms,
    parse_creg,
    parse_csq,
    parse_qesim_list,
)
from hologram_cli.triage.signals import lowest_rsrp, rat_lock_mode

CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1}

# Country MCCs we treat as "foreign" relative to a US-based deployment.
# Used to disambiguate HSS-not-propagated from genuine roaming denial.
US_MCCS = {"310", "311", "312", "313", "314", "315", "316"}


@dataclass
class Hypothesis:
    rule_id: str
    title: str
    confidence: str
    explanation: str
    evidence: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    customer_summary: str = ""

    def as_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "title": self.title,
            "confidence": self.confidence,
            "explanation": self.explanation,
            "evidence": self.evidence,
            "next_actions": self.next_actions,
            "customer_summary": self.customer_summary,
        }


@dataclass
class Diagnosis:
    health: str  # "healthy" | "degraded" | "broken"
    summary: str
    hypotheses: list[Hypothesis]
    vendor: str | None = None
    module: str | None = None

    def as_dict(self) -> dict:
        return {
            "health": self.health,
            "summary": self.summary,
            "vendor": self.vendor,
            "module": self.module,
            "hypotheses": [h.as_dict() for h in self.hypotheses],
        }


Rule = Callable[[ParsedLog], Hypothesis | None]


def analyze(log: ParsedLog) -> Diagnosis:
    hypotheses: list[Hypothesis] = []
    for rule in _RULES:
        h = rule(log)
        if h is not None:
            hypotheses.append(h)

    hypotheses.sort(key=lambda h: CONFIDENCE_RANK[h.confidence], reverse=True)
    top = hypotheses[:3]

    if not top:
        if _looks_attached(log):
            if _has_app_layer_success(log):
                return Diagnosis(
                    health="healthy",
                    summary="No failure patterns matched. Modem is registered, attached, and an application-layer probe succeeded.",
                    hypotheses=[_healthy_hypothesis(log)],
                    vendor=log.vendor,
                    module=log.module,
                )
            return Diagnosis(
                health="degraded",
                summary="Network attach looks fine but no application-layer probe was captured — cannot confirm end-to-end connectivity.",
                hypotheses=[_appears_attached_hypothesis()],
                vendor=log.vendor,
                module=log.module,
            )
        return Diagnosis(
            health="degraded",
            summary="No specific failure pattern matched, but the log lacks indicators of a healthy session.",
            hypotheses=[_unknown_hypothesis()],
            vendor=log.vendor,
            module=log.module,
        )

    health = "broken" if any(h.confidence == "high" for h in top) else "degraded"
    summary = top[0].title
    return Diagnosis(
        health=health,
        summary=summary,
        hypotheses=top,
        vendor=log.vendor,
        module=log.module,
    )


# ---- helpers ------------------------------------------------------------


def _evidence(line_no: int, content: str) -> str:
    return f"line {line_no}: {content}"


def _forbidden_plmn_in_scan(log: ParsedLog) -> dict | None:
    """A +COPS=? scan that returns at least one entry with stat==3 (forbidden)
    is the strongest available signal for roaming denial — it's the network
    explicitly telling the device 'you may not use this PLMN'. Without this
    signal, registration denials are ambiguous between fresh-activation
    propagation delays and true roaming denial."""
    cops_scan = log.find("AT+COPS=?")
    if not cops_scan:
        return None
    for line in cops_scan.responses:
        for entry in parse_cops_scan(line):
            if entry["stat"] == 3:
                return entry
    return None


def _looks_attached(log: ParsedLog) -> bool:
    """Network-level health: registered, attached, PDP context up. Says nothing
    about whether application-layer traffic actually works — for that, see
    _has_app_layer_success."""
    cereg = log.find("AT+CEREG?") or log.find("AT+CGREG?")
    if cereg is None:
        return False
    if not any(parse_creg(r) and parse_creg(r)[1] in (1, 5) for r in cereg.responses):
        return False
    cgatt = log.find("AT+CGATT?")
    if cgatt is None or not any(parse_cgatt(r) == 1 for r in cgatt.responses):
        return False
    cgact = log.find("AT+CGACT")
    if cgact is None or cgact.errored:
        return False
    return True


def _has_app_layer_success(log: ParsedLog) -> bool:
    """Did the modem successfully complete an application-layer probe in this
    log? Successful ping reply, successful socket open, etc. This is what
    distinguishes 'definitely healthy' from 'looks attached but unverified'."""
    for ex in log.exchanges:
        for r in ex.responses:
            if r == "CONNECT":
                return True
            if r.startswith("+UUPING:"):  # u-blox ping reply (not error)
                return True
            if r.startswith("+QPING:"):
                # +QPING: 0,"<host>",... is per-packet success; non-zero = failure.
                m = re.match(r'^\+QPING:\s*0,"[^"]+"', r)
                if m:
                    return True
    return False


def _healthy_hypothesis(log: ParsedLog) -> Hypothesis:
    return Hypothesis(
        rule_id="healthy_baseline",
        title="Healthy session",
        confidence="high",
        explanation="The modem is registered to the network, data-attached, and has an active PDP context with a valid IP. No fault patterns matched.",
        evidence=[],
        next_actions=["No action needed. Use this log as a reference for what success looks like on this module."],
        customer_summary="Your device is online and connected normally — no issues detected in this log.",
    )


def _appears_attached_hypothesis() -> Hypothesis:
    return Hypothesis(
        rule_id="appears_attached",
        title="Network attach looks fine but no application-layer success captured",
        confidence="medium",
        explanation=(
            "The modem is registered, packet-attached, and has an active PDP context with a "
            "valid IP. But the log does not include a successful application-layer probe "
            "(ping reply, socket CONNECT, etc.). The session may be healthy and simply not "
            "exercised, or there may be a downstream issue (DNS, firewall, application server) "
            "that this capture would not reveal."
        ),
        evidence=[],
        next_actions=[
            "Capture a longer session that includes an application-layer probe.",
            "For Quectel: AT+QPING=1,\"8.8.8.8\",1,4   (numeric IP, isolates DNS)",
            "For Quectel: AT+QPING=1,\"hologram.io\",1,4   (hostname, exercises DNS)",
            "For u-blox:  AT+UPING=\"8.8.8.8\"",
            "If both pings succeed, the link is healthy. If hostname pings fail but IP pings succeed, see the dns_failure rule.",
        ],
        customer_summary=(
            "Your device is registered to the network and has been allocated an IP — that part "
            "looks fine. But the log doesn't include any successful data-path probe, so I can't "
            "confirm end-to-end connectivity from this capture alone. Could you run a quick "
            "ping test from the modem (a numeric IP like 8.8.8.8 and a hostname like hologram.io) "
            "and send the output back? That will tell us whether the data path is genuinely "
            "healthy or whether there's a DNS / firewall / application-server issue downstream."
        ),
    )


def _unknown_hypothesis() -> Hypothesis:
    return Hypothesis(
        rule_id="unknown",
        title="Unable to classify",
        confidence="low",
        explanation="The log does not contain enough signal for the analyzer to make a confident diagnosis.",
        evidence=[],
        next_actions=[
            "Capture a longer session that includes: AT+CPIN?, AT+CSQ, AT+CEREG?, AT+CGATT?, AT+CGACT=1,1, AT+CGPADDR=1.",
            "Include the modem ID (ATI) and signal quality (AT+QCSQ or AT+UCGED=5).",
            "Re-run the analyzer with the fuller capture.",
        ],
    )


# ---- rules --------------------------------------------------------------


def rule_modem_unresponsive(log: ParsedLog) -> Hypothesis | None:
    bare_at = [ex for ex in log.exchanges if ex.command.upper() == "AT"]
    if len(bare_at) < 3:
        return None
    empty = [ex for ex in bare_at if ex.empty]
    if len(empty) < 2:
        return None
    return Hypothesis(
        rule_id="modem_unresponsive",
        title="Modem not responding to AT commands (pre-network problem)",
        confidence="high",
        explanation=(
            "Multiple bare 'AT' commands received no response and no terminal status. "
            "This is a hardware/serial-layer problem — the modem is not even attempting "
            "to communicate, so SIM, network, and APN questions are not yet relevant."
        ),
        evidence=[_evidence(ex.start_line, ex.command) for ex in empty[:3]],
        next_actions=[
            "Verify VBAT can supply LTE TX peak current (~2 A on Cat-1, ~500 mA on Cat-M).",
            "Check UART RX/TX wiring, ground reference, and level shifting (1.8 V vs 3.3 V).",
            "Try autobaud at 115200, 9600, and 460800 from a clean cold boot.",
            "Verify the ENABLE/PWRKEY pulse sequence per the module datasheet.",
            "If the modem responds *sometimes* but not under load, suspect a power supply that browns out under TX bursts.",
        ],
        customer_summary=(
            "The logs show your modem isn't responding to basic AT commands at all, which means "
            "the issue is at the hardware/serial layer rather than network. Before we look at SIM "
            "or carrier config, can you check power supply current capability, UART wiring, and "
            "baud rate? Even a few minutes of multimeter work on VBAT under load tends to surface "
            "the cause faster than chasing logs."
        ),
    )


def rule_sim_pin_locked(log: ParsedLog) -> Hypothesis | None:
    cpin = log.find("AT+CPIN?")
    if cpin is None:
        return None
    pin_states = ("SIM PIN2", "SIM PUK2", "SIM PIN", "SIM PUK", "PH-SIM PIN", "PH-NET PIN")
    matched = None
    for r in cpin.responses:
        for state in pin_states:
            if state in r.upper():
                matched = state
                break
        if matched:
            break
    if matched is None:
        return None
    needs_puk = "PUK" in matched
    if needs_puk:
        actions = [
            "Obtain the PUK from the SIM provider — this is required after 3 wrong PIN attempts.",
            'Unblock and set a new PIN: AT+CPIN="<PUK>","<new PIN>"',
            'Optionally remove the PIN lock entirely: AT+CLCK="SC",0,"<new PIN>"',
        ]
    else:
        actions = [
            'Enter the PIN: AT+CPIN="<pin>"',
            "If unknown, verify with the SIM provider — three wrong attempts will lock to PUK.",
            'Optionally remove the PIN requirement: AT+CLCK="SC",0,"<pin>"',
        ]
    return Hypothesis(
        rule_id="sim_pin_locked",
        title=f"SIM is locked, awaiting {matched.title()}",
        confidence="high",
        explanation=(
            f"The modem reports +CPIN: {matched}, meaning the SIM has a security lock that "
            "must be cleared before any network operation can proceed. The SIM is detected "
            "(this is different from 'SIM not inserted'), but the radio stack is gated until "
            "the correct PIN/PUK is entered."
        ),
        evidence=[_evidence(cpin.start_line, f"+CPIN: {matched}")],
        next_actions=actions,
        customer_summary=(
            "Your SIM is locked — the modem detects it, but the SIM has a "
            f"{'PUK' if needs_puk else 'PIN'} configured that needs to be entered before it "
            "can connect. This is different from a missing SIM. "
            f"Could you {'find the PUK code from the SIM issuer' if needs_puk else 'send me the SIM PIN you have on file'}? "
            "Once entered, the device should proceed normally; if you'd like, I can also walk "
            "you through permanently disabling the PIN requirement so this doesn't recur on a reboot."
        ),
    )


def rule_sim_not_inserted(log: ParsedLog) -> Hypothesis | None:
    cpin = log.find("AT+CPIN?")
    if cpin and any("NOT INSERTED" in r.upper() for r in cpin.responses):
        ccid = log.find("AT+CCID")
        evidence = [_evidence(cpin.start_line, "AT+CPIN? -> +CPIN: NOT INSERTED")]
        if ccid and ccid.status == "CME:10":
            evidence.append(_evidence(ccid.start_line, "AT+CCID -> +CME ERROR: 10 (SIM not inserted)"))
        return Hypothesis(
            rule_id="sim_not_inserted",
            title="SIM card not detected by the modem",
            confidence="high",
            explanation=(
                "The modem cannot read the UICC. This precedes any network interaction — until "
                "+CPIN reports READY, no amount of carrier-side troubleshooting will help."
            ),
            evidence=evidence,
            next_actions=[
                "Power down the device and reseat the SIM, verifying orientation against the silkscreen.",
                "Inspect SIM contacts for dirt or corrosion; clean with isopropyl alcohol if needed.",
                "Try a known-good SIM in the same slot — if it also fails, the slot/holder is at fault.",
                "Try the suspect SIM in a known-good device — if it works there, the original device's slot is the issue.",
            ],
            customer_summary=(
                "Your modem isn't detecting the SIM at all (the +CPIN: NOT INSERTED response). "
                "Before anything network-related, please power the device down, reseat the SIM "
                "(double-checking the orientation), and try again. If that doesn't work, swapping "
                "in a known-good SIM is the fastest way to isolate whether the issue is the SIM "
                "or the device."
            ),
        )
    return None


def rule_wrong_apn(log: ParsedLog) -> Hypothesis | None:
    cgact = log.find("AT+CGACT")
    if not cgact or not cgact.errored:
        return None
    cgdcont = log.find("AT+CGDCONT?")
    apn = None
    if cgdcont:
        for r in cgdcont.responses:
            if "hologram" in r.lower():
                return None  # APN is correct, the problem is something else
            if r.startswith("+CGDCONT"):
                # +CGDCONT: 1,"IP","internet","",0,0,0,0
                parts = r.split(",")
                if len(parts) >= 3:
                    apn = parts[2].strip().strip('"')
                    break
    ceer = log.find("AT+CEER")
    cause_33 = False
    if ceer:
        for r in ceer.responses:
            if "33" in r and "subscribed" in r.lower():
                cause_33 = True
                break

    if apn is None and not cause_33:
        return None
    confidence = "high" if cause_33 else "medium"
    evidence = [_evidence(cgact.start_line, f"AT+CGACT -> {cgact.status}")]
    if apn is not None:
        evidence.append(_evidence(cgdcont.start_line, f"APN configured as '{apn}' (expected 'hologram')"))
    if cause_33 and ceer:
        evidence.append(_evidence(ceer.start_line, "+CEER reports 3GPP cause 33 (requested service option not subscribed)"))
    return Hypothesis(
        rule_id="wrong_apn",
        title="PDP context activation failed — APN likely incorrect",
        confidence=confidence,
        explanation=(
            "The modem registers and attaches successfully but fails to bring up a PDP context. "
            "3GPP cause 33 ('requested service option not subscribed') almost always means the APN "
            "string isn't provisioned for this SIM at the carrier. For Hologram SIMs the APN must "
            "be exactly 'hologram'."
        ),
        evidence=evidence,
        next_actions=[
            'Set the APN: AT+CGDCONT=1,"IP","hologram"',
            "Cycle the radio: AT+CFUN=0  then  AT+CFUN=1",
            "Re-test: AT+CGACT=1,1 should now succeed.",
            "If the device firmware re-writes APN on boot, the change must happen in the OEM config store, not just the AT shell.",
        ],
        customer_summary=(
            "Your device is reaching the network and attaching successfully, but failing at the "
            "very last step — bringing up the data context. The cause code points to an APN "
            "mismatch. For Hologram SIMs the APN needs to be exactly `hologram` (lowercase, "
            "no quotes inside the string). Please update the APN setting and bounce the radio, "
            "and the connection should come up."
        ),
    )


def rule_roaming_denied(log: ParsedLog) -> Hypothesis | None:
    forbidden = _forbidden_plmn_in_scan(log)
    if forbidden is None:
        return None

    cops_scan = log.find("AT+COPS=?")
    cops_current = log.find("AT+COPS?")
    camped_on = None
    if cops_current:
        for r in cops_current.responses:
            info = parse_cops(r)
            if info and info.get("operator"):
                camped_on = info["operator"]
                break

    return Hypothesis(
        rule_id="roaming_denied",
        title="Roaming denied — current profile lacks coverage on this network",
        confidence="high",
        explanation=(
            f"The +COPS=? scan reports at least one PLMN with status 3 (forbidden) — the network "
            "is explicitly telling the device it may not use these operators. This usually means "
            "the active SIM profile lacks a roaming agreement in this country. Unlike a fresh-"
            "activation propagation delay, this will not resolve with time; it requires a profile "
            "change or a different SIM SKU for the region."
        ),
        evidence=[
            _evidence(cops_scan.start_line, f"+COPS=? returns forbidden PLMN: {forbidden['long']} ({forbidden['plmn']})"),
            *([_evidence(cops_current.start_line, f"+COPS? -> currently camped on {camped_on}")] if camped_on else []),
        ],
        next_actions=[
            "Confirm coverage in the deployment country at https://www.hologram.io/global-coverage.",
            "For Hyper SIMs (eUICC): switch to a profile that includes the deployment country.",
            "Long-term: define a Conductor geographic-failover policy so this happens automatically when devices cross borders.",
            "For non-eUICC SIMs: this device needs a different SKU for this region — escalate to the AM/CSM.",
        ],
        customer_summary=(
            "Your device is finding the local network just fine, but the network is rejecting it "
            "because the SIM profile that's currently active doesn't have a roaming agreement in "
            "this country. This is different from a fresh-activation issue — waiting won't fix it. "
            "We'll need to either switch the SIM to a profile that covers your deployment region "
            "or evaluate a different SKU. Can you confirm where the device is operating, and "
            "whether it's a Hyper SIM (which can switch profiles remotely)?"
        ),
    )


def rule_registration_denied_hss(log: ParsedLog) -> Hypothesis | None:
    cereg = log.find("AT+CEREG?") or log.find("AT+CREG?")
    if not cereg:
        return None
    denied = False
    for r in cereg.responses:
        v = parse_creg(r)
        if v and v[1] == 3:
            denied = True
            break
    if not denied:
        return None

    if _forbidden_plmn_in_scan(log) is not None:
        # Roaming-denied rule will handle this case more specifically.
        return None

    csq = log.find("AT+CSQ")
    rssi = None
    if csq:
        for r in csq.responses:
            v = parse_csq(r)
            if v:
                rssi = v[0]
                break
    rf_ok = rssi is not None and 0 < rssi < 99

    cgatt = log.find("AT+CGATT?") or log.find("AT+CGATT=1")
    cgatt_failed = False
    if cgatt:
        for r in cgatt.responses:
            v = parse_cgatt(r)
            if v == 0:
                cgatt_failed = True
        if cgatt.errored:
            cgatt_failed = True

    return Hypothesis(
        rule_id="registration_denied_hss",
        title="Network registration denied — SIM activation likely not yet propagated",
        confidence="high",
        explanation=(
            "The modem sees the network and reports good signal, but registration is being denied "
            "at the network side (+CREG/+CEREG status 3). The most common cause for a recently "
            "activated SIM is that activation hasn't yet propagated to the carrier's HSS. This "
            "typically resolves within an hour."
        ),
        evidence=[
            _evidence(cereg.start_line, f"{cereg.command} -> registration denied (status 3)"),
            *([_evidence(csq.start_line, f"+CSQ rssi={rssi} (signal is fine — not a coverage issue)")] if rf_ok else []),
            *([_evidence(cgatt.start_line, f"AT+CGATT failed: {cgatt.status or '+CGATT: 0'}")] if cgatt_failed else []),
        ],
        next_actions=[
            "Wait 30–60 minutes after activation, then power-cycle the modem and recheck +CEREG/+CREG.",
            "If still denied after an hour: pull the SIM's ICCID and look up its state in the Hologram dashboard (LIVE vs LIVE-PENDING).",
            "Verify the SIM has not been deactivated or paused (PAUSED-USER / PAUSED-SYS / DEAD).",
            "If the dashboard shows the SIM as LIVE but registration is still denied, escalate to L3 with ICCID, IMEI, and timestamp of the +CEREG response.",
        ],
        customer_summary=(
            "I can see what's happening in your log — your device has good signal and is reaching the "
            "tower, but the network is denying registration (the +CREG/+CEREG: 0,3 response). The "
            "APN config and physical connection look fine, so the issue is at the SIM authorization "
            "layer rather than the device side.\n\n"
            "The most likely cause is that the SIM activation hasn't fully propagated to the carrier "
            "yet — this can take anywhere from a few minutes to an hour after activation. Could you "
            "confirm the ICCID of the SIM and approximately when you activated it? If activation just "
            "happened, please power-cycle the device after waiting 30 minutes; if you see the +CEREG "
            "response change to 1 or 5, registration succeeded. If it's still showing 3 after a full "
            "hour, we'll dig into account-level checks together."
        ),
    )


def rule_searching_no_register(log: ParsedLog) -> Hypothesis | None:
    cereg = log.find("AT+CEREG?")
    if not cereg:
        return None
    searching = False
    for r in cereg.responses:
        v = parse_creg(r)
        if v and v[1] == 2:
            searching = True
            break
    if not searching:
        return None

    rat_lock = rat_lock_mode(log)
    rsrp_reading = lowest_rsrp(log)
    weak_signal = rsrp_reading is not None and rsrp_reading.rsrp_dbm <= -115

    # Cat-M-only is the typical default in US deployments and not in itself
    # a fault — treat NB-IoT-only as the only inherently diagnostic lock.
    # Bare "+CEREG status 2" without specific evidence is too generic and
    # shadows more useful rules (band_locked, marginal_signal).
    nb_iot_locked = rat_lock is not None and rat_lock[0] == "nb-iot"
    if not (nb_iot_locked or weak_signal):
        return None

    evidence = [_evidence(cereg.start_line, f"{cereg.command} -> searching, never registers (status 2)")]
    if nb_iot_locked:
        evidence.append(_evidence(rat_lock[1], "modem is RAT-locked to NB-IoT only"))
    if weak_signal:
        evidence.append(
            _evidence(rsrp_reading.line_no, f"{rsrp_reading.source} reports RSRP {rsrp_reading.rsrp_dbm:.0f} dBm (at sensitivity edge)")
        )

    return Hypothesis(
        rule_id="searching_no_register",
        title="Modem is searching but never registers (likely RAT/coverage mismatch)",
        confidence="medium",
        explanation=(
            "The modem reports searching (+CEREG status 2) without progressing to registered. "
            "Common causes: the modem is RAT-locked to a technology the local towers don't broadcast, "
            "or the configured RAT (often NB-IoT) has signal too weak to register. Cat-M and NB-IoT "
            "have different propagation characteristics — NB-IoT has better link budget but requires "
            "explicit NB-IoT support on the tower."
        ),
        evidence=evidence,
        next_actions=[
            'Allow both RATs: AT+QCFG="iotopmode",2,1 (mode 2 = Cat-M & NB-IoT)',
            'Verify scan order: AT+QCFG="nwscanseq",020301,1 (Cat-M first, then NB-IoT, then GSM)',
            "Power-cycle the modem and observe +CEREG transitions over 2–3 minutes.",
            "Cross-check coverage map for the deployment site to confirm the chosen RATs are actually broadcast there.",
        ],
        customer_summary=(
            "Your modem is searching for a network but never quite making it to registered. The most "
            "common cause for this pattern is that the modem is locked to a single radio technology "
            "(Cat-M or NB-IoT) that isn't well-covered at your deployment site. The fix is usually a "
            "small config change to allow both — can you try the AT+QCFG commands above and let me "
            "know how the +CEREG response changes after a power-cycle?"
        ),
    )


def rule_band_locked(log: ParsedLog) -> Hypothesis | None:
    csq = log.find("AT+CSQ")
    csq_99 = csq is not None and any(parse_csq(r) == (99, 99) for r in csq.responses)
    cops_scan = log.find("AT+COPS=?")
    no_networks = False
    if cops_scan:
        for r in cops_scan.responses:
            scan = parse_cops_scan(r)
            if scan:
                no_networks = False
                break
            if r.startswith("+COPS:") and not parse_cops_scan(r):
                no_networks = True

    if not (csq_99 and no_networks):
        return None

    band_ex = log.find('AT+QCFG="band"')
    band_evidence = None
    if band_ex:
        for r in band_ex.responses:
            if r.startswith("+QCFG"):
                band_evidence = r

    return Hypothesis(
        rule_id="band_locked",
        title="Modem finds no networks — band mask or RAT config likely too restrictive",
        confidence="medium",
        explanation=(
            "The modem reports +CSQ 99,99 (no measurement) and +COPS=? returns no usable networks. "
            "This pattern usually indicates a band mask or RAT preference that excludes the bands "
            "the local tower is broadcasting on. A real coverage problem normally still lets the "
            "modem hear *something*."
        ),
        evidence=[
            _evidence(csq.start_line, "+CSQ: 99,99 (no measurement)"),
            _evidence(cops_scan.start_line, "+COPS=? returned no networks"),
            *([_evidence(band_ex.start_line, f"current band config: {band_evidence}")] if band_evidence else []),
        ],
        next_actions=[
            'For US Cat-M1 enable bands 2,4,5,12: AT+QCFG="band",f,400a0e189f,0',
            "For Verizon LTE-M: bands 4 and 13.",
            "For EU LTE-M: bands 3, 8, 20.",
            "After updating, restart the radio with AT+CFUN=1,1 and observe +COPS=? again.",
        ],
        customer_summary=(
            "Your modem is reporting that it can't find any networks at all (the +CSQ: 99,99 plus "
            "the empty +COPS=? response). When this happens the cause is usually a band-mask config "
            "that excludes the bands the local tower actually uses, rather than real coverage. Could "
            "you confirm the current band setting (AT+QCFG=\"band\") and the carrier you're on? I'll "
            "send you the right band-mask values for that region."
        ),
    )


def rule_marginal_signal(log: ParsedLog) -> Hypothesis | None:
    weakest = lowest_rsrp(log)
    if weakest is None or weakest.rsrp_dbm > -115:
        return None

    timeouts_seen = False
    for ex in log.exchanges:
        if not ex.command.upper().startswith(("AT+QPING", "AT+UPING")):
            continue
        for r in ex.responses:
            if "Timeout" in r or "TIMEOUT" in r:
                timeouts_seen = True
        # u-blox UUPING: timeouts also appear in URCs after the command
        for following_ex in log.exchanges:
            for r in following_ex.responses:
                if r.startswith("+UUPINGER:") and "Timeout" in r:
                    timeouts_seen = True

    confidence = "high" if timeouts_seen else "medium"
    return Hypothesis(
        rule_id="marginal_signal",
        title=f"Marginal RF — RSRP at or below LTE-M sensitivity threshold ({weakest.rsrp_dbm:.0f} dBm)",
        confidence=confidence,
        explanation=(
            "RSRP values below -115 dBm sit at the edge of LTE-M sensitivity. The modem will register "
            "in good moments and drop in bad ones, producing intermittent connectivity that looks "
            "like a software issue but isn't. Small environmental changes — a closed door, a parked "
            "vehicle, weather — push the link over the edge."
        ),
        evidence=[
            _evidence(weakest.line_no, f"{weakest.source} reports RSRP {weakest.rsrp_dbm:.0f} dBm (LTE-M sensitivity ~ -118 dBm)"),
            *(["ping responses include timeouts — link is dropping packets at this signal level"] if timeouts_seen else []),
        ],
        next_actions=[
            "Move the antenna OUTSIDE any metal enclosure; even 30 cm vertical change can swing RSRP by 6+ dB.",
            "Use a higher-gain external antenna with a proper SMA/u.FL connector (avoid the stock chip antenna at edge sites).",
            "Verify the antenna feedline isn't damaged or pinched.",
            "For permanent low-coverage sites, consider switching to NB-IoT — better link budget at the cost of throughput.",
        ],
        customer_summary=(
            "Your device is right at the edge of usable signal — RSRP around -118 dBm is just at the "
            "LTE-M sensitivity threshold, which is why connectivity looks intermittent rather than "
            "consistently broken. The fix here is RF, not config: better antenna placement, ideally "
            "outside any metal enclosure, with a proper external antenna for long-term deployments. "
            "Want me to send some antenna-mounting guidelines for your enclosure type?"
        ),
    )


def rule_test_quota_exhausted(log: ParsedLog) -> Hypothesis | None:
    cereg = log.find("AT+CEREG?")
    cgatt = log.find("AT+CGATT?")
    cgact = log.find("AT+CGACT")
    cgpaddr = log.find("AT+CGPADDR")
    if not (cereg and cgatt and cgact and cgpaddr):
        return None

    healthy_attach = (
        any(parse_creg(r) and parse_creg(r)[1] in (1, 5) for r in cereg.responses)
        and any(parse_cgatt(r) == 1 for r in cgatt.responses)
        and not cgact.errored
        and any("CGPADDR" in r and r.count('"') >= 2 for r in cgpaddr.responses)
    )
    if not healthy_attach:
        return None

    # +QPING URCs frequently arrive AFTER the AT+QPING command's OK terminator
    # and end up associated with a different exchange (or no command at all).
    # Walk every response line to find them.
    pings_found = False
    any_success = False
    ping_command_seen = bool(log.find_all("AT+QPING") or log.find_all("AT+UPING"))
    for ex in log.exchanges:
        for r in ex.responses:
            if r.startswith("+QPING:"):
                pings_found = True
                # Per-packet line: "+QPING: <result>,\"<host>\",<bytes>,<time>,<ttl>"
                # Summary line:    "+QPING: <total>,<sent>,<rcv>,<lost>,<min>,<max>,<avg>"
                parts = r.split(",")
                if len(parts) >= 5:
                    head = parts[0].split(":", 1)[1].strip()
                    try:
                        if int(head) == 0:
                            any_success = True
                    except ValueError:
                        pass
            if r.startswith("+UUPING:"):
                pings_found = True
                any_success = True
            if r.startswith("+UUPINGER:"):
                pings_found = True

    if not (ping_command_seen and pings_found and not any_success):
        return None

    ping_ex = log.find_all("AT+QPING") or log.find_all("AT+UPING")
    return Hypothesis(
        rule_id="test_quota_exhausted",
        title="Modem looks healthy but data path is dead — likely TEST-ACTIVATE quota exhausted",
        confidence="medium",
        explanation=(
            "Everything from the modem's perspective looks correct: registered, attached, PDP "
            "context active, IP address allocated. But all data probes fail. This pattern often "
            "means the SIM is in TEST-ACTIVATE state (per Hologram's state machine) and has "
            "exhausted its 100 KB / 10 SMS test allowance, so the carrier still attaches it but "
            "Hologram's core blocks/throttles further data."
        ),
        evidence=[
            _evidence(cgpaddr.start_line, "modem reports a valid IP — attach is healthy"),
            _evidence(ping_ex[0].start_line, "ping probes all fail (data path is broken downstream)"),
        ],
        next_actions=[
            "Look up the SIM in the Hologram dashboard — confirm state is LIVE, not TEST-ACTIVATE.",
            "If state is TEST-ACTIVATE: click Activate to promote it to LIVE and assign a paid plan.",
            "After state change, allow up to 10 minutes for activation to settle, then re-test.",
            "Verify via API: GET /api/1/links/cellular/{linkid} — look for state == 'LIVE'.",
        ],
        customer_summary=(
            "Interesting log — your modem is doing everything right (registered, attached, has an "
            "IP), but data is failing. That combination usually means the issue is on our side, not "
            "yours. The most likely cause is that the SIM is still in TEST-ACTIVATE state and has "
            "used up its testing allowance (100 KB / 10 SMS). Could you check the SIM's state in "
            "the Hologram dashboard and promote it to LIVE if needed? Allow about 10 minutes after "
            "the change, then your data path should clear up."
        ),
    )


_QPING_PER_PACKET_RE = re.compile(r'^\+QPING:\s*(?P<code>-?\d+),"(?P<host>[^"]+)",\d+,\d+,\d+')


def rule_dns_failure(log: ParsedLog) -> Hypothesis | None:
    """Pings to numeric IPs succeed but pings by hostname fail. Indicates the
    IP path is healthy but DNS resolution is broken — typically because the
    device is using carrier-assigned DNS that's blocked, or has stale/hardcoded
    DNS settings."""
    ip_total = ip_success = name_total = name_success = 0
    sample_failed_host: str | None = None
    sample_line_no = 0
    for ex in log.exchanges:
        for r in ex.responses:
            m = _QPING_PER_PACKET_RE.match(r)
            if m is None:
                continue
            code = int(m["code"])
            host = m["host"]
            is_ip = bool(re.match(r"^\d+\.\d+\.\d+\.\d+$", host))
            if is_ip:
                ip_total += 1
                if code == 0:
                    ip_success += 1
            else:
                name_total += 1
                if code == 0:
                    name_success += 1
                else:
                    sample_failed_host = host
                    sample_line_no = ex.start_line
    if not (ip_success > 0 and name_total > 0 and name_success == 0):
        return None
    return Hypothesis(
        rule_id="dns_failure",
        title="IP path healthy, hostname resolution failing — likely DNS misconfiguration",
        confidence="high",
        explanation=(
            f"Pings to numeric IPs succeed ({ip_success}/{ip_total}), but pings to hostnames fail "
            f"({name_success}/{name_total}). This isolates the failure to DNS — the data path is "
            "healthy, the device just can't resolve names. Common causes: the carrier-assigned DNS "
            "servers are blocked, the device firmware has stale/hardcoded DNS settings, or DNS "
            "queries are being filtered upstream of the modem."
        ),
        evidence=[
            f"IP pings: {ip_success}/{ip_total} succeeded",
            f"hostname pings: {name_success}/{name_total} succeeded",
            *([_evidence(sample_line_no, f'first failed hostname: "{sample_failed_host}"')] if sample_failed_host else []),
        ],
        next_actions=[
            'Read current DNS config (Quectel): AT+QIDNSCFG=1',
            'Override with public DNS (Quectel): AT+QIDNSCFG=1,"8.8.8.8","1.1.1.1"',
            "Confirm fix by repeating the hostname ping after the override.",
            "Long-term: have the device firmware retry DNS on failure rather than caching the result indefinitely.",
        ],
        customer_summary=(
            "Good news — your data path is healthy. Pings to public IPs (like 8.8.8.8) come back "
            "fine. The issue is specifically DNS: the device can't resolve hostnames into IPs. "
            "The fastest fix is to point the modem at public DNS servers. For Quectel modules: "
            'AT+QIDNSCFG=1,"8.8.8.8","1.1.1.1" then re-test. If your application caches DNS results '
            "across boots, you may also want to clear that cache so the override takes effect."
        ),
    )


def rule_psm_aggressive(log: ParsedLog) -> Hypothesis | None:
    cpsms = log.find("AT+CPSMS?")
    if not cpsms:
        return None
    enabled = False
    t3324_bits = None
    for r in cpsms.responses:
        info = parse_cpsms(r)
        if info and info["enabled"] == 1:
            enabled = True
            t3324_bits = info.get("t3324_bits")
            break
    if not enabled:
        return None

    cscon = log.find("AT+CSCON?")
    rrc_idle = False
    if cscon:
        for r in cscon.responses:
            if r.startswith("+CSCON:") and ",0" in r and ",1" not in r.split(",", 1)[-1]:
                rrc_idle = True

    return Hypothesis(
        rule_id="psm_aggressive",
        title="Power Saving Mode is enabled — 'device disappearing' is expected behavior",
        confidence="high",
        explanation=(
            "PSM is enabled (+CPSMS: 1) and the modem reports RRC IDLE (+CSCON: 0,0). PSM with a "
            "short active timer (T3324) puts the modem in deep sleep within seconds of inactivity. "
            "From the platform's perspective the device looks 'gone' between paging windows — but "
            "this is the modem doing exactly what it was configured to do."
        ),
        evidence=[
            _evidence(cpsms.start_line, f"+CPSMS: 1 (PSM enabled)" + (f", T3324 bits {t3324_bits}" if t3324_bits else "")),
            *([_evidence(cscon.start_line, "+CSCON: 0,0 (RRC IDLE — modem is in low-power state)")] if rrc_idle else []),
        ],
        next_actions=[
            "For DEBUG: temporarily disable PSM and eDRX:  AT+CPSMS=0   then  AT+CEDRXS=0",
            "Re-test the data path. If problems disappear, PSM is the cause.",
            "For PRODUCTION: tune T3324 (active timer) longer than your application's duty cycle.",
            "If you need downlink within seconds of an event, PSM is incompatible — use eDRX alone or stay always-on.",
        ],
        customer_summary=(
            "Your device isn't actually offline — it's doing exactly what PSM (Power Saving Mode) "
            "tells it to: going to deep sleep between data exchanges to save battery. The current "
            "config has the active timer set very short, which is why the device looks 'missing' "
            "from the platform side most of the time. If your application needs near-real-time "
            "downlink, we'll want to either tune the PSM timers up or disable PSM entirely. What's "
            "the device's expected duty cycle?"
        ),
    )


def rule_euicc_wrong_profile(log: ParsedLog) -> Hypothesis | None:
    qesim_list = log.find('AT+QESIM="list"')
    if not qesim_list:
        return None
    profiles = []
    for r in qesim_list.responses:
        info = parse_qesim_list(r)
        if info:
            profiles.append(info)
    if len(profiles) < 2:
        return None
    active = [p for p in profiles if p["active"]]
    inactive = [p for p in profiles if not p["active"]]
    if not (active and inactive):
        return None

    csq = log.find("AT+CSQ")
    no_signal = csq is not None and any(parse_csq(r) == (99, 99) for r in csq.responses)
    cereg = log.find("AT+CEREG?")
    not_registered = False
    if cereg:
        for r in cereg.responses:
            v = parse_creg(r)
            if v and v[1] == 2:
                not_registered = True

    if not (no_signal or not_registered):
        return None

    return Hypothesis(
        rule_id="euicc_wrong_profile",
        title="eUICC has multiple profiles but the active one cannot connect — fallback didn't trigger",
        confidence="high",
        explanation=(
            "The modem reports multiple installed profiles on the eUICC, with one active and at "
            "least one inactive but provisioned. The active profile is failing to register (no "
            "signal or stuck searching), but the device hasn't switched to the alternative. This "
            "is exactly the failure mode Conductor's policy-based failover is designed to prevent."
        ),
        evidence=[
            _evidence(qesim_list.start_line, f"eUICC has {len(profiles)} profiles ({len(active)} active, {len(inactive)} inactive)"),
            *([_evidence(csq.start_line, "+CSQ: 99,99 on active profile")] if no_signal else []),
            *([_evidence(cereg.start_line, "active profile stuck at +CEREG status 2")] if not_registered else []),
        ],
        next_actions=[
            "IMMEDIATE: from the Hologram dashboard SIM page, manually switch the active profile.",
            "OR via Conductor API:  POST /conductor/v1/sims/{iccid}/profile/switch  with the target index.",
            "Wait 30–60 s for the eUICC to apply the switch and re-attach on the new profile.",
            "FLEET-LEVEL FIX: define a Conductor failover policy — e.g., switch profile after 5 minutes of failed registration. Resolves this fault class for all current and future SIMs.",
        ],
        customer_summary=(
            "Good news — your SIM has another profile already provisioned that should work where "
            "this one isn't. The bad news is that without an automated failover policy, the device "
            "stays stuck on the wrong profile until something switches it. I can trigger a manual "
            "switch from the dashboard right now to get this device online; longer-term we should "
            "look at a Conductor policy so this happens automatically across your fleet whenever a "
            "SIM can't register on its active profile. Would you like to start with the manual fix "
            "and then talk through the policy options?"
        ),
    )


_RULES: list[Rule] = [
    rule_modem_unresponsive,
    rule_sim_pin_locked,
    rule_sim_not_inserted,
    rule_wrong_apn,
    rule_roaming_denied,
    rule_registration_denied_hss,
    rule_searching_no_register,
    rule_band_locked,
    rule_marginal_signal,
    rule_dns_failure,
    rule_test_quota_exhausted,
    rule_psm_aggressive,
    rule_euicc_wrong_profile,
]
