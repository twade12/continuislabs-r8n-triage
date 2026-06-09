"""Tests for the AT command reference + response decoder."""
import pytest

from hologram_cli.triage import at_reference


def test_lookup_canonical_name():
    cmd = at_reference.lookup("+CEREG")
    assert cmd is not None
    assert cmd.vendor == "3gpp"


def test_lookup_with_at_prefix():
    cmd = at_reference.lookup("AT+QIOPEN")
    assert cmd is not None
    assert cmd.vendor == "quectel"


def test_lookup_lowercase_normalized():
    cmd = at_reference.lookup("at+cgpaddr")
    assert cmd is not None


def test_lookup_unknown_returns_none():
    assert at_reference.lookup("+ZZZNONEXISTENT") is None


def test_search_finds_ping_commands():
    hits = at_reference.search("ping")
    names = {c.name for c in hits}
    assert "+QPING" in names
    assert "+UPING" in names


def test_search_empty_query_returns_nothing():
    assert at_reference.search("") == []


def test_list_commands_filtered_by_vendor():
    cmds = at_reference.list_commands(vendor="quectel")
    assert all(c.vendor == "quectel" for c in cmds)
    assert any(c.name == "+QPING" for c in cmds)


def test_decode_cereg_status_3():
    out = at_reference.decode_response("+CEREG: 0,3")
    assert out is not None
    assert "registration denied" in out.lower()


def test_decode_cereg_status_1_healthy():
    out = at_reference.decode_response("+CEREG: 0,1")
    assert out is not None
    assert "registered, home network" in out.lower()


def test_decode_csq_excellent():
    out = at_reference.decode_response("+CSQ: 21,99")
    assert out is not None
    assert "excellent" in out.lower() or "good" in out.lower()


def test_decode_csq_unknown():
    out = at_reference.decode_response("+CSQ: 99,99")
    assert out is not None
    assert "no signal" in out.lower()


def test_decode_cesq_marginal_rsrp():
    # idx 23 = -118 dBm; should call out the sensitivity edge
    out = at_reference.decode_response("+CESQ: 99,99,255,255,15,23")
    assert out is not None
    assert "-118 dBm" in out
    assert "sensitivity" in out.lower()


def test_decode_cgpaddr_cgnat_note():
    out = at_reference.decode_response('+CGPADDR: 1,"100.66.18.214"')
    assert out is not None
    assert "100.66.18.214" in out
    assert "carrier-grade NAT" in out


def test_decode_cgpaddr_non_cgnat_no_note():
    out = at_reference.decode_response('+CGPADDR: 1,"10.0.0.5"')
    assert out is not None
    assert "10.0.0.5" in out
    assert "carrier-grade NAT" not in out


def test_decode_cops_scan_with_forbidden():
    line = '+COPS: (3,"O2 - UK","O2","23410",7),(2,"EE","EE","23430",7)'
    out = at_reference.decode_response(line)
    assert out is not None
    assert "FORBIDDEN" in out
    assert "O2 - UK" in out


def test_decode_cme_error_known_code():
    out = at_reference.decode_response("+CME ERROR: 30")
    assert out is not None
    assert "no network service" in out.lower()


def test_decode_cme_error_sim_not_inserted():
    out = at_reference.decode_response("+CME ERROR: 10")
    assert out is not None
    assert "sim not inserted" in out.lower()


def test_decode_qping_success():
    out = at_reference.decode_response('+QPING: 0,"8.8.8.8",32,42,255')
    assert out is not None
    assert "success" in out.lower()


def test_decode_qping_dns_failure():
    out = at_reference.decode_response('+QPING: 565,"hologram.io",32,0,0')
    assert out is not None
    assert "dns" in out.lower()


def test_decode_unknown_response_returns_none():
    assert at_reference.decode_response("+SOMETHING: weird,123") is None


def test_decode_strips_whitespace():
    out = at_reference.decode_response("  +CEREG: 0,1  ")
    assert out is not None


@pytest.mark.parametrize("name", ["+CEREG", "+CGREG", "+CREG", "+CSQ", "+CESQ", "+CGPADDR", "+COPS",
                                    "+CGATT", "+CPSMS", "+CPIN", "+QPING", "+CME ERROR"])
def test_every_decoder_handles_its_command(name):
    """Smoke test: each registered decoder must be present in the lookup table."""
    assert name in at_reference._DECODERS
