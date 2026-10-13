"""Ordinary offline end-to-end tests of real IBAE authority boundaries."""

from copy import deepcopy
import json

import pytest

from ibae.canonical import canonical_fingerprint, canonical_json
from ibae.synthetic_protocol import NormalizedProposal, ProposalKind
from ibae.synthetic_runner import (
    MAX_ACCEPTANCE_RULES, MAX_CONTROL_STEPS, SYNTHETIC_CONTROL_VERSION,
    SyntheticRunResult,
    reference_synthetic_transcripts, replay_synthetic_run,
    run_synthetic_transcript, v0_6b_control_cycle_fixture,
)


def _input(name="happy_path"):
    return reference_synthetic_transcripts()[name]


def _run(name="happy_path"):
    return run_synthetic_transcript(_input(name)).canonical_record()


def _proposal(kind, payload):
    return NormalizedProposal(kind, payload).canonical_record()


def test_happy_path_crosses_real_admission_native_runtime_evidence_and_finalization():
    result = _run()
    assert result["protocol_version"] == SYNTHETIC_CONTROL_VERSION
    assert result["cycle"] == ["DECLARE", "OBSERVE", "CLASSIFY", "INTERVENE", "RECEIPT", "REPLAY"]
    assert result["summary"]["outcome"] == "objectives_verified"
    assert result["summary"]["global_final_acceptance"] is True
    assert result["summary"]["backend_calls"] == 2
    segment, = result["segments"]
    assert segment["source_bound"] is True
    assert len(segment["tool_admissions"]) == 2
    assert len(segment["runtime_receipts"]) == 2
    assert segment["finalization"] == result["full_task_final_receipt"]
    assert segment["finalization"]["status"] == "accepted"
    assert all(item["command_type"] == "execute_read" for item in segment["runtime_receipts"])
    assert all(item["cache_status"] == "cold_execution" for item in segment["runtime_receipts"])
    assert result["final_runtime"]["counters"]["executions"] == 2
    assert result["final_runtime"]["counters"]["requests"] == 2
    assert len(result["objective_proofs"]) == 2
    receipt_ids = {item["receipt_id"] for item in segment["runtime_receipts"]}
    for proof in result["objective_proofs"]:
        assert proof["runtime_receipt_id"] in receipt_ids
        assert proof["compact_evidence_receipt_id"] == segment["compact_evidence"]["receipt_id"]
    assert result["progress"][0]["task_complete"] is True
    assert result["trust_scope"]["report_is_authority"] is False


def test_long_task_uses_exact_grant_application_without_claiming_global_v04_receipt():
    result = _run("long_progressing_task")
    assert result["summary"]["outcome"] == "objectives_verified"
    assert result["summary"]["segment_count"] == 2
    assert result["full_task_final_receipt"] is None
    assert result["summary"]["global_final_acceptance"] is False
    assert result["summary"]["backend_calls"] == 4
    grant, = result["lease_decisions"]
    application, = result["lease_applications"]
    assert grant["status"] == "granted"
    assert application["status"] == "accepted"
    assert result["final_runtime"]["continuation"]["leases_applied"] == 1
    assert result["final_runtime"]["counters"]["executions"] == 4
    assert result["final_runtime"]["limits"]["max_executions"] == 4
    first, second = result["segments"]
    assert first["source_bound"] and second["source_bound"]
    assert first["finalization"]["status"] == second["finalization"]["status"] == "accepted"
    assert first["runtime_receipts"][-1]["resulting_state_id"] == application["prior_state_id"]
    assert second["runtime_receipts"][0]["prior_state_id"] == application["resulting_state_id"]
    assert result["continuation_evidence"]["progress_events"] == 2
    assert result["progress"][0]["task_complete"] is False
    assert result["progress"][1]["task_complete"] is True
    assert result["progress"][0]["current_orchestration_state_id"] == result["progress"][1]["prior_orchestration_state_id"]


def test_model_completion_and_progress_text_never_satisfies_objectives():
    result = _run("fake_completion_claim")
    assert result["summary"]["outcome"] == "partial"
    assert result["summary"]["backend_calls"] == 0
    assert result["objective_proofs"] == []
    assert result["progress"] == []
    assert result["empty_partial"]["status"] == "partial"
    assert result["full_task_final_receipt"] is None
    assert all(event["intervention"] == "ignore_model_claim_as_authority" for event in result["events"])
    assert all(event["before"] == event["after"] for event in result["events"])


