"""Ordinary inert synthetic effect contracts; no callback or live-effect tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ibae.canonical import canonical_json, domain_fingerprint
from ibae.continuation import ContinuationPolicyReceipt, ContinuationState, experimental_continuation_profile
from ibae.effects import (
    EFFECT_PROFILE_ID_DOMAIN, EffectCommand, EffectEntry, EffectLimits, EffectProfile,
    EffectReceipt, EffectSession, EffectSnapshot, SyntheticEffectOutcome as Outcome,
)
from ibae.governance import (
    GovernancePolicy, GovernanceWrapper, PrincipalAuthority, ProviderAuthority,
    SUPPORTED_REQUIRED_GATE_KEYS, ToolAuthorityClass, ToolPermission,
)
from ibae.obligations import Obligation
from ibae.orchestration import (
    ActionProposal, Capability, DecisionStatus, OrchestrationState,
    ProposalBatch, ProposalOrdering, ReplaySafety, Strategy, StrategySchema, admit_batch,
)
from ibae.runtime import RustRuntimeSession


def effect_bundle(
    *, tools=("synthetic_set",), outcomes=None, arguments=None,
    limits=None, initial_cells=None, session_key="effects.reference", commitment=True,
):
    initial_cells = {"counter": 0} if initial_cells is None else initial_cells
    outcomes = ((Outcome.SUCCESS,),) * len(tools) if outcomes is None else outcomes
    arguments = tuple(
        {"key": "counter", "expected_value": index, "value" if name == "synthetic_set" else "delta": index + 1 if name == "synthetic_set" else 1}
        for index, name in enumerate(tools)
    ) if arguments is None else arguments
    policy = GovernancePolicy(
        policy_key="synthetic.effects", policy_version=1, task_profile="tiny", task_profile_version=1,
        provider_authority=ProviderAuthority.OPENAI,
        tool_permissions=(
            ToolPermission("synthetic_set", ToolAuthorityClass.IDEMPOTENT_MUTATION, True, False),
            ToolPermission("synthetic_increment", ToolAuthorityClass.NON_IDEMPOTENT_MUTATION, True, False),
        ),
        required_gate_keys=tuple(sorted(SUPPORTED_REQUIRED_GATE_KEYS)),
    )
    capabilities = {
        name: Capability(name, ReplaySafety.OCCURRENCE_SENSITIVE, "Closed synthetic effect.",
            semantic_argument_keys=("expected_value", "key", "value") if name == "synthetic_set" else ("delta", "expected_value", "key"))
        for name in set(tools)
    }
    obligation = Obligation("synthetic.effects", "Verify the declared synthetic effects.")
    schema = StrategySchema("effects")
    state = OrchestrationState.create((obligation,), capabilities=tuple(capabilities.values()), strategy_schemas=(schema,))
    proposals = tuple(ActionProposal(
        f"effect.{index}", name, argument, target_obligation_ids=(obligation.obligation_id,), occurrence_key=f"occurrence.{index}",
    ) for index, (name, argument) in enumerate(zip(tools, arguments)))
    batch = ProposalBatch("effects", Strategy("effects", {}, schema=schema), proposals, ProposalOrdering.DECLARED_SEQUENCE)
    admitted = admit_batch(state, batch)
    assert all(decision.status is DecisionStatus.ADMITTED for decision in admitted.receipt.decisions)
    dependency = state.epistemic_state.dependency_digest(())
    entries = tuple(EffectEntry(capabilities[proposal.capability], proposal, decision, dependency, outcome)
        for proposal, decision, outcome in zip(proposals, admitted.receipt.decisions, outcomes))
    profile = EffectProfile(policy.governance_id, entries, initial_cells=initial_cells, limits=limits)
    wrapper = GovernanceWrapper(policy)
    task, governance = wrapper.admit_task("synthetic.effects", {"effect_profile_id": profile.profile_id} if commitment else {"goal": "unbound effects"}, requester=PrincipalAuthority.OPENAI_SUPERVISOR)
    admissions = tuple(wrapper.admit_tool(
        task, governance, decision, proposal, capabilities[proposal.capability],
        ToolAuthorityClass.IDEMPOTENT_MUTATION if proposal.capability == "synthetic_set" else ToolAuthorityClass.NON_IDEMPOTENT_MUTATION,
        dependency_state_id=dependency, requester=PrincipalAuthority.DETERMINISTIC_ORCHESTRATOR,
    ) for proposal, decision in zip(proposals, admitted.receipt.decisions))
    continuation = experimental_continuation_profile("tiny")
    continuation_receipt = ContinuationPolicyReceipt(continuation, policy, governance)
    runtime, authority = RustRuntimeSession.create_continuation(session_key, continuation_policy=continuation, continuation_policy_receipt=continuation_receipt)
    continuation_state = ContinuationState.create(policy=continuation, policy_receipt=continuation_receipt, runtime_session=runtime, orchestration_state=admitted.next_state, runtime_snapshot=runtime.snapshot)
    return SimpleNamespace(continuation_state=continuation_state, profile=profile, policy=policy, task=task, governance=governance,
        admissions=admissions, runtime=runtime, authority=authority, entries=entries, proposals=proposals,
        capabilities=capabilities, decisions=admitted.receipt.decisions, dependency=dependency)


def create(bundle, *, enabled=True):
    return EffectSession.create(bundle.runtime, bundle.authority, profile=bundle.profile,
        task=bundle.task, governance_policy=bundle.policy, governance=bundle.governance,
        tool_admissions=bundle.admissions, enabled=enabled)


def perform(session, bundle, kind=EffectCommand.EXECUTE, index=0):
    command = session.command(kind, bundle.entries[index].action_id)
    return session.dispatch(command, session.authorize(command, bundle.authority))


def snapshot(session):
    return canonical_json(session.snapshot.canonical_record())


def test_profile_is_precommitted_isolated_and_separately_versioned():
    bundle = effect_bundle()
    profile = bundle.profile.canonical_record()
    assert profile["protocol_version"] == "IBAE-EFFECT-PROFILE-V1"
    assert bundle.profile.profile_id == domain_fingerprint(EFFECT_PROFILE_ID_DOMAIN, profile)
    profile["initial_cells"]["counter"] = 999
    profile["entries"][0]["outcomes"] = ["arbitrary"]
    assert bundle.profile.canonical_record()["initial_cells"] == {"counter": 0}
    assert bundle.profile.canonical_record()["entries"][0]["outcomes"] == ["success"]
    assert bundle.task.acceptance_contract["effect_profile_id"] == bundle.profile.profile_id
    with pytest.raises(ValueError, match="original task"):
        create(effect_bundle(commitment=False))


@pytest.mark.parametrize("field,value", [("max_requests", True), ("max_requests", 0), ("max_executions", 1025), ("max_retries", -1), ("max_reconciliations", 1025)])
def test_limits_are_finite_and_exact(field, value):
    with pytest.raises((TypeError, ValueError)):
        EffectLimits(**{field: value})


def test_disabled_default_and_once_created_native_ledger_cannot_reset():
    bundle = effect_bundle()
    with pytest.raises(ValueError, match="disabled"):
        EffectSession.create(bundle.runtime, bundle.authority, profile=bundle.profile,
            task=bundle.task, governance_policy=bundle.policy, governance=bundle.governance, tool_admissions=bundle.admissions)
    session = create(bundle)
    before = snapshot(session)
    with pytest.raises(ValueError):
        create(bundle)
    assert snapshot(session) == before


def test_approved_effect_retains_native_pre_post_and_leaves_legacy_runtime_unchanged():
    bundle = effect_bundle()
    before_legacy = bundle.runtime.snapshot._canonical_text()
    session = create(bundle)
    receipt = perform(session, bundle)
    record = receipt.canonical_record()
    assert receipt.status == "applied" and receipt.effect_applied is True and not receipt.ambiguous
    assert receipt.source_bound and session.validates_receipt(receipt)
    assert record["pre_evidence"]["value"] == 0 and record["post_evidence"]["value"] == 1
    assert record["evidence_scope"] == "synthetic-native-in-process"
    assert record["authority_class"] == "idempotent_mutation"
    assert session.snapshot.manifest_complete and not session.snapshot.partial
    assert session.snapshot.canonical_record()["counters"] == {"requests": 1, "executions": 1, "retries": 0, "reconciliations": 0}
    assert bundle.runtime.snapshot._canonical_text() == before_legacy
    assert "final_acceptance" not in record
    record["post_evidence"]["value"] = 9
    assert receipt.canonical_record()["post_evidence"]["value"] == 1


def test_distinct_occurrences_with_identical_payload_are_never_coalesced():
    arguments = ({"key": "counter", "expected_value": 0, "value": 0},) * 2
    bundle = effect_bundle(tools=("synthetic_set",) * 2, arguments=arguments)
    session = create(bundle)
    first = perform(session, bundle, index=0)
    second = perform(session, bundle, index=1)
    assert first.canonical_record()["arguments_id"] == second.canonical_record()["arguments_id"]
    assert first.canonical_record()["action_id"] != second.canonical_record()["action_id"]
    assert session.snapshot.canonical_record()["counters"]["executions"] == 2
    assert session.snapshot.applied_count == 2


def test_missing_forged_duplicate_or_stale_approval_is_state_neutral():
    bundle = effect_bundle(tools=("synthetic_set",) * 2)
    session = create(bundle)
    command = session.command(EffectCommand.EXECUTE, bundle.entries[0].action_id)
    before = snapshot(session)
    with pytest.raises(TypeError):
        session.dispatch(command, None)
    assert snapshot(session) == before
    approval = session.authorize(command, bundle.authority)
    receipt = session.dispatch(command, approval)
    after = snapshot(session)
    with pytest.raises(ValueError):
        session.dispatch(command, approval)
    with pytest.raises(ValueError):
        session.authorize(command, bundle.authority)
    assert snapshot(session) == after
    assert session.validates_receipt(receipt)


def test_equal_id_duplicate_runtime_cannot_issue_or_transfer_native_authority():
    left, right = effect_bundle(), effect_bundle()
    left_session, right_session = create(left), create(right)
    assert left_session.snapshot.state_id == right_session.snapshot.state_id
    command = left_session.command(EffectCommand.EXECUTE, left.entries[0].action_id)
    before = snapshot(left_session)
    with pytest.raises(ValueError):
        left_session.authorize(command, right.authority)
    right_approval = right_session.authorize(command, right.authority)
    with pytest.raises(ValueError):
        left_session.dispatch(command, right_approval)
    assert snapshot(left_session) == before
    receipt = perform(left_session, left)
    assert left_session.validates_receipt(receipt)
    assert not right_session.validates_receipt(receipt)
    structural = EffectReceipt(receipt.canonical_record())
    assert not structural.source_bound and not left_session.validates_receipt(structural)


@pytest.mark.parametrize("tool", ["synthetic_set", "synthetic_increment"])
def test_known_failure_retry_is_explicit_bounded_and_preserves_occurrence(tool):
    bundle = effect_bundle(tools=(tool,), outcomes=((Outcome.FAIL_BEFORE, Outcome.SUCCESS),))
    session = create(bundle)
    first = perform(session, bundle)
    assert first.status == "not_applied" and first.effect_applied is False
    with pytest.raises(ValueError):
        perform(session, bundle)
    second = perform(session, bundle, EffectCommand.RETRY)
    assert second.status == "applied"
    assert second.canonical_record()["attempt"] == 2
    assert first.canonical_record()["occurrence_key"] == second.canonical_record()["occurrence_key"]
    assert session.snapshot.canonical_record()["counters"] == {"requests": 2, "executions": 2, "retries": 1, "reconciliations": 0}


def test_crash_after_effect_is_ambiguous_until_journal_reconciliation_and_never_reexecuted():
    bundle = effect_bundle(tools=("synthetic_increment",), outcomes=((Outcome.CRASH_AFTER, Outcome.SUCCESS),))
    session = create(bundle)
    first = perform(session, bundle)
    assert first.status == "ambiguous" and first.effect_applied is None
    assert first.canonical_record()["post_evidence"] is None
    before = snapshot(session)
    with pytest.raises(ValueError):
        perform(session, bundle, EffectCommand.RETRY)
    assert snapshot(session) == before
    recovered = perform(session, bundle, EffectCommand.RECONCILE)
    assert recovered.status == "reconciled_applied" and recovered.effect_applied is True
    assert recovered.canonical_record()["recovery_of_event_id"] == first.canonical_record()["event_id"]
    assert session.snapshot.canonical_record()["cells"]["counter"] == 1
    assert session.snapshot.canonical_record()["counters"]["executions"] == 1
    with pytest.raises(ValueError):
        perform(session, bundle, EffectCommand.RETRY)


def test_crash_before_effect_requires_reconciliation_before_retry():
    bundle = effect_bundle(outcomes=((Outcome.CRASH_BEFORE, Outcome.SUCCESS),))
    session = create(bundle)
    assert perform(session, bundle).status == "ambiguous"
    with pytest.raises(ValueError):
        perform(session, bundle, EffectCommand.RETRY)
    recovered = perform(session, bundle, EffectCommand.RECONCILE)
    assert recovered.status == "reconciled_not_applied" and recovered.effect_applied is False
    assert perform(session, bundle, EffectCommand.RETRY).status == "applied"


def test_unknown_outcome_remains_ambiguous_and_reconciliation_cannot_refill_budget():
    bundle = effect_bundle(outcomes=((Outcome.AMBIGUOUS_UNKNOWN,),), limits=EffectLimits(max_reconciliations=1))
    session = create(bundle)
    assert perform(session, bundle).ambiguous
    assert perform(session, bundle, EffectCommand.RECONCILE).ambiguous
    before = snapshot(session)
    with pytest.raises(ValueError):
        perform(session, bundle, EffectCommand.RECONCILE)
    with pytest.raises(ValueError):
        perform(session, bundle, EffectCommand.RETRY)
    assert snapshot(session) == before
    assert not session.snapshot.manifest_complete


def test_cancellation_before_execution_has_no_effect_or_execution_credit():
    bundle = effect_bundle()
    session = create(bundle)
    receipt = perform(session, bundle, EffectCommand.CANCEL)
    assert receipt.status == "cancelled" and receipt.effect_applied is False
    state = session.snapshot.canonical_record()
    assert state["cells"] == {"counter": 0} and state["counters"]["executions"] == 0
    assert state["occurrences"][0]["cancel_requested"]
    before = snapshot(session)
    with pytest.raises(ValueError):
        perform(session, bundle)
    assert snapshot(session) == before


def test_revocation_retires_previously_issued_effect_approval_and_never_undoes_evidence():
    bundle = effect_bundle(tools=("synthetic_set",) * 2)
    session = create(bundle)
    receipt = perform(session, bundle)
    command = session.command(EffectCommand.EXECUTE, bundle.entries[1].action_id)
    approval = session.authorize(command, bundle.authority)
    bundle.authority.revoke_all()
    before = snapshot(session)
    with pytest.raises(ValueError):
        session.dispatch(command, approval)
    with pytest.raises(ValueError):
        session.authorize(session.command(EffectCommand.EXECUTE, bundle.entries[1].action_id), bundle.authority)
    assert snapshot(session) == before
    assert session.snapshot.canonical_record()["revoked"] is True
    assert session.validates_receipt(receipt)


@pytest.mark.parametrize("limits", [EffectLimits(max_requests=1), EffectLimits(max_executions=1), EffectLimits(max_retries=0)])
def test_fixed_request_execution_and_retry_ceilings_cannot_be_extended(limits):
    bundle = effect_bundle(outcomes=((Outcome.FAIL_BEFORE, Outcome.SUCCESS),), limits=limits)
    session = create(bundle)
    perform(session, bundle)
    before = snapshot(session)
    with pytest.raises(ValueError):
        perform(session, bundle, EffectCommand.RETRY)
    assert snapshot(session) == before


def test_partial_manifest_preserves_earlier_work_and_precondition_protects_existing_content():
    arguments = ({"key": "counter", "expected_value": 0, "value": 7}, {"key": "counter", "expected_value": 0, "value": 99})
    bundle = effect_bundle(tools=("synthetic_set",) * 2, arguments=arguments)
    session = create(bundle)
    first = perform(session, bundle)
    second = perform(session, bundle, index=1)
    assert second.status == "not_applied"
    assert second.canonical_record()["failure_reason"] == "precondition_mismatch"
    assert session.snapshot.canonical_record()["cells"] == {"counter": 7}
    assert session.snapshot.partial and not session.snapshot.manifest_complete
    assert session.validates_receipt(first)


def test_declared_order_is_enforced_before_any_mutation():
    bundle = effect_bundle(tools=("synthetic_set",) * 2)
    session = create(bundle)
    before = snapshot(session)
    with pytest.raises(ValueError):
        perform(session, bundle, index=1)
    assert snapshot(session) == before


def test_recomputed_hash_does_not_admit_invalid_effect_receipt_or_restore_authority():
    bundle = effect_bundle()
    session = create(bundle)
    receipt = perform(session, bundle)
    record = receipt.canonical_record()
    record["authority_class"] = "pure_read"
    record["receipt_id"] = domain_fingerprint("ibae.effect-receipt-id.v1", {key: value for key, value in record.items() if key != "receipt_id"})
    with pytest.raises(ValueError, match="mutation"):
        EffectReceipt(record)
    record = receipt.canonical_record()
    record["unknown_field"] = True
    with pytest.raises(ValueError, match="schema"):
        EffectReceipt(record)
    with pytest.raises(TypeError):
        EffectSession()


def test_manifest_or_limits_change_cannot_use_original_task_commitment():
    bundle = effect_bundle()
    altered = EffectProfile(bundle.policy.governance_id, bundle.entries,
        initial_cells={"counter": 0}, limits=EffectLimits(max_requests=65))
    with pytest.raises(ValueError, match="original task"):
        EffectSession.create(bundle.runtime, bundle.authority, profile=altered, task=bundle.task,
            governance_policy=bundle.policy, governance=bundle.governance, tool_admissions=bundle.admissions, enabled=True)


def test_non_native_profile_fields_do_not_expand_closed_effect_surface():
    bundle = effect_bundle()
    with pytest.raises(TypeError):
        EffectProfile(bundle.policy.governance_id, list(bundle.entries), initial_cells={"counter": 0})
    with pytest.raises(ValueError, match="unique"):
        EffectProfile(bundle.policy.governance_id, bundle.entries * 2, initial_cells={"counter": 0})
    with pytest.raises((ValueError, TypeError)):
        EffectProfile(bundle.policy.governance_id, bundle.entries, initial_cells={"counter": True})
    with pytest.raises(ValueError):
        EffectProfile(bundle.policy.governance_id, bundle.entries, initial_cells={"counter": 1 << 63})


def test_cancel_after_approval_retires_only_the_exact_pending_effect():
    bundle = effect_bundle(tools=("synthetic_set",) * 2)
    session = create(bundle)
    execute = session.command(EffectCommand.EXECUTE, bundle.entries[0].action_id)
    execute_approval = session.authorize(execute, bundle.authority)
    before = snapshot(session)
    wrong_target = session.command(EffectCommand.CANCEL, bundle.entries[1].action_id)
    with pytest.raises(ValueError):
        session.authorize(wrong_target, bundle.authority)
    foreign = effect_bundle()
    cancel = session.command(EffectCommand.CANCEL, bundle.entries[0].action_id)
    with pytest.raises(ValueError):
        session.authorize(cancel, foreign.authority)
    assert execute_approval.validates(canonical_json(execute))
    assert snapshot(session) == before
    cancellation = session.authorize(cancel, bundle.authority)
    assert not execute_approval.validates(canonical_json(execute))
    assert snapshot(session) == before
    with pytest.raises(ValueError):
        session.dispatch(execute, execute_approval)
    with pytest.raises(ValueError):
        session.authorize(cancel, bundle.authority)
    receipt = session.dispatch(cancel, cancellation)
    assert receipt.status == "cancelled"
    assert session.snapshot.canonical_record()["counters"] == {"requests": 1, "executions": 0, "retries": 0, "reconciliations": 0}
    assert session.snapshot.canonical_record()["cells"] == {"counter": 0}


def test_cancelling_ambiguous_effect_preserves_unknown_outcome_and_allows_journal_inspection():
    bundle = effect_bundle(outcomes=((Outcome.CRASH_AFTER,),))
    session = create(bundle)
    first = perform(session, bundle)
    cancelled = perform(session, bundle, EffectCommand.CANCEL)
    assert cancelled.status == "ambiguous" and cancelled.effect_applied is None
    assert cancelled.canonical_record()["cancel_requested"]
    assert cancelled.canonical_record()["recovery_of_event_id"] == first.canonical_record()["event_id"]
    recovered = perform(session, bundle, EffectCommand.RECONCILE)
    assert recovered.status == "reconciled_applied" and recovered.canonical_record()["cancel_requested"]
    with pytest.raises(ValueError):
        perform(session, bundle, EffectCommand.RETRY)
    assert session.snapshot.canonical_record()["counters"]["executions"] == 1


def _factory_spec(bundle):
    return {
        "protocol_version": "IBAE-EFFECT-RUNTIME-V1", "profile": bundle.profile.canonical_record(),
        "task_receipt": bundle.task.canonical_record(), "governance_policy": bundle.policy.canonical_record(),
        "governance_receipt": bundle.governance.canonical_record(), "tool_admissions": [item.canonical_record() for item in bundle.admissions],
    }


@pytest.mark.parametrize("mutation", [
    lambda spec: spec["profile"]["limits"].update(max_requests=65),
    lambda spec: spec["profile"]["initial_cells"].update(counter=999),
    lambda spec: spec["profile"]["entries"][0]["proposal"]["arguments"].update(value=99),
    lambda spec: spec["tool_admissions"][0].update(authority_class="pure_read"),
    lambda spec: spec["governance_policy"]["tool_permissions"][0].update(allow_mutation=False),
    lambda spec: spec["task_receipt"]["acceptance_contract"].update(effect_profile_id="0" * 64),
])
def test_direct_native_factory_rejects_unbound_inert_spec_and_does_not_consume_attachment(mutation):
    bundle = effect_bundle()
    spec = _factory_spec(bundle)
    mutation(spec)
    before = bundle.runtime.snapshot._canonical_text()
    with pytest.raises(ValueError):
        bundle.runtime._create_effect_session(bundle.authority, canonical_json(spec), enabled=True)
    assert bundle.runtime.snapshot._canonical_text() == before
    session = create(bundle)
    assert perform(session, bundle).effect_applied


@pytest.mark.parametrize("path,value", [
    (("protocol_version",), "IBAE-EFFECT-PROFILE-V2"),
    (("entries", 0, "capability", "capability_id"), "0" * 64),
    (("entries", 0, "capability", "description"), ""),
    (("entries", 0, "capability", "available"), 1),
    (("entries", 0, "proposal", "epistemic_class"), "observed"),
    (("entries", 0, "proposal", "arguments", "expected_value"), 0.0),
    (("entries", 0, "admission_decision", "logical_tick"), True),
    (("entries", 0, "admission_decision", "action_id"), "0" * 64),
    (("entries", 0, "outcomes"), ["live_network"]),
])
def test_profile_parser_revalidates_every_bound_semantic_field(path, value):
    record = effect_bundle().profile.canonical_record()
    parent = record
    for key in path[:-1]:
        parent = parent[key]
    parent[path[-1]] = value
    with pytest.raises((ValueError, TypeError)):
        EffectProfile.from_record(record)


def test_profile_and_entry_roundtrip_preserve_content_but_never_native_capabilities():
    bundle = effect_bundle()
    parsed = EffectProfile.from_record(bundle.profile.canonical_record())
    assert parsed.profile_id == bundle.profile.profile_id
    parsed_entry = EffectEntry.from_record(bundle.entries[0].canonical_record())
    assert parsed_entry.action_id == bundle.entries[0].action_id
    assert not hasattr(parsed, "authorize") and not hasattr(parsed_entry, "dispatch")


@pytest.mark.parametrize("field,value", [("event_id", "0" * 64), ("command_id", "0" * 64), ("logical_tick", 3), ("effect_applied", False), ("failure_reason", "precondition_mismatch")])
def test_recomputed_receipt_hash_cannot_hide_semantic_inconsistency(field, value):
    bundle = effect_bundle()
    receipt = perform(create(bundle), bundle).canonical_record()
    receipt[field] = value
    receipt["receipt_id"] = domain_fingerprint("ibae.effect-receipt-id.v1", {key: item for key, item in receipt.items() if key != "receipt_id"})
    with pytest.raises(ValueError):
        EffectReceipt(receipt)


def test_recomputed_snapshot_hash_cannot_hide_counter_or_occurrence_inconsistency():
    bundle = effect_bundle()
    session = create(bundle)
    perform(session, bundle)
    record = session.snapshot.canonical_record()
    record["occurrences"][0]["attempts"] = 0
    record["state_id"] = domain_fingerprint("ibae.effect-state-id.v1", {key: value for key, value in record.items() if key != "state_id"})
    with pytest.raises(ValueError):
        EffectSnapshot(record)


def test_native_effect_types_are_nonconstructible_and_non_subclassable():
    from ibae._runtime import NativeEffectSession, NativeEffectApprovalSeal, NativeEffectReceiptSeal
    for kind in (NativeEffectSession, NativeEffectApprovalSeal, NativeEffectReceiptSeal):
        with pytest.raises(TypeError):
            kind()
        with pytest.raises(TypeError):
            type("DerivedEffectAuthority", (kind,), {})


def test_checked_increment_overflow_rejects_before_approval_or_resource_consumption():
    bundle = effect_bundle(tools=("synthetic_increment",), initial_cells={"counter": (1 << 63) - 1},
        arguments=({"key": "counter", "expected_value": (1 << 63) - 1, "delta": 1},))
    session = create(bundle)
    before = snapshot(session)
    with pytest.raises(ValueError):
        perform(session, bundle)
    assert snapshot(session) == before


def test_cancelled_proven_unapplied_occurrence_releases_declared_sequence():
    arguments = ({"key": "counter", "expected_value": 0, "value": 9}, {"key": "counter", "expected_value": 0, "value": 3})
    bundle = effect_bundle(tools=("synthetic_set",) * 2, arguments=arguments,
        outcomes=((Outcome.CRASH_BEFORE,), (Outcome.SUCCESS,)))
    session = create(bundle)
    assert perform(session, bundle).ambiguous
    assert perform(session, bundle, EffectCommand.CANCEL).ambiguous
    receipt = perform(session, bundle, EffectCommand.RECONCILE)
    assert receipt.status == "reconciled_not_applied"
    assert receipt.canonical_record()["cancel_requested"]
    assert perform(session, bundle, index=1).status == "applied"
    assert session.snapshot.canonical_record()["cells"] == {"counter": 3}
    assert session.snapshot.partial and not session.snapshot.manifest_complete


def test_failed_cancel_replacement_keeps_original_approved_effect_dispatchable():
    bundle = effect_bundle(tools=("synthetic_set",) * 2)
    session = create(bundle)
    execute = session.command(EffectCommand.EXECUTE, bundle.entries[0].action_id)
    approval = session.authorize(execute, bundle.authority)
    wrong_cancel = session.command(EffectCommand.CANCEL, bundle.entries[1].action_id)
    with pytest.raises(ValueError):
        session.authorize(wrong_cancel, bundle.authority)
    assert session.dispatch(execute, approval).effect_applied is True


def test_finite_outcome_plan_exhaustion_is_separate_from_global_retry_capacity():
    bundle = effect_bundle(outcomes=((Outcome.FAIL_BEFORE,) * 2,))
    session = create(bundle)
    assert perform(session, bundle).status == "not_applied"
    assert perform(session, bundle, EffectCommand.RETRY).status == "not_applied"
    before = snapshot(session)
    with pytest.raises(ValueError):
        perform(session, bundle, EffectCommand.RETRY)
    assert snapshot(session) == before
    assert session.snapshot.canonical_record()["counters"]["retries"] == 1


def test_structural_receipt_and_snapshot_reject_overlapping_counter_claims():
    bundle = effect_bundle()
    session = create(bundle)
    receipt = perform(session, bundle).canonical_record()
    receipt["counters"]["reconciliations"] = 1
    receipt["receipt_id"] = domain_fingerprint("ibae.effect-receipt-id.v1", {key: value for key, value in receipt.items() if key != "receipt_id"})
    with pytest.raises(ValueError, match="accounting"):
        EffectReceipt(receipt)
    state = session.snapshot.canonical_record()
    state["counters"]["reconciliations"] = 1
    state["state_id"] = domain_fingerprint("ibae.effect-state-id.v1", {key: value for key, value in state.items() if key != "state_id"})
    with pytest.raises(ValueError, match="accounting"):
        EffectSnapshot(state)


@pytest.mark.parametrize("command,flag", [(EffectCommand.CANCEL, False), (EffectCommand.EXECUTE, True)])
def test_structural_snapshot_rejects_impossible_cancellation_flags(command, flag):
    bundle = effect_bundle()
    session = create(bundle)
    perform(session, bundle, command)
    state = session.snapshot.canonical_record()
    state["occurrences"][0]["cancel_requested"] = flag
    state["state_id"] = domain_fingerprint("ibae.effect-state-id.v1", {key: value for key, value in state.items() if key != "state_id"})
    with pytest.raises(ValueError, match="cancellation"):
        EffectSnapshot(state)
