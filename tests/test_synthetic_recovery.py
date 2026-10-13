"""Adversarial recovery fixtures exercise native authority, never real effects."""
import json
from dataclasses import FrozenInstanceError, replace

import pytest

from ibae.canonical import canonical_json, domain_fingerprint
from ibae.synthetic_recovery import (
    MAX_RECOVERY_ASSESSMENT_BYTES, MAX_RECOVERY_SCENARIOS,
    SYNTHETIC_RECOVERY_SCENARIOS, RecoveryAssessment, RecoveryScenario,
    _compact_forgery, assess_recovery_scenario, synthetic_recovery_corpus,
)


@pytest.fixture(scope="module")
def corpus():
    return synthetic_recovery_corpus()


@pytest.fixture(scope="module")
def observed(corpus):
    return {item["scenario"]["scenario_id"]: item["observations"] for item in corpus["assessments"]}


def test_corpus_is_bounded_complete_and_explicitly_not_live_recovery(corpus):
    assert corpus["scenario_count"] == len(SYNTHETIC_RECOVERY_SCENARIOS) == 48
    assert corpus["scenario_count"] <= MAX_RECOVERY_SCENARIOS
    assert corpus["offline_only"] is True
    assert corpus["live_recovery_verified"] is False
    assert corpus["effect_execution_supported"] is False
    assert corpus["native_authority_reconstruction_supported"] is False
    for item in corpus["assessments"]:
        assert len(canonical_json(item).encode()) <= MAX_RECOVERY_ASSESSMENT_BYTES
        assert item["synthetic_only"] is True
        assert item["restores_native_authority"] is False
        assert item["final_acceptance"] is False


def test_decoded_input_manifest_replays_the_exact_corpus(corpus):
    raw = json.loads(canonical_json([item.canonical_record() for item in SYNTHETIC_RECOVERY_SCENARIOS]))
    parsed = tuple(RecoveryScenario.from_record(item) for item in raw)
    assert canonical_json(synthetic_recovery_corpus(scenarios=parsed)) == canonical_json(corpus)
    body = {key: value for key, value in corpus.items() if key != "corpus_id"}
    assert domain_fingerprint("ibae.synthetic-recovery.corpus.v1", body) == corpus["corpus_id"]


@pytest.mark.parametrize("case", SYNTHETIC_RECOVERY_SCENARIOS, ids=lambda item: item.scenario_id)
def test_each_registered_scenario_has_mutation_isolated_deterministic_evidence(case, observed):
    assessment = assess_recovery_scenario(case)
    assert assessment.canonical_record()["observations"] == observed[case.scenario_id]
    original = assessment.assessment_id
    changed = assessment.canonical_record()
    changed["observations"].clear()
    assert assessment.assessment_id == original
    assert assessment.canonical_record()["observations"]
    with pytest.raises(FrozenInstanceError):
        assessment._record = None


@pytest.mark.parametrize("case", ["conversation_interruption", "work_ui_interruption", "apparently_idle_active"])
def test_preserved_live_source_resumes_without_increasing_authority(case, observed):
    record = observed[case]
    assert record["recovery"]["classification"] == "resume_verified_live_task"
    assert record["recovery"]["reason"] == "exact_live_lineage_verified"
    assert record["runtime_unchanged"] is True
    assert record["external_effects_executed"] == 0
    assert record["external_outcome"]["grants_authority"] is False


@pytest.mark.parametrize("case", [
    "codex_worker_interruption", "commit_before_lost_ack", "interruption_before_commit",
    "lost_uncommitted_state", "record_only_resume", "duplicate_session_identity",
])
def test_missing_or_record_only_sources_stop_even_with_historical_evidence(case, observed):
    record = observed[case]
    assert record["recovery"]["classification"] == "stop_unverifiable"
    assert record["recovery"]["target_task_id"] is None
    assert record["runtime_unchanged"] is True
    assert record["external_effects_executed"] == 0