def test_activity_without_progress_receives_native_denial_and_semantic_partial():
    result = _run("activity_without_progress")
    assert result["summary"]["outcome"] == "partial"
    assert result["summary"]["backend_calls"] == 1
    assert result["objective_proofs"] == []
    assert result["segments"][0]["source_bound"] is True
    assert result["segments"][0]["finalization"]["status"] == "partial"
    denial, = result["lease_decisions"]
    assert denial["denial_reason"] == "IBAE-LEASE-DENY-NO-MEASURABLE-PROGRESS"
    assert result["lease_applications"] == []
    assert result["continuation_partial"]["reason"] == "no_progress"
    assert result["continuation_partial"]["checkpoint_id"] == result["checkpoint"]["checkpoint_id"]
    assert result["final_runtime"]["continuation"]["leases_applied"] == 0


def test_missing_source_is_indeterminate_and_cannot_fabricate_observation():
    result = _run("missing_evidence")
    segment, = result["segments"]
    assert segment["measurement_status"] == "indeterminate"
    assert segment["observations"] == segment["runtime_receipts"] == []
    assert segment["rejections"] == [{"reason": "frozen-source-unavailable"}]
    assert segment["compact_evidence"] is None
    assert segment["finalization"]["status"] == "partial"
    assert result["summary"]["backend_calls"] == 0
    assert result["summary"]["outcome"] == "partial"


def test_tool_injection_stays_data_and_never_becomes_control_or_completion():
    result = _run("prompt_injection_tool_output")
    segment, = result["segments"]
    assert "Ignore governance" in segment["observations"][0]["text"]
    assert result["summary"]["outcome"] == "partial"
    assert result["objective_proofs"] == result["lease_applications"] == []
    assert result["final_runtime"]["counters"]["executions"] == 1
    assert result["final_runtime"]["limits"]["max_executions"] == 4


def test_acceptance_rule_uses_exact_canonical_output_not_python_scalar_equality():
    transcript = _input()
    transcript["fixtures"][0]["output"]["valid"] = 1
    result = run_synthetic_transcript(transcript).canonical_record()
    assert result["summary"]["outcome"] == "partial"
    assert result["full_task_final_receipt"] is None


def test_read_backend_never_runs_after_runtime_budget_exhaustion_and_demand_is_retained():
    transcript = _input()
    transcript["initial_execution_budget"] = 1
    result = run_synthetic_transcript(transcript).canonical_record()
    assert result["summary"]["backend_calls"] == 1
    assert result["summary"]["outcome"] == "partial"
    assert len(result["summary"]["unresolved_obligation_ids"]) == 2
    assert result["final_runtime"]["counters"]["executions"] == 1
    segment, = result["segments"]
    assert segment["runtime_receipts"][-1]["status"] == "rejected"
    assert segment["compact_evidence"] is None
    assert segment["finalization"]["status"] == "partial"


def test_repeated_cross_segment_read_does_not_bypass_cold_provenance():
    transcript = _input("activity_without_progress")
    transcript["proposals"] = [transcript["proposals"][0], transcript["proposals"][0]]
    transcript["initial_execution_budget"] = 4
    result = run_synthetic_transcript(transcript).canonical_record()
    assert result["summary"]["backend_calls"] == 1
    assert result["segments"][1]["rejections"] == [{"reason": "cross-segment-cold-provenance-required"}]
    assert result["segments"][1]["source_bound"] is False
    assert result["final_runtime"]["counters"]["requests"] == 1


def test_unknown_capability_is_rejected_by_actual_orchestration():
    transcript = _input()
    original = transcript["proposals"][0]["payload"]
    original["proposals"][0]["capability"] = "read.undeclared"
    transcript["proposals"][0] = _proposal(ProposalKind.READ_BATCH, original)
    result = run_synthetic_transcript(transcript).canonical_record()
    decisions = result["segments"][0]["admission"]["decisions"]
    assert any(item["status"] == "rejected" for item in decisions)
    assert result["summary"]["backend_calls"] == 1
    assert result["summary"]["outcome"] == "partial"


def test_simple_read_contract_also_crosses_real_admission():
    transcript = _input("activity_without_progress")
    transcript["fixtures"][0]["output"] = transcript["acceptance_rules"][0]["expected_output"]
    transcript["proposals"] = [_proposal(ProposalKind.READ, {
        "proposal_key": "single", "tool_name": "read.frozen", "arguments": {"path": "item-0"},
        "target_obligation_keys": ["objective-0"],
    })]
    result = run_synthetic_transcript(transcript).canonical_record()
    assert result["summary"]["global_final_acceptance"] is True
    assert result["summary"]["backend_calls"] == 1


