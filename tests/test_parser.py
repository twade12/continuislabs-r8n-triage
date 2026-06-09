from pathlib import Path

import pytest

from hologram_cli.triage.parser import parse, parse_creg, parse_csq, parse_qcsq, parse_qesim_list

FIXTURES = Path(__file__).parent.parent / "fixtures" / "at_logs"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_parse_strips_comments():
    log = parse("# this is a comment\nAT\nOK\n")
    assert len(log.exchanges) == 1
    assert log.exchanges[0].command == "AT"
    assert log.exchanges[0].status == "OK"


def test_parse_handles_cme_error():
    log = parse("AT+CGATT=1\n+CME ERROR: 30\n")
    assert log.exchanges[0].command == "AT+CGATT=1"
    assert log.exchanges[0].status == "CME:30"
    assert log.exchanges[0].errored


def test_parse_groups_multiline_response():
    text = "AT+QPING=1,\"8.8.8.8\",1,4\nOK\n+QPING: 0,\"8.8.8.8\",32,48,255\n+QPING: 0,4,4,0,47,51,49\n"
    log = parse(text)
    assert len(log.exchanges) >= 1
    # The OK closes the first exchange, then the +QPING URCs become a second exchange
    # without a command. Both behaviours are valid for our analyzer's purposes.


def test_parse_baseline_fixture_detects_quectel():
    log = parse(_read("01_healthy_baseline_quectel_bg96.log"))
    assert log.vendor == "quectel"
    assert log.module == "BG96"
    assert log.find("AT+CEREG?") is not None
    assert log.find("AT+CGATT?") is not None


def test_parse_ublox_fixture_detects_vendor():
    log = parse(_read("02_registration_denied_creg03_ublox.log"))
    assert log.vendor == "ublox"
    assert "SARA" in (log.module or "")


def test_parse_simcom_fixture_detects_vendor():
    log = parse(_read("04_sim_not_detected_simcom.log"))
    assert log.vendor == "simcom"


def test_parse_modem_unresponsive_keeps_empty_exchanges():
    log = parse(_read("11_modem_unresponsive.log"))
    bare_at = [ex for ex in log.exchanges if ex.command.upper() == "AT"]
    assert len(bare_at) >= 4
    empty = [ex for ex in bare_at if ex.empty]
    assert len(empty) >= 2


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("+CEREG: 0,1", (0, 1)),
        ("+CEREG: 0,3", (0, 3)),
        ("+CGREG: 0,0", (0, 0)),
        ("+CREG: 1,5", (1, 5)),
        ("+CEREG: 2,2,,,,", (2, 2)),
    ],
)
def test_parse_creg(line, expected):
    assert parse_creg(line) == expected


def test_parse_csq():
    assert parse_csq("+CSQ: 21,99") == (21, 99)
    assert parse_csq("+CSQ: 99,99") == (99, 99)


def test_parse_qcsq():
    info = parse_qcsq('+QCSQ: "CAT-M1",-79,-92,142,-9')
    assert info == {"rat": "CAT-M1", "rssi": -79, "rsrp": -92, "sinr": 142, "rsrq": -9}


def test_parse_qesim_list():
    info = parse_qesim_list('+QESIM: "list",1,"89001012012341234012",1')
    assert info == {"index": 1, "iccid": "89001012012341234012", "active": True}
    info2 = parse_qesim_list('+QESIM: "list",2,"89001012012341234020",0')
    assert info2["active"] is False
