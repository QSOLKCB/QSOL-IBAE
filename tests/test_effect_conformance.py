"""Deterministic closed effect replay preserves the simulation boundary."""
import json
from pathlib import Path

import pytest

from ibae.canonical import canonical_json, domain_fingerprint
from ibae.effect_conformance import reference_effect_inputs, replay_effect_inputs, v0_6d_reference_fixture


def test_golden_inputs_replay_to_exact_native_effect_fixture():
    root = Path(__file__).resolve().parents[1] / "fixtures" / "v0.6D"
    inputs = json.loads((root / "effect-inputs.json").read_text())
    assert canonical_json(inputs) == canonical_json(reference_effect_inputs())
    result = replay_effect_inputs(inputs)
    assert canonical_json(result) == (root / "governed-effects-reference.json").read_text().strip()
    assert result["scenario_count"] == 18
    assert result["live_effects_enabled"] is False
    assert result["live_recovery_verified"] is False
    assert result["external_mutations"] == 0
    claimed = result.pop("fixture_id")
    assert claimed == domain_fingerprint("ibae.synthetic-effect-conformance-id.v1", result)


def test_independent_fresh_native_sessions_repeat_same_effect_evidence():
    assert canonical_json(v0_6d_reference_fixture()) == canonical_json(v0_6d_reference_fixture())


def test_closed_effect_inputs_cannot_substitute_acceptance_or_execution_plan():
    inputs = reference_effect_inputs()
    inputs["cases"]["synthetic_set.success"]["expected_cells"]["counter"] = 99
    with pytest.raises(ValueError, match="closed reference corpus"):
        replay_effect_inputs(inputs)


def test_recovery_keeps_applied_occurrences_and_unknown_outcomes_distinct():
    result = v0_6d_reference_fixture()["cases"]
    after = result["synthetic_increment.lost_ack_after"]
    assert after["final_snapshot"]["counters"]["executions"] == 1
    assert after["receipts"][0]["effect_applied"] is None
    assert after["receipts"][1]["effect_applied"] is True
    unknown = result["synthetic_increment.unknown"]
    assert unknown["final_snapshot"]["cells"]["counter"] == 1
    assert unknown["manifest_complete"] is False
    assert unknown["receipts"][-1]["effect_applied"] is None
    assert result["ordered.partial_completion"]["partial"] is True
    distinct = result["ordered.distinct_same_payload"]
    assert distinct["receipts"][0]["action_id"] != distinct["receipts"][1]["action_id"]
    assert distinct["final_snapshot"]["counters"]["executions"] == 2
    assert result["preserve.uncommitted_content"]["final_snapshot"]["cells"]["counter"] == 99
    assert all(not case["global_task_acceptance"] for case in result.values())


def test_effect_replay_never_dispatches_network_or_provider_transport(monkeypatch):
    import socket
    import ibae.openai_transport as transport

    def forbidden(*args, **kwargs):
        raise AssertionError("synthetic effects must never dispatch network/provider work")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(transport.OpenAICredentialBroker, "_request", forbidden)
    result = v0_6d_reference_fixture()
    assert result["external_mutations"] == 0