def test_replay_decodes_actual_input_records_and_requires_full_output_equality():
    transcript = json.loads(canonical_json(_input("long_progressing_task")))
    first = run_synthetic_transcript(transcript)
    expected = first.canonical_record()
    assert replay_synthetic_run(transcript, json.loads(canonical_json(expected)))
    changed = deepcopy(expected)
    changed["summary"]["backend_calls"] += 1
    assert replay_synthetic_run(transcript, changed) is False
    transcript["fixtures"][0]["output"]["valid"] = False
    assert replay_synthetic_run(transcript, expected) is False
    assert first.canonical_record() == expected


def test_normalized_transport_roundtrip_preserves_every_decision_and_receipt():
    transcript = _input()
    other = deepcopy(transcript)
    other["proposals"] = [NormalizedProposal.from_record(json.loads(canonical_json(item))).canonical_record()
                          for item in transcript["proposals"]]
    assert run_synthetic_transcript(transcript).canonical_record() == run_synthetic_transcript(other).canonical_record()


def test_changed_frozen_dependency_changes_authority_and_runtime_identities():
    transcript = _input()
    first = run_synthetic_transcript(transcript).canonical_record()
    transcript["source_version"] = "frozen-world-v2"
    second = run_synthetic_transcript(transcript).canonical_record()
    assert first["declaration"]["task"]["task_id"] != second["declaration"]["task"]["task_id"]
    assert first["segments"][0]["runtime_receipts"][0]["command_id"] != second["segments"][0]["runtime_receipts"][0]["command_id"]
    assert first["summary"] == second["summary"]


def test_run_results_and_inputs_are_isolated_inert_records():
    transcript = _input()
    before = deepcopy(transcript)
    result = run_synthetic_transcript(transcript)
    assert transcript == before
    first = result.canonical_record()
    first["summary"]["outcome"] = "fabricated"
    assert result.canonical_record()["summary"]["outcome"] == "objectives_verified"
    assert result.report_id == result.report_id


@pytest.mark.parametrize("field,value", [
    ("network_endpoint", "https://invalid.example"),
    ("credential", "cred:openai.test"),
    ("provider", "unapproved"),
])
def test_live_configuration_is_rejected_by_closed_input_schema(field, value):
    transcript = _input()
    transcript[field] = value
    with pytest.raises(ValueError, match="closed schema"):
        run_synthetic_transcript(transcript)


def test_input_budgets_and_streams_have_explicit_hard_bounds():
    transcript = _input()
    transcript["initial_execution_budget"] = True
    with pytest.raises(ValueError, match="execution budget"):
        run_synthetic_transcript(transcript)
    transcript = _input()
    transcript["proposals"] = [_proposal(ProposalKind.OBSERVE, {})] * (MAX_CONTROL_STEPS + 1)
    with pytest.raises(ValueError, match="finite container bound"):
        run_synthetic_transcript(transcript)
    transcript = _input()
    transcript["acceptance_rules"] *= MAX_ACCEPTANCE_RULES
    with pytest.raises(ValueError, match="finite container bound"):
        run_synthetic_transcript(transcript)


def test_non_data_values_are_rejected_at_input_boundary():
    transcript = _input()
    transcript["fixtures"][0]["output"] = {"not_json": object()}
    with pytest.raises(TypeError, match="inert exact JSON"):
        run_synthetic_transcript(transcript)


def test_reference_fixture_is_deterministic_and_offline():
    first = v0_6b_control_cycle_fixture()
    second = v0_6b_control_cycle_fixture()
    assert canonical_fingerprint(first) == canonical_fingerprint(second)
    assert set(first) == set(reference_synthetic_transcripts())
    assert all(item["trust_scope"]["network_used"] is False for item in first.values())
    assert all(item["trust_scope"]["credentials_resolved"] is False for item in first.values())


def test_material_strategy_proposal_gets_real_governance_recovery_then_observes_success():
    result = _run("material_strategy_recovery")
    change, = result["strategy_changes"]
    assert change["status"] == "admitted"
    assert change["reason"] == "IBAE-STRATEGY-ADMIT-MATERIAL-CHANGE"
    grant, = result["lease_decisions"]
    assert grant["status"] == "granted"
    assert grant["strategy_change_id"] == result["events"][1]["strategy_change_id"]
    assert len(result["lease_applications"]) == 1
    assert result["final_continuation"]["strategy_recoveries"] == 1
    assert result["active_strategy"]["capability_frontier"] == ["read.alternate"]
    assert result["progress"][0]["classification"] == "no_progress"
    assert result["progress"][1]["task_complete"] is True
    assert result["segments"][0]["finalization"]["status"] == "partial"
    assert result["segments"][1]["finalization"]["status"] == "accepted"
    assert result["summary"]["outcome"] == "objectives_verified"
    assert result["summary"]["backend_calls"] == 2
    assert result["full_task_final_receipt"] is None


