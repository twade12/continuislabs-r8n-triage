"""Tests for the vendor-agnostic signal/RAT adapter."""
from hologram_cli.triage import lowest_rsrp, parse, rat_lock_mode


def test_lowest_rsrp_from_qcsq():
    text = "AT+QCSQ\n+QCSQ: \"CAT-M1\",-79,-92,142,-9\nOK\n"
    log = parse(text)
    r = lowest_rsrp(log)
    assert r is not None
    assert r.rsrp_dbm == -92.0
    assert r.source == "+QCSQ"


def test_lowest_rsrp_from_cesq_index_conversion():
    # CESQ rsrp index 23 corresponds to -118 dBm: rsrp_dBm = idx - 141
    text = "AT+CESQ\n+CESQ: 99,99,255,255,15,23\nOK\n"
    log = parse(text)
    r = lowest_rsrp(log)
    assert r is not None
    assert r.rsrp_dbm == -118.0
    assert r.source == "+CESQ"


def test_lowest_rsrp_from_rsrp_urc():
    text = 'AT+UCGED=5\n+RSRP: 1,2850,"-118.00"\nOK\n'
    log = parse(text)
    r = lowest_rsrp(log)
    assert r is not None
    assert r.rsrp_dbm == -118.0
    assert r.source == "+RSRP"


def test_lowest_rsrp_picks_weakest_across_vendors():
    text = (
        "AT+QCSQ\n+QCSQ: \"CAT-M1\",-79,-100,142,-9\nOK\n"
        "AT+CESQ\n+CESQ: 99,99,255,255,15,23\nOK\n"  # idx 23 = -118 dBm (weaker)
    )
    log = parse(text)
    r = lowest_rsrp(log)
    assert r is not None
    assert r.rsrp_dbm == -118.0


def test_lowest_rsrp_returns_none_when_no_signal_data():
    text = "AT+CSQ\n+CSQ: 99,99\nOK\n"
    log = parse(text)
    assert lowest_rsrp(log) is None


def test_rat_lock_quectel_iotopmode_nbiot():
    text = "AT+QCFG=\"iotopmode\"\n+QCFG: \"iotopmode\",1\nOK\n"
    log = parse(text)
    r = rat_lock_mode(log)
    assert r is not None
    assert r[0] == "nb-iot"


def test_rat_lock_quectel_iotopmode_catm():
    text = "AT+QCFG=\"iotopmode\"\n+QCFG: \"iotopmode\",0\nOK\n"
    log = parse(text)
    r = rat_lock_mode(log)
    assert r is not None
    assert r[0] == "cat-m"


def test_rat_lock_quectel_mixed_returns_none():
    text = "AT+QCFG=\"iotopmode\"\n+QCFG: \"iotopmode\",2\nOK\n"
    log = parse(text)
    assert rat_lock_mode(log) is None


def test_rat_lock_simcom_cmnb_nbiot():
    text = "AT+CMNB?\n+CMNB: 2\nOK\n"
    log = parse(text)
    r = rat_lock_mode(log)
    assert r is not None
    assert r[0] == "nb-iot"


def test_rat_lock_ublox_urat_nbiot():
    text = "AT+URAT?\n+URAT: 8\nOK\n"
    log = parse(text)
    r = rat_lock_mode(log)
    assert r is not None
    assert r[0] == "nb-iot"


def test_rat_lock_nordic_xsystemmode_nbiot():
    text = "AT%XSYSTEMMODE?\n%XSYSTEMMODE: 0,1,0,0\nOK\n"
    log = parse(text)
    r = rat_lock_mode(log)
    assert r is not None
    assert r[0] == "nb-iot"


def test_rat_lock_returns_none_when_no_rat_command():
    text = "AT+CSQ\n+CSQ: 21,99\nOK\n"
    log = parse(text)
    assert rat_lock_mode(log) is None
