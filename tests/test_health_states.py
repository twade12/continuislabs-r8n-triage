"""Tests for the tightened health-classification logic.

The old behaviour returned `healthy` whenever attach looked fine; the new
behaviour requires explicit application-layer success and falls back to a
medium-confidence `appears_attached` hypothesis when attach is fine but no
probe is captured.
"""
from hologram_cli.triage import analyze, parse


HEALTHY_ATTACH_BASE = """
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
"""


def test_attach_with_qping_success_is_healthy():
    text = HEALTHY_ATTACH_BASE + (
        'AT+QPING=1,"8.8.8.8",1,1\n'
        'OK\n'
        '+QPING: 0,"8.8.8.8",32,42,255\n'
        '+QPING: 0,1,1,0,42,42,42\n'
    )
    diag = analyze(parse(text))
    assert diag.health == "healthy"
    assert diag.hypotheses[0].rule_id == "healthy_baseline"


def test_attach_with_socket_connect_is_healthy():
    text = HEALTHY_ATTACH_BASE + 'AT#SD=1,0,443,"hologram.io",0,0\nOK\nCONNECT\n'
    diag = analyze(parse(text))
    assert diag.health == "healthy"


def test_attach_without_app_layer_probe_is_degraded():
    text = HEALTHY_ATTACH_BASE
    diag = analyze(parse(text))
    assert diag.health == "degraded"
    assert diag.hypotheses[0].rule_id == "appears_attached"
    assert diag.hypotheses[0].confidence == "medium"


def test_no_attach_no_probe_is_unknown():
    text = "AT\nOK\nATI\nQuectel\nBG96\nOK\n"
    diag = analyze(parse(text))
    assert diag.health == "degraded"
    assert diag.hypotheses[0].rule_id == "unknown"