def test_durable_fixture_outcomes_are_separate_from_current_authority(observed):
    committed = observed["commit_before_lost_ack"]
    before_commit = observed["interruption_before_commit"]
    lost = observed["lost_uncommitted_state"]
    assert committed["external_outcome"]["durable_commit"] == "fixture.commit.completed"
    assert "without_replay" in committed["next_action"]
    assert before_commit["external_outcome"]["durable_commit"] == "baseline"
    assert before_commit["external_outcome"]["uncommitted_state"] == "fixture.patch.pending"
    assert lost["external_outcome"]["uncommitted_state"] == "lost_unverifiable"
    assert observed["apparently_idle_active"]["external_outcome"]["process"] == "active"
    assert "without_duplicate_dispatch" in observed["apparently_idle_active"]["next_action"]


def test_fresh_authorized_task_has_independent_capacity_and_explicit_history_binding(observed):
    record = observed["fresh_authorized_task"]
    assert record["recovery"]["classification"] == "start_fresh_authorized_task"
    assert record["recovery"]["reason"] == "separate_authority_selects_historical_observation"
    assert record["distinct_runtime_session"] is True
    assert record["fresh_initial_lease_count"] == 0
    assert record["authority_transfer"] is False
    assert record["old_runtime_unchanged"] is True


def test_missing_capability_asks_for_authorization(observed):
    decision = observed["missing_supervisor_authority"]["recovery"]
    assert decision["classification"] == "ask_human_authorization"
    assert decision["reason"] == "live_task_authority_unavailable"


@pytest.mark.parametrize("case", ["checkpoint_resume", "fresh_session_equality"])
def test_checkpoint_inspection_revalidates_equal_live_decision_surface(case, observed):
    record = observed[case]
    assert record["same_live_state"] is True
    assert record["equal_decision_surface"] is True
    assert record["runtime_unchanged"] is True
    assert record["recovery"]["classification"] == "resume_verified_live_task"


@pytest.mark.parametrize("case", ["interrupted_recovery", "stale_checkpoint"])
def test_second_interruption_cannot_reuse_retired_checkpoint(case, observed):
    record = observed[case]
    assert record["stale_recovery"]["classification"] == "stop_unverifiable"
    assert record["checkpoint_rejection"] == "ValueError"
    assert record["checkpoint_rejection_reason"]
    assert record["current_recovery"]["classification"] == "resume_verified_live_task"
    assert record["requests"] == 1
    assert record["duplicate_dispatches"] == 0


@pytest.mark.parametrize("case", [
    "duplicate_continuation", "duplicate_lease_application", "stale_lease_replay", "authority_epoch_revocation",
    "forged_lease_receipt", "malformed_receipt",
])
def test_invalid_lease_operations_are_source_bound_and_state_neutral(case, observed):
    record = observed[case]
    assert record["rejection"] in {"ValueError", "TypeError", "RuntimeLeaseRejected"}
    assert record["rejection_reason"]
    assert record["rejection_state_neutral"] is True
    assert record["leases_applied"] == (1 if case == "duplicate_lease_application" else 0)
    if case == "duplicate_continuation":
        assert record["rejection_reason"] == "continuation decision lineage does not match state"
        assert len(record["live_lineage_state_id"]) == 64
    if case == "malformed_receipt":
        assert record["typed_scalar_rejection"]["reason"]
    if case == "forged_lease_receipt":
        assert record["structurally_equal_receipt"] is True
        assert record["rejection_reason"] == "IBAE-RT-LEASE-REJECT-UNISSUED-GRANT"
    if case == "authority_epoch_revocation":
        assert record["revoked"] is True
        assert record["recovery"]["classification"] == "stop_unverifiable"


def test_partial_results_never_become_accepted_completion(observed):
    record = observed["partial_results"]
    assert record["denials"] == ["IBAE-LEASE-DENY-NO-MEASURABLE-PROGRESS"]
    assert record["partial"]["status"] == "partial"
    assert record["partial"]["task_complete"] is False
    assert record["partial"]["reason"] == "no_progress"
    assert record["checkpoint"]["continuation_state_id"] == record["partial"]["continuation_state_id"]


