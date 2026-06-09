"""Vendor-agnostic signal and RAT helpers.

The diagnosis rules should reason about what the modem reports, not about
which vendor reported it. This module normalises the various ways different
modules express the same fact:

  - RSRP: Quectel +QCSQ vs u-blox +RSRP/+UCGED vs standard +CESQ vs Nordic +CESQ
  - RAT mode lock: Quectel +QCFG"iotopmode" vs SIMCom +CMNB vs u-blox +URAT
    vs Nordic %XSYSTEMMODE

Rules call the helpers below; the helpers handle vendor differences in one
place. Adding a new module is a one-place change.
"""
from __future__ import annotations

from dataclasses import dataclass

from hologram_cli.triage.parser import (
    ParsedLog,
    parse_cesq,
    parse_qcsq,
    parse_rsrp,
)


@dataclass
class RsrpReading:
    rsrp_dbm: float
    line_no: int
    source: str  # "+QCSQ" | "+RSRP" | "+CESQ"


def lowest_rsrp(log: ParsedLog) -> RsrpReading | None:
    """Find the weakest RSRP value reported anywhere in the log, regardless of
    which command produced it. Returns None if no RSRP measurement was found."""
    candidates: list[RsrpReading] = []
    for ex in log.exchanges:
        for r in ex.responses:
            v = parse_rsrp(r)
            if v is not None:
                candidates.append(RsrpReading(v, ex.start_line, "+RSRP"))
                continue
            qc = parse_qcsq(r)
            if qc is not None and qc.get("rsrp") is not None:
                candidates.append(RsrpReading(float(qc["rsrp"]), ex.start_line, "+QCSQ"))
                continue
            ce = parse_cesq(r)
            if ce is not None and ce.get("rsrp_dbm") is not None:
                candidates.append(RsrpReading(float(ce["rsrp_dbm"]), ex.start_line, "+CESQ"))
                continue
    if not candidates:
        return None
    return min(candidates, key=lambda c: c.rsrp_dbm)


def rat_lock_mode(log: ParsedLog) -> tuple[str, int] | None:
    """Detect single-RAT lock across vendors.

    Returns (mode, line_no) where mode is "nb-iot" | "cat-m" | "lte-cat-m-only"
    when the modem is restricted to a single technology in a way that's likely
    to cause registration failures, or None when not RAT-locked or not reported.

    Multi-mode (Cat-M + NB-IoT) configurations return None — those aren't
    inherent failure causes.
    """
    # Quectel: AT+QCFG="iotopmode"  — 0=Cat-M only, 1=NB-IoT only, 2=both
    qcfg = log.find('AT+QCFG="iotopmode"')
    if qcfg is not None:
        for r in qcfg.responses:
            if r.startswith('+QCFG: "iotopmode"'):
                parts = r.split(",")
                if len(parts) >= 2:
                    try:
                        mode = int(parts[1].strip())
                    except ValueError:
                        break
                    if mode == 1:
                        return ("nb-iot", qcfg.start_line)
                    if mode == 0:
                        return ("cat-m", qcfg.start_line)
                    return None

    # SIMCom: AT+CMNB?  — 1=Cat-M, 2=NB-IoT, 3=both
    cmnb = log.find("AT+CMNB?")
    if cmnb is not None:
        for r in cmnb.responses:
            if r.startswith("+CMNB:"):
                try:
                    mode = int(r.split(":", 1)[1].strip().split(",")[0])
                except (ValueError, IndexError):
                    break
                if mode == 2:
                    return ("nb-iot", cmnb.start_line)
                if mode == 1:
                    return ("cat-m", cmnb.start_line)
                return None

    # u-blox: AT+URAT?  — 7=LTE Cat-M1, 8=NB-IoT (single value = locked, list = preference)
    urat = log.find("AT+URAT?")
    if urat is not None:
        for r in urat.responses:
            if r.startswith("+URAT:"):
                rats = [s.strip() for s in r.split(":", 1)[1].split(",")]
                if rats == ["7"]:
                    return ("cat-m", urat.start_line)
                if rats == ["8"]:
                    return ("nb-iot", urat.start_line)
                return None

    # Nordic: AT%XSYSTEMMODE? — params: <ltem>,<nbiot>,<gnss>,<lte_pref>
    xsysmode = log.find("AT%XSYSTEMMODE?")
    if xsysmode is not None:
        for r in xsysmode.responses:
            if r.startswith("%XSYSTEMMODE:"):
                parts = [s.strip() for s in r.split(":", 1)[1].split(",")]
                if len(parts) >= 2:
                    ltem, nbiot = parts[0], parts[1]
                    if ltem == "0" and nbiot == "1":
                        return ("nb-iot", xsysmode.start_line)
                    if ltem == "1" and nbiot == "0":
                        return ("cat-m", xsysmode.start_line)
                return None

    return None
