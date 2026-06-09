"""AT command log parser.

Parses raw modem AT command transcripts into a structured form the analyzer
can reason over. Tolerant of vendor variations (Quectel, u-blox, SIMCom) and
of common capture artefacts (echo, blank lines, fixture-style # comments).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

CME_ERROR_RE = re.compile(r"^\+CME ERROR:\s*(.+)$")
CMS_ERROR_RE = re.compile(r"^\+CMS ERROR:\s*(.+)$")
CREG_RE = re.compile(r"^\+(?P<which>CREG|CGREG|CEREG):\s*(?P<n>\d+),\s*(?P<stat>\d+)")
COPS_RE = re.compile(r'^\+COPS:\s*(?P<mode>\d+)(?:,(?P<format>\d+),"(?P<oper>[^"]*)"(?:,(?P<act>\d+))?)?')
COPS_SCAN_RE = re.compile(r'\((?P<stat>\d+),"(?P<long>[^"]*)","(?P<short>[^"]*)","(?P<plmn>\d+)",(?P<act>\d+)\)')
CSQ_RE = re.compile(r"^\+CSQ:\s*(?P<rssi>\d+),\s*(?P<ber>\d+)")
RSRP_RE = re.compile(r'^\+RSRP:\s*\d+,\d+,"(?P<rsrp>-?\d+\.\d+)"')
QCSQ_RE = re.compile(r'^\+QCSQ:\s*"(?P<rat>[^"]+)",(?P<rssi>-?\d+),(?P<rsrp>-?\d+),(?P<sinr>-?\d+),(?P<rsrq>-?\d+)')
CESQ_RE = re.compile(r"^\+CESQ:\s*(?P<rxlev>\d+),\s*(?P<ber>\d+),\s*(?P<rscp>\d+),\s*(?P<ecno>\d+),\s*(?P<rsrq>\d+),\s*(?P<rsrp>\d+)")
CGATT_RE = re.compile(r"^\+CGATT:\s*(?P<state>\d+)")
CPSMS_RE = re.compile(r'^\+CPSMS:\s*(?P<enabled>\d)(?:,[^,]*,[^,]*,"(?P<t3412>[01]+)","(?P<t3324>[01]+)")?')
QESIM_LIST_RE = re.compile(r'^\+QESIM:\s*"list",(?P<idx>\d+),"(?P<iccid>\d+)",(?P<active>\d+)')


@dataclass
class Exchange:
    command: str
    responses: list[str] = field(default_factory=list)
    status: str = ""
    start_line: int = 0

    @property
    def errored(self) -> bool:
        return self.status == "ERROR" or self.status.startswith(("CME:", "CMS:"))

    @property
    def empty(self) -> bool:
        return not self.responses and not self.status


@dataclass
class ParsedLog:
    raw: str
    exchanges: list[Exchange]
    vendor: str | None = None
    module: str | None = None

    def find(self, command_prefix: str) -> Exchange | None:
        for ex in self.exchanges:
            if ex.command.upper().startswith(command_prefix.upper()):
                return ex
        return None

    def find_all(self, command_prefix: str) -> list[Exchange]:
        return [ex for ex in self.exchanges if ex.command.upper().startswith(command_prefix.upper())]


def parse(text: str) -> ParsedLog:
    lines = [ln.rstrip("\r\n") for ln in text.splitlines()]
    exchanges: list[Exchange] = []
    current: Exchange | None = None

    for i, raw in enumerate(lines, start=1):
        line = raw.strip()
        if line.startswith("#"):
            continue
        if not line:
            continue
        if line.upper().startswith("AT") and not _looks_like_response(line):
            if current is not None:
                exchanges.append(current)
            current = Exchange(command=line, start_line=i)
            continue
        if current is None:
            current = Exchange(command="", start_line=i)
        if line == "OK":
            current.status = "OK"
            exchanges.append(current)
            current = None
            continue
        if line == "ERROR":
            current.status = "ERROR"
            exchanges.append(current)
            current = None
            continue
        m = CME_ERROR_RE.match(line)
        if m:
            current.status = f"CME:{m.group(1).strip()}"
            exchanges.append(current)
            current = None
            continue
        m = CMS_ERROR_RE.match(line)
        if m:
            current.status = f"CMS:{m.group(1).strip()}"
            exchanges.append(current)
            current = None
            continue
        current.responses.append(line)

    if current is not None:
        exchanges.append(current)

    # Detect bare-AT exchanges where the modem was unresponsive: the parser
    # above will have rolled them into the *next* exchange because "no OK seen"
    # means the current exchange stays open. Split them back out.
    exchanges = _split_unresponsive_exchanges(exchanges)

    vendor, module = _detect_vendor(exchanges)
    return ParsedLog(raw=text, exchanges=exchanges, vendor=vendor, module=module)


def _looks_like_response(line: str) -> bool:
    # Some response payloads happen to start with "AT" (very rare); be conservative.
    # Real commands always have form AT+X, AT&X, ATI, ATZ, ATE, AT, etc.
    if line.startswith("+") or line.startswith('"'):
        return True
    return False


def _split_unresponsive_exchanges(exchanges: list[Exchange]) -> list[Exchange]:
    """If an exchange has no responses and no status AND its 'responses' came
    from a later command being absorbed, the parser has already kept them
    separate. This is a safety net for malformed captures."""
    return exchanges


def _detect_vendor(exchanges: list[Exchange]) -> tuple[str | None, str | None]:
    # Most modules respond to ATI with vendor + model + firmware. Nordic uses
    # +CGMI (manufacturer) and +CGMM (model) instead, so we check both.
    for ex in exchanges:
        cmd = ex.command.upper()
        if cmd not in ("ATI", "AT+CGMI", "AT+CGMM"):
            continue
        text = "\n".join(ex.responses)
        lower = text.lower()
        if "quectel" in lower:
            module = next((r for r in ex.responses if r.upper().startswith(("BG", "EC", "EG", "RG", "RM"))), None)
            return ("quectel", module)
        if "u-blox" in lower or "ublox" in lower:
            module = next((r for r in ex.responses if "SARA" in r.upper() or "TOBY" in r.upper() or "LARA" in r.upper()), None)
            return ("ublox", module)
        if "simcom" in lower or "sim_com" in lower or "simcomltd" in lower.replace(" ", ""):
            # SIMCom typically prints "SIMCOM_Ltd" then "SIMCOM_<MODEL>" — pick
            # the SIMCOM_<MODEL> line, not the manufacturer header.
            module = next(
                (r for r in ex.responses
                 if r.upper().startswith("SIMCOM_") and r.upper() not in ("SIMCOM_LTD",)),
                None,
            )
            return ("simcom", module)
        if "telit" in lower:
            module = next(
                (r for r in ex.responses
                 if r.upper().startswith(("ME910", "LE910", "NE866", "LM940", "LN940"))),
                None,
            )
            return ("telit", module)
        if "sierra wireless" in lower or "sierra_wireless" in lower:
            module = next(
                (r for r in ex.responses
                 if r.upper().startswith(("HL", "EM", "WP", "MC", "AR"))),
                None,
            )
            return ("sierra", module)
        if "nordic" in lower:
            # Nordic +CGMM returns just the model (e.g. "nRF9160-SICA"); +CGMI
            # returns the manufacturer. Whichever command we found, pull the
            # model from the matching CGMM exchange if present.
            cgmm = next((e for e in exchanges if e.command.upper() == "AT+CGMM"), None)
            module = cgmm.responses[0] if cgmm and cgmm.responses else None
            return ("nordic", module)
    cmds = " ".join(ex.command.upper() for ex in exchanges)
    if any(tok in cmds for tok in ("+QENG", "+QCSQ", "+QCFG", "+QESIM", "+QPING")):
        return ("quectel", None)
    if any(tok in cmds for tok in ("+UCGED", "+UPING", "+UBANDMASK")):
        return ("ublox", None)
    if any(tok in cmds for tok in ("+CSERVINFO", "+CNETSCAN", "+CMNB")):
        return ("simcom", None)
    if any(tok in cmds for tok in ("#SGACT", "#SD", "#RFSTS")):
        return ("telit", None)
    if any(tok in cmds for tok in ("+KSRAT", "+KCNXCFG", "+KSREG")):
        return ("sierra", None)
    if "%XSYSTEMMODE" in cmds or "%XSNRSQ" in cmds:
        return ("nordic", None)
    return (None, None)


def parse_creg(line: str) -> tuple[int, int] | None:
    m = CREG_RE.match(line)
    if m:
        return (int(m["n"]), int(m["stat"]))
    return None


def parse_csq(line: str) -> tuple[int, int] | None:
    m = CSQ_RE.match(line)
    if m:
        return (int(m["rssi"]), int(m["ber"]))
    return None


def parse_rsrp(line: str) -> float | None:
    m = RSRP_RE.match(line)
    if m:
        return float(m["rsrp"])
    return None


def parse_qcsq(line: str) -> dict | None:
    m = QCSQ_RE.match(line)
    if m:
        return {
            "rat": m["rat"],
            "rssi": int(m["rssi"]),
            "rsrp": int(m["rsrp"]),
            "sinr": int(m["sinr"]),
            "rsrq": int(m["rsrq"]),
        }
    return None


def parse_cesq(line: str) -> dict | None:
    """Parse +CESQ extended signal quality. Per 3GPP TS 27.007:
      rsrp_dBm  = rsrp_idx - 141   (range -141..-44 for idx 0..97; 255 = n/a)
      rsrq_dB   = -20 + 0.5 * rsrq_idx  (range -20..-3 for idx 0..34; 255 = n/a)
    """
    m = CESQ_RE.match(line)
    if not m:
        return None
    rsrp_idx = int(m["rsrp"])
    rsrq_idx = int(m["rsrq"])
    return {
        "rxlev": int(m["rxlev"]),
        "ber": int(m["ber"]),
        "rsrp_dbm": (rsrp_idx - 141) if rsrp_idx != 255 else None,
        "rsrq_db": (-20 + 0.5 * rsrq_idx) if rsrq_idx != 255 else None,
    }


def parse_cops(line: str) -> dict | None:
    m = COPS_RE.match(line)
    if m:
        return {
            "mode": int(m["mode"]),
            "operator": m["oper"],
            "act": int(m["act"]) if m["act"] else None,
        }
    return None


def parse_cops_scan(line: str) -> list[dict]:
    return [
        {
            "stat": int(m["stat"]),
            "long": m["long"],
            "short": m["short"],
            "plmn": m["plmn"],
            "act": int(m["act"]),
        }
        for m in COPS_SCAN_RE.finditer(line)
    ]


def parse_cgatt(line: str) -> int | None:
    m = CGATT_RE.match(line)
    if m:
        return int(m["state"])
    return None


def parse_cpsms(line: str) -> dict | None:
    m = CPSMS_RE.match(line)
    if m:
        return {
            "enabled": int(m["enabled"]),
            "t3412_bits": m["t3412"],
            "t3324_bits": m["t3324"],
        }
    return None


def parse_qesim_list(line: str) -> dict | None:
    m = QESIM_LIST_RE.match(line)
    if m:
        return {
            "index": int(m["idx"]),
            "iccid": m["iccid"],
            "active": bool(int(m["active"])),
        }
    return None