@pytest.mark.parametrize("case", ["repeated_lease_denials", "request_exhaustion"])
def test_repeated_failures_end_at_exact_request_cap_without_impossible_recovery(case, observed):
    record = observed[case]
    assert record["leases_granted"] == 0
    assert record["lease_requests"] == record["max_lease_requests"]
    assert record["lease_requests_remaining"] == 0
    assert record["denials"][-1] == "IBAE-LEASE-DENY-LEASE-REQUEST-LIMIT"
    assert record["terminal_marker_stable"] is True
    assert record["terminal_state_neutral"] is True
    assert record["runtime_unchanged"] is True
    assert record["legal_recovery_actions"] == []
    assert record["partial"]["task_complete"] is False
    assert record["partial"]["execution_receipt_id"] == record["checkpoint"]["relevant_receipt_id"]


def test_schedule_exhaustion_preserves_native_lease_count_and_partial(observed):
    record = observed["lease_exhaustion"]
    assert record["denial"]["denial_reason"] == "IBAE-LEASE-DENY-LEASE-CEILING-REACHED"
    assert record["checkpoint"]["leases_used"] == 1
    assert record["checkpoint"]["leases_remaining"] == 0
    assert set(record["checkpoint"]["remaining_capacity"].values()) == {0}
    assert record["partial"]["reason"] == "lease_ceiling_exhausted"
    assert record["partial"]["task_complete"] is False


@pytest.mark.parametrize("period", [1, 2, 3])
def test_real_native_short_cycles_count_cached_activity_and_deny_continuation(period, observed):
    record = observed[f"period_{period}_loop"]
    assert record["cycle"]["period"] == period
    assert record["requests"] == 2 * period
    assert record["executions"] == record["cache_hits"] == period
    assert record["denial"]["denial_reason"] == "IBAE-LEASE-DENY-TERMINAL-CYCLE"
    assert record["partial"]["reason"] == "terminal_cycle"


@pytest.mark.parametrize("case", ["material_strategy_recovery", "warning_then_recovery"])
def test_real_material_strategy_recovery_is_bounded_and_not_progress(case, observed):
    record = observed[case]
    assert record["granted"] is True
    assert record["strategy_change"]["status"] == "admitted"
    assert record["progress_classification"] == "no_progress"
    assert record["strategy_recoveries_used"] == 1
    assert record["strategy_recoveries_remaining"] == 0
    assert record["application_receipt_id"]
    if case == "warning_then_recovery":
        assert record["warning"] == "IBAE-LEASE-DENY-NO-MEASURABLE-PROGRESS"


@pytest.mark.parametrize("case", ["strategy_paraphrase", "strategy_churn", "strategy_cycle"])
def test_paraphrase_churn_and_cycle_equivalence_cannot_gain_recovery(case, observed):
    record = observed[case]
    assert record["granted"] is False
    assert record["strategy_recoveries_used"] == 0
    expected = ("IBAE-LEASE-DENY-STRATEGY-CHANGE-CYCLE-EQUIVALENT" if case == "strategy_cycle"
                else "IBAE-LEASE-DENY-STRATEGY-CHANGE-NOT-MATERIAL")
    assert record["decision"]["denial_reason"] == expected


def test_returning_to_old_strategy_does_not_reset_recovery_scope(observed):
    record = observed["recovery_set_exhaustion"]
    assert record["second_denial"]["denial_reason"] == "IBAE-LEASE-DENY-STRATEGY-RECOVERY-EXHAUSTED"
    assert record["strategy_recoveries_used"] == 1
    assert record["strategy_recoveries_remaining"] == 0
    assert record["partial"]["reason"] == "strategy_recovery_exhausted"