def test_strategy_paraphrase_cannot_change_native_strategy_or_add_authority():
    result = _run("superficial_strategy_paraphrase")
    change, = result["strategy_changes"]
    assert change["status"] == "rejected"
    assert change["prior_strategy_material_id"] == change["proposed_strategy_material_id"]
    assert result["lease_decisions"][0]["denial_reason"] == "IBAE-LEASE-DENY-STRATEGY-CHANGE-NOT-MATERIAL"
    assert result["lease_applications"] == []
    assert result["final_continuation"]["strategy_recoveries"] == 0
    assert result["summary"]["outcome"] == "partial"
    assert result["progress"][0]["classification"] == "no_progress"


def test_normalized_recovery_inspection_revalidates_the_live_source_without_mutation():
    result = _run("material_strategy_recovery")
    inspection = next(item for item in result["events"] if item["proposal_kind"] == "inspect_recovery")
    assert inspection["before"] == inspection["after"]
    decision = inspection["recovery_decision"]
    assert decision["classification"] == "resume_verified_live_task"
    assert decision["evidence_handoff_id"] == inspection["recovery_handoff_id"]
    assert decision["target_task_id"] == result["declaration"]["task"]["task_id"]
    assert decision["grants_authority"] is decision["restores_native_authority"] is False


def test_deduplicated_read_preserves_both_obligation_targets_with_one_execution():
    transcript = _input()
    transcript["acceptance_rules"][1]["arguments"] = deepcopy(transcript["acceptance_rules"][0]["arguments"])
    transcript["acceptance_rules"][1]["expected_output"] = deepcopy(transcript["acceptance_rules"][0]["expected_output"])
    transcript["fixtures"] = [transcript["fixtures"][0]]
    payload = transcript["proposals"][0]["payload"]
    payload["proposals"][1]["arguments"] = deepcopy(payload["proposals"][0]["arguments"])
    transcript["proposals"][0] = _proposal(ProposalKind.READ_BATCH, payload)
    result = run_synthetic_transcript(transcript).canonical_record()
    segment, = result["segments"]
    assert sorted(item["status"] for item in segment["admission"]["decisions"]) == ["admitted", "deduplicated"]
    assert result["summary"]["backend_calls"] == 1
    assert result["summary"]["global_final_acceptance"] is True
    assert len(result["objective_proofs"]) == 2
    assert len({item["runtime_receipt_id"] for item in result["objective_proofs"]}) == 1
    assert len(segment["tool_admissions"]) == 1


def test_controller_prefers_remaining_budget_before_requesting_a_lease():
    transcript = _input()
    transcript["proposals"].insert(0, _proposal(ProposalKind.CONTINUE, {}))
    result = run_synthetic_transcript(transcript).canonical_record()
    assert result["events"][0]["intervention"] == "continue_within_existing_budget"
    assert result["events"][0]["before"] == result["events"][0]["after"]
    assert result["lease_decisions"] == result["lease_applications"] == []
    assert result["summary"]["global_final_acceptance"] is True


def test_whole_input_and_diagnostic_report_have_separate_byte_caps():
    with pytest.raises(ValueError, match="bound"):
        run_synthetic_transcript({"payload": ["x" * 4096] * 128})
    with pytest.raises(ValueError, match="bound"):
        SyntheticRunResult({"payload": [["x" * 4096] * 128] * 3})


def test_reference_acceptance_rules_do_not_alias_mutable_source_outputs():
    transcript = _input()
    transcript["fixtures"][0]["output"]["valid"] = False
    assert transcript["acceptance_rules"][0]["expected_output"]["valid"] is True


def test_detailed_strategy_change_normalizes_to_the_same_material_native_decision():
    transcript = _input("material_strategy_recovery")
    original = run_synthetic_transcript(transcript).canonical_record()
    material = original["active_strategy"]
    schema = next(item for item in original["declaration"]["strategy_schemas"]
                  if item["record"]["strategy_key"] == "synthetic.recovery")
    transcript["proposals"][1] = _proposal(ProposalKind.STRATEGY_CHANGE, {
        "strategy": {"key": "synthetic.recovery", "schema_id": schema["schema_id"],
                     "parameters": {"mode": "alternate"}},
        "capability_names": material["capability_frontier"],
        "target_obligation_ids": material["target_obligation_ids"],
        "dependency_path": material["dependency_path"], "recovery_mode": material["recovery_mode"],
        "initial_transition_pattern": material["initial_transition_pattern"],
    })
    replay = run_synthetic_transcript(transcript).canonical_record()
    assert replay["strategy_changes"] == original["strategy_changes"]
    assert replay["lease_decisions"] == original["lease_decisions"]
    assert replay["lease_applications"] == original["lease_applications"]
    assert replay["summary"] == original["summary"]


