from pathlib import Path

from ibae.canonical import canonical_json
from ibae.supervisor import RecoveryClass
from ibae.supervisor_conformance import v0_6a_reference_fixture


def test_v0_6a_frozen_reference_fixture():
    fixture = v0_6a_reference_fixture()
    checked_in = Path(__file__).parents[1] / "fixtures/v0.6A/supervisor-recovery-reference.json"
    assert canonical_json(fixture) + "\n" == checked_in.read_text()
    assert {item["classification"] for item in fixture["recovery_classifications"]} == {item.value for item in RecoveryClass}
    assert fixture["fresh_session_equivalent"] is True
    assert fixture["rejection_state_neutral"] is True
    assert fixture["source_bound_native_checks"] is True
    assert fixture["live_recovery_verified"] is False


def test_v0_6a_independent_native_sessions_render_identically():
    assert v0_6a_reference_fixture() == v0_6a_reference_fixture()