@pytest.mark.parametrize("case", [
    "prompt_injection_repository", "prompt_injection_tool", "prompt_injection_worker",
    "fake_completion_claim", "fake_progress_claim",
])
def test_retrieved_imperatives_and_fake_claims_remain_non_authoritative_data(case, observed):
    record = observed[case]
    assert record["data"]["control_authority"] is False
    assert record["decision_surface_unchanged"] is True
    assert record["data_changes_projection_identity"] is True
    assert record["completion"]["final_acceptance"] is False
    assert record["completion"]["eligible_for_gate_validation"] is False
    if case == "fake_progress_claim":
        assert record["progress_classification"] == "no_progress"


def test_hash_consistent_projection_and_compact_forgery_do_not_supply_native_sources(observed):
    projection = observed["forged_handoff"]
    assert projection["hash_consistent_record_parsed"] is True
    assert projection["recovery"]["classification"] == "stop_unverifiable"
    compact = observed["forged_compact_evidence"]
    assert compact["structurally_equal_receipt"] is True
    assert compact["genuine_source_bound"] is True
    assert compact["forged_source_bound"] is False
    assert compact["genuine_final_receipt_id"]
    assert compact["rejection"]["reason"] == "IBAE-REJECT-INVALID-BOUND-RECEIPT"
    assert compact["rejection"]["stage"] == "finalization"
    assert compact["rejection_state_neutral"] is True


def test_compact_forgery_positive_baseline_requires_declared_verified_completion(observed):
    record = observed["forged_compact_evidence"]
    contract = record["acceptance_contract"]
    assert contract["acceptance_rule"] == "exact-canonical-governed-observation-equality-v1"
    assert len(contract["acceptance_rules"]) == len(record["obligations"]) == 1
    rule = contract["acceptance_rules"][0]
    assert canonical_json(rule["expected_output"]) == canonical_json(record["observed_output"])
    assert record["predicate_matched"] is record["task_complete"] is True
    assert record["progress"]["task_complete"] is True
    assert record["progress"]["prior_measures"] != record["progress"]["current_measures"]
    assert record["progress"]["current_orchestration_state_id"] == record["live_orchestration_state_id"]
    assert record["progress_id"] == record["live_progress_evidence_id"]
    assert record["obligations"][0]["status"] == "satisfied"
    assert record["completion_surface"]["eligible_for_gate_validation"] is True
    proof = record["acceptance_proof"]
    assert proof["obligation_id"] == record["obligations"][0]["obligation_id"]
    assert proof["acceptance_rule_id"] == domain_fingerprint("ibae.synthetic-acceptance-rule.v1", rule)
    assert proof["tool_admission_receipt_id"] == record["tool_admission_receipt_id"]
    assert proof["runtime_receipt_id"] == record["runtime_receipt_id"]
    assert proof["compact_evidence_receipt_id"] == record["genuine_compact_receipt_id"]
    assert all(item["satisfied"] for item in record["gate_results"])
    assert record["baseline_finalization"]["status"] == "accepted"
    assert record["baseline_finalization"]["receipt_id"] == record["genuine_final_receipt_id"]


@pytest.mark.parametrize("actual", [
    None,
    {"fixture": "wrong", "success": True},
    {"fixture": "verified", "success": False},
    {"fixture": "verified", "success": 1},
    {"fixture": "verified"},
    {"fixture": "verified", "success": True, "extra": "unrequested"},
])
def test_compact_forgery_mismatched_actual_observation_never_mints_final_acceptance(actual):
    record = _compact_forgery(actual_output=actual)
    assert record["genuine_source_bound"] is True
    assert record["predicate_matched"] is record["task_complete"] is False
    assert record["acceptance_proof"] is None
    assert record["progress"]["task_complete"] is False
    assert record["obligations"][0]["status"] == "unsatisfied"
    assert record["completion_surface"]["eligible_for_gate_validation"] is False
    assert record["genuine_final_receipt_id"] is None
    assert record["baseline_finalization"]["status"] == "partial"
    assert not all(item["satisfied"] for item in record["gate_results"])