def test_strategy_proposal_alone_never_changes_authority_or_objective_state():
    transcript = _input("material_strategy_recovery")
    transcript["proposals"] = transcript["proposals"][:2]
    result = run_synthetic_transcript(transcript).canonical_record()
    event = result["events"][-1]
    assert event["strategy_status"] == "admitted"
    assert event["before"] == event["after"]
    assert result["active_strategy"] == result["declaration"]["initial_strategy"]
    assert result["summary"]["outcome"] == "partial"
    assert result["lease_applications"] == []


def test_progressing_run_retains_unmet_demand_after_exact_lease_ceiling_denial():
    transcript = _input("long_progressing_task")
    transcript["acceptance_rules"].append({
        "obligation_key": "objective-4", "tool_name": "read.frozen",
        "arguments": {"path": "item-4"}, "expected_output": {"valid": True, "value": 4},
    })
    transcript["fixtures"].append({"tool_name": "read.frozen", "arguments": {"path": "item-4"},
                                    "output": {"valid": True, "value": 4}})
    transcript["proposals"].insert(3, _proposal(ProposalKind.CONTINUE, {}))
    result = run_synthetic_transcript(transcript).canonical_record()
    assert result["summary"]["outcome"] == "partial"
    assert result["summary"]["backend_calls"] == 4
    assert len(result["summary"]["unresolved_obligation_ids"]) == 1
    assert len(result["objective_proofs"]) == 4
    assert result["lease_decisions"][-1]["denial_reason"] == "IBAE-LEASE-DENY-LEASE-CEILING-REACHED"
    assert len(result["lease_applications"]) == 1
    assert result["continuation_partial"]["reason"] == "lease_ceiling_exhausted"
    assert result["continuation_partial"]["checkpoint_id"] == result["checkpoint"]["checkpoint_id"]
    assert result["final_runtime"]["counters"]["executions"] == 4
    assert result["final_runtime"]["limits"]["max_executions"] == 4


def test_unavailable_alternate_frontier_cannot_manufacture_material_recovery():
    transcript = _input("activity_without_progress")
    transcript["proposals"].insert(1, _proposal(ProposalKind.STRATEGY, {
        "mode": "alternate", "description": "Use an alternate name for the same operation.",
    }))
    result = run_synthetic_transcript(transcript).canonical_record()
    assert result["events"][1]["intervention"] == "reject_undeclared_strategy"
    assert result["strategy_changes"] == result["lease_applications"] == []
    assert result["lease_decisions"][0]["denial_reason"] == "IBAE-LEASE-DENY-NO-MEASURABLE-PROGRESS"
    assert result["active_strategy"] == result["declaration"]["initial_strategy"]
    assert result["final_runtime"]["limits"]["max_executions"] == 1


def test_detailed_same_frontier_cannot_invent_recovery_path_fields():
    transcript = _input("material_strategy_recovery")
    original = run_synthetic_transcript(transcript).canonical_record()
    initial = original["declaration"]["initial_strategy"]
    alternate = original["active_strategy"]
    schema = next(item for item in original["declaration"]["strategy_schemas"]
                  if item["record"]["strategy_key"] == "synthetic.recovery")
    transcript["proposals"][1] = _proposal(ProposalKind.STRATEGY_CHANGE, {
        "strategy": {"key": "synthetic.recovery", "schema_id": schema["schema_id"],
                     "parameters": {"mode": "alternate"}},
        "capability_names": initial["capability_frontier"],
        "target_obligation_ids": alternate["target_obligation_ids"],
        "dependency_path": [], "recovery_mode": "alternate",
        "initial_transition_pattern": alternate["initial_transition_pattern"],
    })
    result = run_synthetic_transcript(transcript).canonical_record()
    assert result["events"][1]["intervention"] == "reject_undeclared_strategy"
    assert result["strategy_changes"] == result["lease_applications"] == []
    assert result["lease_decisions"][0]["denial_reason"] == "IBAE-LEASE-DENY-NO-MEASURABLE-PROGRESS"
    assert result["summary"]["outcome"] == "partial"
    assert result["summary"]["backend_calls"] == 1
