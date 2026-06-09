"""End-to-end tests: each fixture must produce its expected diagnosis."""
from pathlib import Path

import pytest

from hologram_cli.triage import analyze, parse

FIXTURES = Path(__file__).parent.parent / "fixtures" / "at_logs"

# fixture filename -> expected top hypothesis rule_id
EXPECTED = {
    # Original fixture set (Quectel-heavy, plus u-blox SARA-R5/R412 and SIMCom 7600).
    "01_healthy_baseline_quectel_bg96.log": "healthy_baseline",
    "02_registration_denied_creg03_ublox.log": "registration_denied_hss",
    "03_searching_stuck_quectel_bg95.log": "searching_no_register",
    "04_sim_not_detected_simcom.log": "sim_not_inserted",
    "05_wrong_apn_quectel.log": "wrong_apn",
    "06_marginal_signal_ublox.log": "marginal_signal",
    "07_roaming_denied_china.log": "roaming_denied",
    "08_band_locked_quectel.log": "band_locked",
    "09_test_quota_exhausted_quectel.log": "test_quota_exhausted",
    "10_psm_too_aggressive_quectel.log": "psm_aggressive",
    "11_modem_unresponsive.log": "modem_unresponsive",
    "12_euicc_fallback_not_triggered.log": "euicc_wrong_profile",
    # Cross-vendor generalisation set (Telit, Sierra, Nordic, SIMCom 7080G,
    # u-blox LARA-R6, Quectel EC25/EG25). Validates the vendor-agnostic
    # signal/RAT adapter and the new sim_pin_locked / dns_failure rules.
    "13_healthy_telit_me910c1.log": "healthy_baseline",
    "14_registration_denied_sierra_hl7800_brazil.log": "registration_denied_hss",
    "15_sim_pin_locked_quectel_eg25.log": "sim_pin_locked",
    "16_wrong_apn_simcom.log": "wrong_apn",
    "17_searching_nbiot_simcom_sim7080g.log": "searching_no_register",
    "18_band_locked_ublox_lara_r6.log": "band_locked",
    "19_marginal_signal_nordic_nrf9160.log": "marginal_signal",
    "20_roaming_denied_telit_uk.log": "roaming_denied",
    "21_psm_aggressive_simcom_sim7080g.log": "psm_aggressive",
    "22_dns_failure_quectel_ec25.log": "dns_failure",
    "23_modem_unresponsive_telit.log": "modem_unresponsive",
}


@pytest.mark.parametrize(("filename", "expected_rule"), list(EXPECTED.items()))
def test_fixture_produces_expected_diagnosis(filename, expected_rule):
    text = (FIXTURES / filename).read_text()
    log = parse(text)
    diag = analyze(log)
    assert diag.hypotheses, f"{filename}: no hypotheses produced"
    top_ids = [h.rule_id for h in diag.hypotheses]
    assert expected_rule in top_ids, (
        f"{filename}: expected {expected_rule} in top hypotheses, got {top_ids}"
    )
    assert diag.hypotheses[0].rule_id == expected_rule, (
        f"{filename}: expected {expected_rule} as #1 hypothesis, got {top_ids[0]}"
    )


def test_healthy_log_marks_health_healthy():
    log = parse((FIXTURES / "01_healthy_baseline_quectel_bg96.log").read_text())
    diag = analyze(log)
    assert diag.health == "healthy"


def test_broken_log_marks_health_broken():
    log = parse((FIXTURES / "04_sim_not_detected_simcom.log").read_text())
    diag = analyze(log)
    assert diag.health == "broken"
    assert any(h.confidence == "high" for h in diag.hypotheses)