def test_compact_forgery_checks_expected_output_from_declared_task_contract():
    expected = {"fixture": "alternate", "success": True}
    mismatch = _compact_forgery(expected_output=expected)
    assert mismatch["predicate_matched"] is False
    assert mismatch["baseline_finalization"]["status"] == "partial"
    assert mismatch["genuine_final_receipt_id"] is None
    matching = _compact_forgery(expected_output=expected, actual_output=expected)
    assert matching["predicate_matched"] is matching["task_complete"] is True
    assert matching["baseline_finalization"]["status"] == "accepted"
    assert matching["genuine_final_receipt_id"]
    # Canonical equality accepts irrelevant dictionary insertion ordering.
    reordered = _compact_forgery(actual_output={"success": True, "fixture": "verified"})
    assert reordered == _compact_forgery()


def test_compact_forgery_one_verified_read_cannot_cover_unrelated_obligation():
    record = _compact_forgery(include_unmatched_obligation=True)
    assert record["predicate_matched"] is True
    assert record["acceptance_proof"] is not None
    assert record["task_complete"] is record["progress"]["task_complete"] is False
    assert sorted(item["status"] for item in record["obligations"]) == ["satisfied", "unsatisfied"]
    assert record["completion_surface"]["eligible_for_gate_validation"] is False
    assert record["baseline_finalization"]["status"] == "partial"
    assert record["genuine_final_receipt_id"] is None


@pytest.mark.parametrize("case", ["provider_substitution", "profile_mutation", "research_policy_promotion"])
def test_foreign_provider_silent_profile_change_and_research_promotion_fail_closed(case, observed):
    record = observed[case]
    assert record["rejection"] == "ValueError"
    assert record["rejection_reason"]
    assert record["runtime_unchanged"] is True


def test_missing_measurements_are_indeterminate_never_invented_completion(observed):
    record = observed["missing_measurements"]
    assert record["assessment"] == "indeterminate"
    assert record["measurements_available"] is False
    assert record["completion"] is False
    assert record["progress"]["evidence_ids"] == []
    assert record["progress"]["current_measures"][0]["value"] is None
    assert record["denial"]["denial_reason"] == "IBAE-LEASE-DENY-NO-MEASURABLE-PROGRESS"


def test_capability_presence_and_normalized_effect_proposal_grant_no_effects(observed):
    capability = observed["capability_escalation"]["capability"]
    assert capability["available"] is True
    assert capability["permission_id"] is None
    assert capability["read_proposal_eligible"] is False
    assert observed["capability_escalation"]["governance_rejection"]["reason"] == "IBAE-REJECT-UNKNOWN-TOOL-PERMISSION"
    effect = observed["unauthorized_effect"]
    assert effect["effect_adapter_result"]["status"] == "unsupported"
    assert effect["effect_adapter_result"]["control_authority"] is False
    assert effect["effect_governance_rejection"]["reason"] == "IBAE-REJECT-UNKNOWN-TOOL-PERMISSION"
    assert effect["effects_executed"] == 0
    assert effect["runtime_unchanged"] is True


@pytest.mark.parametrize("field,value", [
    ("scenario_id", "unknown"), ("category", "lease"), ("description", "changed operation"),
    ("external_world", "live"), ("scenario_id", True),
])
def test_manifest_cannot_select_unregistered_or_relabelled_scenarios(field, value):
    record = SYNTHETIC_RECOVERY_SCENARIOS[0].canonical_record()
    record[field] = value
    with pytest.raises((TypeError, ValueError)):
        RecoveryScenario.from_record(record)


def test_manifest_and_corpus_reject_unknown_extra_duplicate_and_unbounded_inputs():
    scenario = SYNTHETIC_RECOVERY_SCENARIOS[0]
    record = scenario.canonical_record()
    record["authority"] = True
    with pytest.raises(ValueError):
        RecoveryScenario.from_record(record)
    for invalid in ([], (), (scenario, scenario), (scenario,) * (MAX_RECOVERY_SCENARIOS + 1)):
        with pytest.raises((TypeError, ValueError)):
            synthetic_recovery_corpus(scenarios=invalid)
    with pytest.raises(ValueError):
        assess_recovery_scenario(replace(scenario, description="execute unrequested effect"))
    with pytest.raises(ValueError):
        assess_recovery_scenario("unregistered")
    with pytest.raises(TypeError):
        assess_recovery_scenario(1)


def test_assessment_boundary_rejects_noninert_and_oversized_ordinary_values():
    scenario = SYNTHETIC_RECOVERY_SCENARIOS[0]
    for value in ({"untyped": object()}, {"text": "x" * (MAX_RECOVERY_ASSESSMENT_BYTES + 1)},
                  {"number": 1 << 257}):
        with pytest.raises((TypeError, ValueError)):
            RecoveryAssessment(scenario, value)


@pytest.mark.parametrize("case,count", [
    ("period_1_loop", 2), ("period_2_loop", 4), ("period_3_loop", 6),
    ("strategy_cycle", 4), ("interrupted_recovery", 1), ("stale_checkpoint", 1), ("stale_lease_replay", 1),
])
def test_fixture_reads_traverse_real_admission_governance_and_native_accounting(case, count, observed):
    reads = observed[case]["governed_reads"]
    assert len(reads) == count
    for index, read in enumerate(reads):
        assert len(read["admission_receipt_id"]) == 64
        assert len(read["governed_tool_receipt_id"]) == 64
        assert len(read["runtime_receipt_id"]) == 64
        assert read["prior_orchestration_state_id"] != read["next_orchestration_state_id"]
        if index:
            assert read["prior_orchestration_state_id"] == reads[index - 1]["next_orchestration_state_id"]


@pytest.mark.parametrize("resource,requests,executions,retries", [
    ("retry", 3, 3, 2), ("execution", 3, 2, 2), ("request", 2, 2, 2),
])
def test_repeated_frozen_tool_failures_stop_at_real_native_resource_ceilings(
        resource, requests, executions, retries, observed):
    record = observed["repeated_tool_failures"]
    assert record["failure_source"] == "closed_frozen_read_backend"
    assert record["external_effects_executed"] == 0
    run = next(item for item in record["runs"] if item["exhausted_resource"] == resource)
    assert run["final_counters"] == {
        "requests": requests, "executions": executions, "retries": retries, "cache_hits": 0}
    assert run["terminal_receipt"]["rejection"]["reason_code"] == f"IBAE-RT-REJECT-{resource.upper()}-BUDGET"
    assert sum(item["reason"] == "IBAE-RT-REJECT-OPERATION-FAILED" for item in run["reads"]) == executions
    assert run["cache_entries"] == run["history_entries"] == 0
    assert run["progress_classification"] == "no_progress"
    assert run["continuation_denial_reason"] == "IBAE-LEASE-DENY-NO-MEASURABLE-PROGRESS"
    assert run["leases_granted"] == 0
    assert run["partial_status"] == "partial"
    assert run["task_complete"] is False
    assert "synthetic_fixture_unavailable" not in canonical_json(run)
    for index, read in enumerate(run["reads"]):
        assert read["status"] == "rejected"
        assert len(read["governed_tool_receipt_id"]) == len(read["orchestration_admission_receipt_id"]) == 64
        if index:
            retry = run["retries"][index - 1]
            assert retry["status"] == "accepted"
            assert read["prior_state_id"] == retry["next_state_id"]
            assert retry["prior_state_id"] == run["reads"][index - 1]["next_state_id"]
            assert retry["admission_id"] == run["reads"][index - 1]["admission_id"]
    assert len(run["continuation_denial_receipt_id"]) == len(run["partial_checkpoint_id"]) == 64
