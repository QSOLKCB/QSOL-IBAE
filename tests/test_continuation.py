from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from ibae.canonical import canonical_fingerprint, canonical_json
from ibae.continuation import (
    MAX_U64,
    BudgetVector,
    ContinuationCheckpoint,
    ContinuationEvidenceReceipt,
    ContinuationPartialReason,
    ContinuationPartialReceipt,
    ContinuationPolicy,
    ContinuationPolicyReceipt,
    ContinuationRequest,
    ContinuationRequester,
    ContinuationState,
    CycleEvidence,
    LeaseDenialReason,
    LeaseDenyReceipt,
    LeaseGrantReceipt,
    ProgressClassification,
    ProgressCounterEvidence,
    ProgressDimension,
    ProgressDirection,
    ProgressMeasureContract,
    ProgressSource,
    ProgressState,
    StrategyChangeReason,
    StrategyChangeStatus,
    StrategyMaterialization,
    WatchdogObservation,
    commit_lease_application,
    evaluate_continuation,
    evaluate_progress,
    evaluate_strategy_change,
    experimental_continuation_profile,
    observe_continuation_context,
    resume_continuation_checkpoint,
)
from ibae.continuation_benchmark import (
    benchmark_policies,
    run_budget_profile_benchmark,
)
from ibae.conformance import (
    v0_5_budget_benchmark_fixture,
    v0_5_reference_fixture,
)
from ibae.epistemic import EpistemicClass
from ibae.governance import (
    COMPACT_EVIDENCE_GATE_KEY,
    EXECUTION_RECEIPT_GATE_KEY,
    ORCHESTRATION_RECEIPT_GATE_KEY,
    GovernancePolicy,
    GovernanceWrapper,
    PrincipalAuthority,
    ProviderAuthority,
)
from ibae.obligations import Obligation, ObligationStatus
from ibae.orchestration import (
    Capability,
    OrchestrationState,
    ReplaySafety,
    Strategy,
    StrategyParameterSpec,
    StrategySchema,
    StrategyValueKind,
)
from ibae.runtime import (
    RUNTIME_PROTOCOL_VERSION,
    RuntimeLeaseApplicationReceipt,
    RuntimeLimits,
    RustRuntimeSession,
)


def _id(label: str) -> str:
    return canonical_fingerprint({"label": label})


def _governed_runtime(profile: str = "tiny", *, session: str = "continuation"):
    continuation_policy = experimental_continuation_profile(profile)
    governance_policy = GovernancePolicy(
        policy_key="continuation.reference",
        policy_version=1,
        task_profile=profile,
        task_profile_version=1,
        provider_authority=ProviderAuthority.OPENAI,
        tool_permissions=(),
        required_gate_keys=(
            COMPACT_EVIDENCE_GATE_KEY,
            ORCHESTRATION_RECEIPT_GATE_KEY,
            EXECUTION_RECEIPT_GATE_KEY,
        ),
    )
    wrapper = GovernanceWrapper(governance_policy)
    task, governance = wrapper.admit_task(
        "task.continuation",
        {"goal": "satisfy declared obligations"},
        requester=PrincipalAuthority.OPENAI_SUPERVISOR,
    )
    policy_receipt = ContinuationPolicyReceipt(
        continuation_policy, governance_policy, governance
    )
    runtime = RustRuntimeSession(
        session,
        continuation_policy=continuation_policy,
        continuation_policy_receipt=policy_receipt,
    )
    return (
        continuation_policy,
        governance_policy,
        task,
        governance,
        policy_receipt,
        runtime,
    )


def _obligation_states(*, total: int = 3, satisfied: int = 0):
    obligations = tuple(
        Obligation(f"obligation.{index}", f"Obligation {index}.")
        for index in range(total)
    )
    active = tuple(
        item.with_status(ObligationStatus.SATISFIED)
        if index < satisfied
        else item
        for index, item in enumerate(obligations)
    )
    return OrchestrationState.create(active)


def _progress_contract() -> ProgressMeasureContract:
    return ProgressMeasureContract(
        "acceptance.obligations",
        1,
        (
            ProgressDimension(
                "unsatisfied",
                ProgressSource.UNSATISFIED_OBLIGATION_COUNT,
                ProgressDirection.DECREASE,
            ),
        ),
    )


def _progress(task, governance, prior, current):
    return evaluate_progress(
        task_id=task.task_id,
        governance_id=governance.governance_id,
        contract=_progress_contract(),
        prior_state=prior,
        current_state=current,
    )


def _state_and_progress(profile: str = "tiny", *, progressing: bool = True):
    bundle = _governed_runtime(profile, session=f"state-{profile}-{progressing}")
    policy, _, task, governance, policy_receipt, runtime = bundle
    prior = _obligation_states(total=3, satisfied=0)
    current = _obligation_states(total=3, satisfied=1 if progressing else 0)
    progress = _progress(task, governance, prior, current)
    state = ContinuationState.create(
        policy=policy,
        policy_receipt=policy_receipt,
        orchestration_state=current,
        runtime_snapshot=runtime.snapshot,
    )
    return (*bundle, prior, current, progress, state)


def _request_and_decide(
    policy,
    policy_receipt,
    progress,
    state,
    *,
    requested_resources=None,
    requester=PrincipalAuthority.OPENAI_SUPERVISOR,
    strategy_change=None,
    cycle_evidence=None,
    benchmark_observation=None,
):
    request = ContinuationRequest.from_state(
        state,
        progress=progress,
        requested_resources=(
            policy.lease_schedule[state.leases_granted]
            if requested_resources is None
            else requested_resources
        ),
        requester=requester,
        strategy_change=strategy_change,
    )
    decision = evaluate_continuation(
        state,
        request,
        policy=policy,
        policy_receipt=policy_receipt,
        progress=progress,
        strategy_change=strategy_change,
        cycle_evidence=cycle_evidence,
        benchmark_observation=benchmark_observation,
    )
    return request, decision


def test_named_profiles_are_exact_versioned_and_finite():
    expected = {
        "tiny": (8, 4, 2, 8, 1),
        "standard": (32, 16, 4, 32, 2),
        "extended": (64, 32, 8, 64, 3),
        "repository": (128, 64, 16, 128, 3),
    }
    for name, values in expected.items():
        policy = experimental_continuation_profile(name)
        assert (
            policy.initial_budget.request_delta,
            policy.initial_budget.execution_delta,
            policy.initial_budget.retry_delta,
            policy.initial_budget.history_delta,
            policy.max_leases,
        ) == values
        assert policy.total_ceiling == policy.initial_budget.add_checked(
            policy.continuation_capacity
        )
        assert policy.initial_budget.mutation_delta == 0
        assert all(item.mutation_delta == 0 for item in policy.lease_schedule)
        assert policy.task_profile_version == 1
        assert policy.continuation_policy_id == experimental_continuation_profile(
            name
        ).continuation_policy_id


def test_policy_requires_exact_precommitted_ceiling_and_safe_classes():
    base = BudgetVector(2, 2, 1, 0, 2)
    lease = BudgetVector(1, 1, 0, 0, 1)
    with pytest.raises(ValueError, match="exactly equal"):
        ContinuationPolicy(
            "bad.ceiling",
            1,
            "tiny",
            1,
            base,
            (lease,),
            BudgetVector(99, 3, 1, 0, 3),
            2,
        )
    with pytest.raises(ValueError, match="no_progress"):
        ContinuationPolicy(
            "bad.progress",
            1,
            "tiny",
            1,
            base,
            (lease,),
            base.add_checked(lease),
            2,
            admitted_progress=(ProgressClassification.NO_PROGRESS,),
        )


@pytest.mark.parametrize("bad", [-1, True, 1.0])
def test_lease_amounts_reject_negative_boolean_and_float(bad):
    with pytest.raises(ValueError, match="unsigned 64-bit"):
        BudgetVector(request_delta=bad)


def test_budget_vector_checked_overflow_fails_closed():
    with pytest.raises(OverflowError, match="overflow"):
        BudgetVector(request_delta=MAX_U64).add_checked(
            BudgetVector(request_delta=1)
        )


def test_measurable_progress_uses_obligation_state_not_activity():
    _, _, task, governance, _, _, prior, current, progress, _ = (
        _state_and_progress()
    )
    assert progress.classification is ProgressClassification.MEASURABLE_PROGRESS
    assert progress.prior_orchestration_state_id == prior.state_id
    assert progress.current_orchestration_state_id == current.state_id
    assert progress.evidence_ids == tuple(sorted((prior.state_id, current.state_id)))
    record = canonical_json(progress.canonical_record())
    for forbidden in ("confidence", "tokens", "elapsed", "actions_attempted"):
        assert forbidden not in record
    assert progress.progress_id == _progress(task, governance, prior, current).progress_id


def test_activity_without_progress_is_no_progress_and_denied():
    (
        policy,
        _,
        _,
        _,
        policy_receipt,
        runtime,
        _,
        _,
        progress,
        state,
    ) = _state_and_progress(progressing=False)
    runtime.execute_read("read", {"path": "a"}, "same", lambda: {"ok": True})
    runtime.execute_read("read", {"path": "a"}, "same", lambda: pytest.fail())
    assert runtime.snapshot.requests == 2
    assert runtime.snapshot.executions == 1
    assert progress.classification is ProgressClassification.NO_PROGRESS
    _, decision = _request_and_decide(policy, policy_receipt, progress, state)
    assert not decision.granted
    assert decision.receipt.denial_reason is LeaseDenialReason.NO_MEASURABLE_PROGRESS


def test_model_confidence_theatre_cannot_change_no_progress_denial():
    policy, _, _, _, policy_receipt, _, _, _, progress, state = (
        _state_and_progress(progressing=False)
    )
    request = ContinuationRequest.from_state(
        state,
        progress=progress,
        requested_resources=policy.lease_schedule[0],
        requester=PrincipalAuthority.OPENAI_SUPERVISOR,
    )
    plain = evaluate_continuation(
        state,
        request,
        policy=policy,
        policy_receipt=policy_receipt,
        progress=progress,
    )
    theatrical = evaluate_continuation(
        state,
        request,
        policy=policy,
        policy_receipt=policy_receipt,
        progress=progress,
        benchmark_observation={"model_statement": "I am 99% done"},
    )
    assert plain.receipt.canonical_record() == theatrical.receipt.canonical_record()
    assert plain.next_state.canonical_record() == theatrical.next_state.canonical_record()


def test_benchmark_observations_are_non_authoritative_for_grants():
    policy, _, _, _, policy_receipt, _, _, _, progress, state = _state_and_progress()
    request = ContinuationRequest.from_state(
        state,
        progress=progress,
        requested_resources=policy.lease_schedule[0],
        requester=PrincipalAuthority.OPENAI_SUPERVISOR,
    )
    left = evaluate_continuation(
        state,
        request,
        policy=policy,
        policy_receipt=policy_receipt,
        progress=progress,
        benchmark_observation={"wall_clock_ms": 1, "rank": "best"},
    )
    right = evaluate_continuation(
        state,
        request,
        policy=policy,
        policy_receipt=policy_receipt,
        progress=progress,
        benchmark_observation={"wall_clock_ms": 999999, "rank": "worst"},
    )
    assert left.receipt.canonical_record() == right.receipt.canonical_record()
    assert left.next_state.continuation_state_id == right.next_state.continuation_state_id


def test_regression_new_information_and_incomparable_are_distinct():
    policy, _, task, governance, _, _, *_ = _state_and_progress()
    del policy
    more_satisfied = _obligation_states(total=3, satisfied=2)
    fewer_satisfied = _obligation_states(total=3, satisfied=1)
    regression = _progress(task, governance, more_satisfied, fewer_satisfied)
    assert regression.classification is ProgressClassification.REGRESSION

    changed_definition = OrchestrationState.create(
        (
            Obligation("obligation.0", "Deeper test found a changed obligation."),
            Obligation("obligation.1", "Obligation 1."),
            Obligation("obligation.2", "Obligation 2."),
        )
    )
    new_information = _progress(
        task, governance, _obligation_states(total=3), changed_definition
    )
    assert new_information.classification is ProgressClassification.NEW_INFORMATION

    contract = ProgressMeasureContract(
        "mixed",
        1,
        (
            ProgressDimension(
                "failing",
                ProgressSource.GOVERNED_EXTERNAL_COUNTER,
                ProgressDirection.DECREASE,
            ),
            ProgressDimension(
                "gates",
                ProgressSource.GOVERNED_EXTERNAL_COUNTER,
                ProgressDirection.INCREASE,
            ),
        ),
    )
    basis = _id("external-basis")
    prior_evidence = {
        "failing": ProgressCounterEvidence(
            task.task_id,
            governance.governance_id,
            "failing",
            7,
            basis,
            _id("prior-failing"),
            EpistemicClass.OBSERVED,
        ),
        "gates": ProgressCounterEvidence(
            task.task_id,
            governance.governance_id,
            "gates",
            3,
            basis,
            _id("prior-gates"),
            EpistemicClass.DERIVED,
        ),
    }
    current_evidence = {
        "failing": replace(prior_evidence["failing"], value=3),
        "gates": replace(prior_evidence["gates"], value=2),
    }
    mixed = evaluate_progress(
        task_id=task.task_id,
        governance_id=governance.governance_id,
        contract=contract,
        prior_state=fewer_satisfied,
        current_state=fewer_satisfied,
        prior_evidence=prior_evidence,
        current_evidence=current_evidence,
    )
    assert mixed.classification is ProgressClassification.INCOMPARABLE


def test_model_proposed_external_counter_is_rejected():
    with pytest.raises(ValueError, match="observed or deterministically derived"):
        ProgressCounterEvidence(
            _id("task"),
            _id("governance"),
            "tests.failing",
            1,
            _id("basis"),
            _id("source"),
            EpistemicClass.MODEL_PROPOSED,
        )


def test_unknown_to_known_external_measure_is_new_information_not_progress():
    _, _, task, governance, _, _, prior, current, _, _ = _state_and_progress()
    contract = ProgressMeasureContract(
        "external",
        1,
        (
            ProgressDimension(
                "review.findings",
                ProgressSource.GOVERNED_EXTERNAL_COUNTER,
                ProgressDirection.DECREASE,
            ),
        ),
    )
    evidence = ProgressCounterEvidence(
        task.task_id,
        governance.governance_id,
        "review.findings",
        5,
        _id("review-basis"),
        _id("review-receipt"),
        EpistemicClass.OBSERVED,
    )
    record = evaluate_progress(
        task_id=task.task_id,
        governance_id=governance.governance_id,
        contract=contract,
        prior_state=prior,
        current_state=current,
        current_evidence={"review.findings": evidence},
    )
    assert record.classification is ProgressClassification.NEW_INFORMATION


@pytest.mark.parametrize(
    "requester",
    (
        PrincipalAuthority.LOCAL_CANDIDATE_WORKER,
        PrincipalAuthority.DETERMINISTIC_ORCHESTRATOR,
        PrincipalAuthority.RUST_EXECUTION_RUNTIME,
        ContinuationRequester.TOOL_BACKEND,
    ),
)
def test_only_supervisor_principal_may_request_a_lease(requester):
    policy, _, _, _, policy_receipt, runtime, _, _, progress, state = (
        _state_and_progress()
    )
    before = runtime.snapshot.canonical_record()
    _, decision = _request_and_decide(
        policy,
        policy_receipt,
        progress,
        state,
        requester=requester,
    )
    assert isinstance(decision.receipt, LeaseDenyReceipt)
    assert (
        decision.receipt.denial_reason
        is LeaseDenialReason.UNAUTHORIZED_REQUESTER
    )
    assert runtime.snapshot.canonical_record() == before


def test_runtime_cannot_self_extend_or_apply_without_opt_in_policy():
    runtime = RustRuntimeSession("legacy-no-continuation", RuntimeLimits(2, 2, 1, 2))
    prior = runtime.snapshot
    unsupported = runtime.dispatch_protocol(
        {
            "admission_id": _id("runtime-self-extension"),
            "command_type": "request_lease",
            "protocol_version": RUNTIME_PROTOCOL_VERSION,
        }
    )
    assert unsupported.receipt.status == "rejected"
    assert unsupported.receipt.rejection_reason == "IBAE-RT-REJECT-UNSUPPORTED-COMMAND"
    assert runtime.snapshot.state_id == prior.state_id

    policy, _, _, _, policy_receipt, _, _, _, progress, state = (
        _state_and_progress()
    )
    _, decision = _request_and_decide(policy, policy_receipt, progress, state)
    assert isinstance(decision.receipt, LeaseGrantReceipt)
    disabled = runtime.apply_lease_transition(decision.receipt)
    assert isinstance(disabled.receipt, RuntimeLeaseApplicationReceipt)
    assert disabled.receipt.status == "rejected"
    assert (
        disabled.receipt.rejection_reason
        == "IBAE-RT-LEASE-REJECT-CONTINUATION-DISABLED"
    )
    assert runtime.snapshot.state_id == prior.state_id


def test_stale_governance_and_progress_identities_are_denied():
    policy, _, _, _, policy_receipt, _, _, _, progress, state = (
        _state_and_progress()
    )
    valid = ContinuationRequest.from_state(
        state,
        progress=progress,
        requested_resources=policy.lease_schedule[0],
        requester=PrincipalAuthority.OPENAI_SUPERVISOR,
    )
    stale_governance = replace(valid, governance_id=_id("foreign-governance"))
    denied = evaluate_continuation(
        state,
        stale_governance,
        policy=policy,
        policy_receipt=policy_receipt,
        progress=progress,
    )
    assert denied.receipt.denial_reason is LeaseDenialReason.STALE_GOVERNANCE

    stale_progress = replace(valid, progress_id=_id("stale-progress"))
    denied = evaluate_continuation(
        state,
        stale_progress,
        policy=policy,
        policy_receipt=policy_receipt,
        progress=progress,
    )
    assert denied.receipt.denial_reason is LeaseDenialReason.STALE_PROGRESS


def test_skipped_lease_index_is_denied_by_governance_and_rust():
    policy, _, _, _, policy_receipt, runtime, _, _, progress, state = (
        _state_and_progress("standard")
    )
    request = ContinuationRequest.from_state(
        state,
        progress=progress,
        requested_resources=policy.lease_schedule[0],
        requester=PrincipalAuthority.OPENAI_SUPERVISOR,
    )
    skipped_request = replace(request, lease_index=2)
    denied = evaluate_continuation(
        state,
        skipped_request,
        policy=policy,
        policy_receipt=policy_receipt,
        progress=progress,
    )
    assert denied.receipt.denial_reason is LeaseDenialReason.LEASE_INDEX_MISMATCH

    valid = evaluate_continuation(
        state,
        request,
        policy=policy,
        policy_receipt=policy_receipt,
        progress=progress,
    )
    assert isinstance(valid.receipt, LeaseGrantReceipt)
    skipped_grant = replace(valid.receipt, lease_index=2)
    application = runtime.apply_lease_transition(skipped_grant)
    assert application.receipt.status == "rejected"
    assert (
        application.receipt.rejection_reason
        == "IBAE-RT-LEASE-REJECT-LEASE-INDEX"
    )
    assert runtime.snapshot.continuation.leases_applied == 0


def test_stale_grant_and_duplicate_application_are_state_neutral():
    policy, _, _, _, policy_receipt, runtime, _, _, progress, state = (
        _state_and_progress()
    )
    _, decision = _request_and_decide(policy, policy_receipt, progress, state)
    grant = decision.receipt
    assert isinstance(grant, LeaseGrantReceipt)

    runtime.record_retry()
    changed = runtime.snapshot.state_id
    stale = runtime.apply_lease_transition(grant)
    assert stale.receipt.status == "rejected"
    assert (
        stale.receipt.rejection_reason
        == "IBAE-RT-LEASE-REJECT-STALE-RUNTIME-STATE"
    )
    assert runtime.snapshot.state_id == changed

    # A fresh isolated context demonstrates apply-once semantics.
    policy, _, _, _, policy_receipt, runtime, _, _, progress, state = (
        _state_and_progress()
    )
    _, decision = _request_and_decide(policy, policy_receipt, progress, state)
    first = runtime.apply_lease(decision.receipt)
    accepted_state = runtime.snapshot.state_id
    duplicate = runtime.apply_lease_transition(decision.receipt)
    assert first.status == "accepted"
    assert duplicate.receipt.status == "rejected"
    assert runtime.snapshot.state_id == accepted_state
    assert runtime.snapshot.continuation.leases_applied == 1


def test_exact_lease_application_changes_limits_not_execution_counters():
    policy, _, _, _, policy_receipt, runtime, _, _, progress, state = (
        _state_and_progress()
    )
    before = runtime.snapshot
    _, decision = _request_and_decide(policy, policy_receipt, progress, state)
    grant = decision.receipt
    assert isinstance(grant, LeaseGrantReceipt)
    assert decision.next_state.continuation_logical_tick == 1
    assert runtime.snapshot.logical_tick == before.logical_tick

    application = runtime.apply_lease(grant)
    after = runtime.snapshot
    assert application.canonical_record()["runtime_budget_delta"] == (
        BudgetVector.zero().canonical_record()
    )
    assert application.canonical_record()["logical_tick_delta"] == 1
    assert (after.requests, after.executions, after.retries) == (
        before.requests,
        before.executions,
        before.retries,
    )
    assert after.limits == RuntimeLimits(12, 6, 3, 12)
    assert after.history == before.history
    committed = commit_lease_application(
        decision.next_state,
        policy=policy,
        grant=grant,
        application=application,
        runtime_snapshot=after,
    )
    assert not committed.has_pending_grant
    assert committed.runtime_state_id == after.state_id


def test_partial_lease_vectors_extend_resources_independently():
    policy, _, _, _, policy_receipt, runtime, _, _, progress, state = (
        _state_and_progress()
    )
    retry_only = BudgetVector(retry_delta=1)
    _, decision = _request_and_decide(
        policy,
        policy_receipt,
        progress,
        state,
        requested_resources=retry_only,
    )
    assert decision.granted
    before = runtime.snapshot.limits
    runtime.apply_lease(decision.receipt)
    after = runtime.snapshot.limits
    assert after.max_retries == before.max_retries + 1
    assert after.max_requests == before.max_requests
    assert after.max_executions == before.max_executions
    assert after.max_history == before.max_history


def test_mutation_resource_is_represented_but_unsupported():
    policy, _, _, _, policy_receipt, _, _, _, progress, state = (
        _state_and_progress()
    )
    request = ContinuationRequest.from_state(
        state,
        progress=progress,
        requested_resources=BudgetVector(mutation_delta=1),
        requester=PrincipalAuthority.OPENAI_SUPERVISOR,
    )
    denied = evaluate_continuation(
        state,
        request,
        policy=policy,
        policy_receipt=policy_receipt,
        progress=progress,
    )
    assert denied.receipt.denial_reason is LeaseDenialReason.UNSUPPORTED_RESOURCE


def _strategy_state():
    schema = StrategySchema(
        "recovery",
        (
            StrategyParameterSpec(
                "mode",
                StrategyValueKind.SYMBOL,
                allowed_symbols=("alternate", "primary"),
            ),
        ),
    )
    capabilities = (
        Capability(
            "read.alternate",
            ReplaySafety.CACHEABLE_READ,
            "Read through an alternate frontier.",
        ),
        Capability(
            "read.primary",
            ReplaySafety.CACHEABLE_READ,
            "Read through the primary frontier.",
        ),
    )
    state = OrchestrationState.create(
        (Obligation("obligation.target", "Target obligation."),),
        capabilities=capabilities,
        strategy_schemas=(schema,),
    )
    target = state.obligations.known_ids[0]
    prior_strategy = StrategyMaterialization(
        Strategy("recovery", {"mode": "primary"}, schema=schema),
        capability_frontier=("read.primary",),
        target_obligation_ids=(target,),
        dependency_path=(target,),
        recovery_mode="primary",
        initial_transition_pattern=(_id("primary-transition"),),
        description="Try the primary path.",
    )
    alternate_strategy = StrategyMaterialization(
        Strategy("recovery", {"mode": "alternate"}, schema=schema),
        capability_frontier=("read.alternate",),
        target_obligation_ids=(target,),
        dependency_path=(),
        recovery_mode="alternate",
        initial_transition_pattern=(_id("alternate-transition"),),
        description="Use the alternate path.",
    )
    return state, prior_strategy, alternate_strategy


def test_strategy_paraphrase_is_not_a_material_change():
    _, _, task, governance, _, _, *_ = _state_and_progress()
    state, prior, _ = _strategy_state()
    paraphrase = StrategyMaterialization(
        prior.strategy,
        capability_frontier=prior.capability_frontier,
        target_obligation_ids=prior.target_obligation_ids,
        dependency_path=prior.dependency_path,
        recovery_mode=prior.recovery_mode,
        initial_transition_pattern=prior.initial_transition_pattern,
        description="A totally different way to say: try the primary path again.",
    )
    assert paraphrase.strategy_material_id == prior.strategy_material_id
    receipt = evaluate_strategy_change(
        task_id=task.task_id,
        governance_id=governance.governance_id,
        orchestration_state=state,
        prior_strategy=prior,
        proposed_strategy=paraphrase,
    )
    assert receipt.status is StrategyChangeStatus.REJECTED
    assert receipt.reason is StrategyChangeReason.SAME_STRATEGY_IDENTITY


def test_different_strategy_identity_also_requires_structured_difference():
    _, _, task, governance, _, _, *_ = _state_and_progress()
    state, prior, alternate = _strategy_state()
    semantic_clone = StrategyMaterialization(
        alternate.strategy,
        capability_frontier=prior.capability_frontier,
        target_obligation_ids=prior.target_obligation_ids,
        dependency_path=prior.dependency_path,
        recovery_mode=prior.recovery_mode,
        initial_transition_pattern=prior.initial_transition_pattern,
        description="Different parameter, no material recovery semantics.",
    )
    receipt = evaluate_strategy_change(
        task_id=task.task_id,
        governance_id=governance.governance_id,
        orchestration_state=state,
        prior_strategy=prior,
        proposed_strategy=semantic_clone,
    )
    assert receipt.reason is StrategyChangeReason.NOT_MATERIAL


def test_material_strategy_change_is_alternative_justification_not_progress():
    policy, _, task, governance, policy_receipt, runtime = _governed_runtime(
        "standard", session="strategy-recovery"
    )
    orchestration, prior_strategy, alternate = _strategy_state()
    no_progress = _progress(task, governance, orchestration, orchestration)
    state = ContinuationState.create(
        policy=policy,
        policy_receipt=policy_receipt,
        orchestration_state=orchestration,
        runtime_snapshot=runtime.snapshot,
        strategy=prior_strategy,
    )
    change = evaluate_strategy_change(
        task_id=task.task_id,
        governance_id=governance.governance_id,
        orchestration_state=orchestration,
        prior_strategy=prior_strategy,
        proposed_strategy=alternate,
    )
    assert change.status is StrategyChangeStatus.ADMITTED
    assert no_progress.classification is ProgressClassification.NO_PROGRESS
    _, decision = _request_and_decide(
        policy,
        policy_receipt,
        no_progress,
        state,
        strategy_change=change,
    )
    assert decision.granted
    assert decision.next_state.progress_state is ProgressState.STRATEGY_CHANGED
    assert decision.next_state.strategy_recoveries == 1


def test_strategy_change_receipt_must_bind_current_strategy_lineage():
    policy, _, task, governance, policy_receipt, runtime = _governed_runtime(
        "standard", session="stale-strategy-lineage"
    )
    orchestration, prior_strategy, alternate = _strategy_state()
    no_progress = _progress(task, governance, orchestration, orchestration)
    state = ContinuationState.create(
        policy=policy,
        policy_receipt=policy_receipt,
        orchestration_state=orchestration,
        runtime_snapshot=runtime.snapshot,
        strategy=prior_strategy,
    )
    change = evaluate_strategy_change(
        task_id=task.task_id,
        governance_id=governance.governance_id,
        orchestration_state=orchestration,
        prior_strategy=prior_strategy,
        proposed_strategy=alternate,
    )
    stale_state = replace(
        state, current_strategy_material_id=_id("newer-strategy-material")
    )
    _, decision = _request_and_decide(
        policy,
        policy_receipt,
        no_progress,
        stale_state,
        strategy_change=change,
    )
    assert (
        decision.receipt.denial_reason
        is LeaseDenialReason.STRATEGY_CHANGE_NOT_MATERIAL
    )


@pytest.mark.parametrize(
    ("sequence", "period"),
    (("aa", 1), ("abab", 2), ("abcabc", 3)),
)
def test_real_period_one_two_three_cycles_are_canonical(sequence, period):
    policy, _, task, governance, policy_receipt, runtime = _governed_runtime(
        "tiny", session=f"cycle-{period}"
    )
    for label in sequence:
        runtime.execute_read(
            "read",
            {"path": label},
            "cycle-dependency",
            lambda label=label: {"label": label},
        )
    assert runtime.terminal_cycle_period() == period
    evidence = CycleEvidence.from_snapshot(runtime.snapshot)
    assert evidence is not None
    assert evidence.period == period
    orchestration = _obligation_states(total=2)
    progress = _progress(task, governance, orchestration, orchestration)
    state = ContinuationState.create(
        policy=policy,
        policy_receipt=policy_receipt,
        orchestration_state=orchestration,
        runtime_snapshot=runtime.snapshot,
    )
    _, decision = _request_and_decide(
        policy,
        policy_receipt,
        progress,
        state,
        cycle_evidence=evidence,
    )
    assert not decision.granted
    assert decision.receipt.denial_reason is LeaseDenialReason.TERMINAL_CYCLE
    assert decision.next_state.progress_state is ProgressState.CYCLE_BLOCKED


def test_cycle_detection_survives_cache_hits_and_keeps_budgets_distinct():
    _, _, _, _, _, runtime = _governed_runtime(
        "tiny", session="cache-hidden-cycle"
    )
    for label in "abab":
        runtime.execute_read(
            "read",
            {"path": label},
            "same-dependency",
            lambda label=label: {"value": label},
        )
    snapshot = runtime.snapshot
    assert snapshot.requests == 4
    assert snapshot.executions == 2
    assert snapshot.cache_hits == 2
    evidence = CycleEvidence.from_snapshot(snapshot)
    assert evidence is not None and evidence.period == 2


def test_cycle_equivalent_strategy_is_rejected_but_breaking_change_can_continue():
    policy, _, task, governance, policy_receipt, runtime = _governed_runtime(
        "standard", session="cycle-breaking"
    )
    for label in "abab":
        runtime.execute_read(
            "read",
            {"path": label},
            "cycle",
            lambda label=label: label,
        )
    cycle = CycleEvidence.from_snapshot(runtime.snapshot)
    assert cycle is not None
    orchestration, prior_strategy, alternate = _strategy_state()
    no_progress = _progress(task, governance, orchestration, orchestration)
    state = ContinuationState.create(
        policy=policy,
        policy_receipt=policy_receipt,
        orchestration_state=orchestration,
        runtime_snapshot=runtime.snapshot,
        strategy=prior_strategy,
    )
    cycle_clone = StrategyMaterialization(
        alternate.strategy,
        capability_frontier=alternate.capability_frontier,
        target_obligation_ids=alternate.target_obligation_ids,
        dependency_path=alternate.dependency_path,
        recovery_mode=alternate.recovery_mode,
        initial_transition_pattern=cycle.transition_pattern * 2,
        description="Alternate words, same terminal cycle.",
    )
    rejected_change = evaluate_strategy_change(
        task_id=task.task_id,
        governance_id=governance.governance_id,
        orchestration_state=orchestration,
        prior_strategy=prior_strategy,
        proposed_strategy=cycle_clone,
        cycle_evidence=cycle,
    )
    assert rejected_change.reason is StrategyChangeReason.CYCLE_EQUIVALENT
    _, denied = _request_and_decide(
        policy,
        policy_receipt,
        no_progress,
        state,
        strategy_change=rejected_change,
        cycle_evidence=cycle,
    )
    assert (
        denied.receipt.denial_reason
        is LeaseDenialReason.STRATEGY_CHANGE_CYCLE_EQUIVALENT
    )

    admitted_change = evaluate_strategy_change(
        task_id=task.task_id,
        governance_id=governance.governance_id,
        orchestration_state=orchestration,
        prior_strategy=prior_strategy,
        proposed_strategy=alternate,
        cycle_evidence=cycle,
    )
    assert admitted_change.status is StrategyChangeStatus.ADMITTED
    _, granted = _request_and_decide(
        policy,
        policy_receipt,
        no_progress,
        state,
        strategy_change=admitted_change,
        cycle_evidence=cycle,
    )
    assert granted.granted
    assert granted.next_state.strategy_recoveries == 1


def test_strategy_recovery_count_is_finite():
    policy, _, task, governance, policy_receipt, runtime = _governed_runtime(
        "standard", session="recovery-ceiling"
    )
    orchestration, prior_strategy, alternate = _strategy_state()
    progress = _progress(task, governance, orchestration, orchestration)
    state = ContinuationState.create(
        policy=policy,
        policy_receipt=policy_receipt,
        orchestration_state=orchestration,
        runtime_snapshot=runtime.snapshot,
        strategy=prior_strategy,
    )
    state = replace(state, strategy_recoveries=policy.max_strategy_recoveries)
    change = evaluate_strategy_change(
        task_id=task.task_id,
        governance_id=governance.governance_id,
        orchestration_state=orchestration,
        prior_strategy=prior_strategy,
        proposed_strategy=alternate,
    )
    _, decision = _request_and_decide(
        policy,
        policy_receipt,
        progress,
        state,
        strategy_change=change,
    )
    assert (
        decision.receipt.denial_reason
        is LeaseDenialReason.STRATEGY_RECOVERY_EXHAUSTED
    )


def test_complete_task_never_receives_unnecessary_continuation():
    policy, _, task, governance, policy_receipt, runtime = _governed_runtime(
        "tiny", session="already-complete"
    )
    prior = _obligation_states(total=2, satisfied=1)
    complete = _obligation_states(total=2, satisfied=2)
    progress = _progress(task, governance, prior, complete)
    assert progress.task_complete
    state = ContinuationState.create(
        policy=policy,
        policy_receipt=policy_receipt,
        orchestration_state=complete,
        runtime_snapshot=runtime.snapshot,
    )
    _, decision = _request_and_decide(policy, policy_receipt, progress, state)
    assert decision.receipt.denial_reason is LeaseDenialReason.TASK_ALREADY_COMPLETE
    assert decision.next_state.progress_state is ProgressState.COMPLETE


def test_pending_grant_blocks_another_request_until_rust_applies_it():
    policy, _, _, _, policy_receipt, _, _, _, progress, state = (
        _state_and_progress("standard")
    )
    _, first = _request_and_decide(policy, policy_receipt, progress, state)
    assert first.next_state.has_pending_grant
    second_request = ContinuationRequest.from_state(
        first.next_state,
        progress=progress,
        requested_resources=policy.lease_schedule[1],
        requester=PrincipalAuthority.OPENAI_SUPERVISOR,
    )
    second = evaluate_continuation(
        first.next_state,
        second_request,
        policy=policy,
        policy_receipt=policy_receipt,
        progress=progress,
    )
    assert (
        second.receipt.denial_reason
        is LeaseDenialReason.PENDING_LEASE_APPLICATION
    )


def test_governance_ceiling_exhaustion_is_deterministic():
    policy, _, task, governance, policy_receipt, runtime = _governed_runtime(
        "standard", session="lease-ceiling"
    )
    orchestration_states = tuple(
        _obligation_states(total=4, satisfied=count) for count in range(4)
    )
    progress = _progress(task, governance, orchestration_states[0], orchestration_states[1])
    state = ContinuationState.create(
        policy=policy,
        policy_receipt=policy_receipt,
        orchestration_state=orchestration_states[1],
        runtime_snapshot=runtime.snapshot,
    )
    for index in range(policy.max_leases):
        if index:
            progress = _progress(
                task,
                governance,
                orchestration_states[index],
                orchestration_states[index + 1],
            )
            state = observe_continuation_context(
                state,
                policy=policy,
                orchestration_state=orchestration_states[index + 1],
                runtime_snapshot=runtime.snapshot,
                progress=progress,
            )
        _, decision = _request_and_decide(
            policy, policy_receipt, progress, state
        )
        assert isinstance(decision.receipt, LeaseGrantReceipt)
        application = runtime.apply_lease(decision.receipt)
        state = commit_lease_application(
            decision.next_state,
            policy=policy,
            grant=decision.receipt,
            application=application,
            runtime_snapshot=runtime.snapshot,
        )

    progress = _progress(
        task, governance, orchestration_states[2], orchestration_states[3]
    )
    state = observe_continuation_context(
        state,
        policy=policy,
        orchestration_state=orchestration_states[3],
        runtime_snapshot=runtime.snapshot,
        progress=progress,
    )
    request = ContinuationRequest.from_state(
        state,
        progress=progress,
        requested_resources=BudgetVector(request_delta=1),
        requester=PrincipalAuthority.OPENAI_SUPERVISOR,
    )
    exhausted = evaluate_continuation(
        state,
        request,
        policy=policy,
        policy_receipt=policy_receipt,
        progress=progress,
    )
    assert (
        exhausted.receipt.denial_reason
        is LeaseDenialReason.LEASE_CEILING_REACHED
    )
    assert exhausted.next_state.progress_state is ProgressState.LEASE_EXHAUSTED
    assert exhausted.next_state.leases_granted == policy.max_leases


def test_requested_amount_cannot_exceed_schedule_or_cumulative_ceiling():
    policy, _, _, _, policy_receipt, _, _, _, progress, state = (
        _state_and_progress()
    )
    excessive = replace(
        policy.lease_schedule[0],
        request_delta=policy.lease_schedule[0].request_delta + 1,
    )
    _, denied = _request_and_decide(
        policy,
        policy_receipt,
        progress,
        state,
        requested_resources=excessive,
    )
    assert (
        denied.receipt.denial_reason
        is LeaseDenialReason.AMOUNT_EXCEEDS_SCHEDULE
    )

    fabricated = replace(
        state,
        cumulative_granted=BudgetVector(request_delta=MAX_U64),
    )
    request = ContinuationRequest.from_state(
        fabricated,
        progress=progress,
        requested_resources=BudgetVector(request_delta=1),
        requester=PrincipalAuthority.OPENAI_SUPERVISOR,
    )
    denied = evaluate_continuation(
        fabricated,
        request,
        policy=policy,
        policy_receipt=policy_receipt,
        progress=progress,
    )
    assert denied.receipt.denial_reason is LeaseDenialReason.LEASE_CEILING_REACHED


def test_denials_are_finitely_bounded_by_request_policy():
    policy, _, _, _, policy_receipt, _, _, _, progress, state = (
        _state_and_progress("tiny", progressing=False)
    )
    for _ in range(policy.max_lease_requests):
        _, decision = _request_and_decide(
            policy, policy_receipt, progress, state
        )
        state = decision.next_state
    assert state.lease_requests == policy.max_lease_requests
    assert state.leases_denied == policy.max_lease_requests
    request = ContinuationRequest.from_state(
        state,
        progress=progress,
        requested_resources=policy.lease_schedule[0],
        requester=PrincipalAuthority.OPENAI_SUPERVISOR,
    )
    final = evaluate_continuation(
        state,
        request,
        policy=policy,
        policy_receipt=policy_receipt,
        progress=progress,
    )
    assert final.receipt.denial_reason is LeaseDenialReason.LEASE_REQUEST_LIMIT
    assert final.next_state is state


def test_checkpoint_resume_validates_exact_live_in_process_lineage():
    policy, _, _, _, policy_receipt, runtime, _, current, progress, state = (
        _state_and_progress()
    )
    checkpoint = ContinuationCheckpoint(
        state=state,
        policy=policy,
        orchestration_state=current,
        runtime_snapshot=runtime.snapshot,
        progress=progress,
    )
    assert (
        resume_continuation_checkpoint(
            checkpoint,
            live_state=state,
            policy=policy,
            orchestration_state=current,
            runtime_snapshot=runtime.snapshot,
            progress=progress,
        )
        is state
    )
    assert checkpoint.canonical_record()["trust_scope"] == (
        "structural-in-process-lineage-only"
    )
    assert checkpoint.checkpoint_id == ContinuationCheckpoint(
        state=state,
        policy=policy,
        orchestration_state=current,
        runtime_snapshot=runtime.snapshot,
        progress=progress,
    ).checkpoint_id


def test_stale_checkpoint_fails_closed_after_runtime_changes():
    policy, _, _, _, _, runtime, _, current, progress, state = (
        _state_and_progress()
    )
    checkpoint = ContinuationCheckpoint(
        state=state,
        policy=policy,
        orchestration_state=current,
        runtime_snapshot=runtime.snapshot,
        progress=progress,
    )
    runtime.record_retry()
    with pytest.raises(ValueError, match="runtime state is stale"):
        resume_continuation_checkpoint(
            checkpoint,
            live_state=state,
            policy=policy,
            orchestration_state=current,
            runtime_snapshot=runtime.snapshot,
            progress=progress,
        )


def test_compact_continuation_evidence_uses_aggregates_not_verbose_traces():
    policy, _, _, _, policy_receipt, runtime, _, current, progress, state = (
        _state_and_progress()
    )
    _, decision = _request_and_decide(policy, policy_receipt, progress, state)
    application = runtime.apply_lease(decision.receipt)
    state = commit_lease_application(
        decision.next_state,
        policy=policy,
        grant=decision.receipt,
        application=application,
        runtime_snapshot=runtime.snapshot,
    )
    evidence = ContinuationEvidenceReceipt(
        state=state,
        policy=policy,
        progress_records=(progress,),
        compact_execution_evidence_receipt_id=_id("v0.4-evidence"),
    )
    record = evidence.canonical_record()
    assert record["progress_events"] == 1
    assert record["leases_requested"] == 1
    assert record["leases_granted"] == 1
    assert "progress_records" not in record
    assert len(canonical_json(record).encode("utf-8")) <= 4_096
    checkpoint = ContinuationCheckpoint(
        state=state,
        policy=policy,
        orchestration_state=current,
        runtime_snapshot=runtime.snapshot,
        progress=progress,
        compact_evidence_receipt_id=evidence.receipt_id,
        relevant_receipt_id=application.receipt_id,
    )
    assert checkpoint.compact_evidence_receipt_id == evidence.receipt_id


def test_ai_projection_exposes_exact_remaining_capacity_and_recovery_actions():
    policy, _, _, _, policy_receipt, _, _, _, progress, state = (
        _state_and_progress(progressing=False)
    )
    _, decision = _request_and_decide(policy, policy_receipt, progress, state)
    projection = decision.next_state.compact_projection(policy)
    assert projection["current_progress_classification"] == "no_progress"
    assert projection["leases_used"] == 0
    assert projection["leases_remaining"] == 1
    assert projection["last_lease_decision"] == "denied"
    assert projection["last_denial_reason"] == (
        LeaseDenialReason.NO_MEASURABLE_PROGRESS.value
    )
    assert "provide_objective_progress" in projection["legal_recovery_actions"]
    assert projection["remaining_total_continuation_ceiling"] == (
        policy.continuation_capacity.canonical_record()
    )


@pytest.mark.parametrize(
    "reason",
    (
        ContinuationPartialReason.LEASE_CEILING_EXHAUSTED,
        ContinuationPartialReason.NO_PROGRESS,
        ContinuationPartialReason.TERMINAL_CYCLE,
        ContinuationPartialReason.STRATEGY_RECOVERY_EXHAUSTED,
    ),
)
def test_partial_finalization_is_never_accepted_or_complete(reason):
    policy, _, _, _, _, runtime, _, current, progress, state = (
        _state_and_progress()
    )
    state = replace(
        state,
        progress_state={
            ContinuationPartialReason.LEASE_CEILING_EXHAUSTED: (
                ProgressState.LEASE_EXHAUSTED
            ),
            ContinuationPartialReason.NO_PROGRESS: ProgressState.STALLED,
            ContinuationPartialReason.TERMINAL_CYCLE: ProgressState.CYCLE_BLOCKED,
            ContinuationPartialReason.STRATEGY_RECOVERY_EXHAUSTED: (
                ProgressState.STALLED
            ),
        }[reason],
    )
    checkpoint = ContinuationCheckpoint(
        state=state,
        policy=policy,
        orchestration_state=current,
        runtime_snapshot=runtime.snapshot,
        progress=progress,
        partial_reason=reason,
    )
    partial = ContinuationPartialReceipt(
        state=state,
        checkpoint=checkpoint,
        reason=reason,
    )
    record = partial.canonical_record()
    assert record["status"] == "partial"
    assert record["task_complete"] is False
    assert "accepted" not in record.values()
    with pytest.raises((TypeError, FrozenInstanceError)):
        partial.reason = ContinuationPartialReason.NO_PROGRESS


def test_partial_receipt_rejects_reason_mismatch():
    policy, _, _, _, _, runtime, _, current, progress, state = (
        _state_and_progress()
    )
    checkpoint = ContinuationCheckpoint(
        state=state,
        policy=policy,
        orchestration_state=current,
        runtime_snapshot=runtime.snapshot,
        progress=progress,
        partial_reason=ContinuationPartialReason.NO_PROGRESS,
    )
    with pytest.raises(ValueError, match="reason does not match"):
        ContinuationPartialReceipt(
            state=state,
            checkpoint=checkpoint,
            reason=ContinuationPartialReason.TERMINAL_CYCLE,
        )


def test_watchdog_expiry_is_observational_partial_not_completion_or_lease_exhaustion():
    policy, _, _, _, _, runtime, _, current, progress, state = (
        _state_and_progress()
    )
    observation = WatchdogObservation(
        state.task_id,
        state.governance_id,
        state.orchestration_state_id,
        state.runtime_state_id,
        state.continuation_state_id,
        60_000,
        lease_exhausted=False,
    )
    record = observation.canonical_record()
    assert record["correctness_authority"] is False
    assert record["task_complete"] is False
    assert record["lease_exhausted"] is False
    checkpoint = ContinuationCheckpoint(
        state=state,
        policy=policy,
        orchestration_state=current,
        runtime_snapshot=runtime.snapshot,
        progress=progress,
        partial_reason=ContinuationPartialReason.WATCHDOG_EXPIRED,
    )
    partial = ContinuationPartialReceipt(
        state=state,
        checkpoint=checkpoint,
        reason=ContinuationPartialReason.WATCHDOG_EXPIRED,
        watchdog_observation=observation,
    )
    assert partial.canonical_record()["task_complete"] is False
    assert partial.reason is ContinuationPartialReason.WATCHDOG_EXPIRED
    # Observed wall-clock magnitude is not correctness identity.
    later = replace(observation, elapsed_milliseconds=120_000)
    assert later.observation_id == observation.observation_id


def test_checkpoint_and_partial_records_are_byte_deterministic():
    policy, _, _, _, _, runtime, _, current, progress, state = (
        _state_and_progress()
    )
    kwargs = dict(
        state=state,
        policy=policy,
        orchestration_state=current,
        runtime_snapshot=runtime.snapshot,
        progress=progress,
        partial_reason=ContinuationPartialReason.NO_PROGRESS,
    )
    left = ContinuationCheckpoint(**kwargs)
    right = ContinuationCheckpoint(**kwargs)
    assert canonical_json(left.canonical_record()) == canonical_json(
        right.canonical_record()
    )
    assert left.checkpoint_id == right.checkpoint_id
    left_partial = ContinuationPartialReceipt(
        state=state,
        checkpoint=left,
        reason=ContinuationPartialReason.NO_PROGRESS,
    )
    right_partial = ContinuationPartialReceipt(
        state=state,
        checkpoint=right,
        reason=ContinuationPartialReason.NO_PROGRESS,
    )
    assert left_partial.partial_id == right_partial.partial_id


def test_legacy_runtime_snapshot_and_state_identity_have_no_continuation_fields():
    left = RustRuntimeSession("legacy-compatible")
    right = RustRuntimeSession("legacy-compatible")
    assert left.snapshot.state_id == right.snapshot.state_id
    assert left.snapshot.continuation is None
    assert "continuation" not in left.snapshot.canonical_record()


def test_continuation_session_requires_exact_policy_receipt_pair():
    policy, _, _, _, policy_receipt, _, *_ = _state_and_progress()
    with pytest.raises(ValueError, match="supplied together"):
        RustRuntimeSession("missing-receipt", continuation_policy=policy)
    with pytest.raises(ValueError, match="supplied together"):
        RustRuntimeSession(
            "missing-policy", continuation_policy_receipt=policy_receipt
        )


def test_records_are_immutable_and_domain_separated():
    policy, _, _, _, policy_receipt, _, _, _, progress, state = (
        _state_and_progress()
    )
    request, decision = _request_and_decide(
        policy, policy_receipt, progress, state
    )
    assert request.continuation_request_id != progress.progress_id
    assert decision.receipt.lease_grant_id != decision.receipt.receipt_id
    assert decision.next_state.continuation_state_id not in {
        request.continuation_request_id,
        decision.receipt.lease_grant_id,
        decision.receipt.receipt_id,
    }
    with pytest.raises((FrozenInstanceError, TypeError)):
        decision.receipt.lease_index = 9


def test_model_free_budget_benchmark_covers_required_scenarios():
    report = run_budget_profile_benchmark()
    assert report["benchmark_only"] is True
    assert report["correctness_authority"] is False
    assert report["wall_clock_in_correctness_identity"] is False
    assert len(report["policy_comparisons"]) == 4
    assert len(report["named_experimental_profiles"]) == 4
    scenario_names = {item["scenario"] for item in report["results"]}
    assert scenario_names == {
        "activity_without_progress",
        "cache_heavy",
        "ceiling_exhaustion",
        "long_genuinely_progressing",
        "material_strategy_recovery",
        "periodic_loop",
        "retry_heavy",
        "short_success",
        "strategy_paraphrase",
    }
    for result in report["results"]:
        assert BudgetVector.from_record(result["base_budget_consumed"]).is_within(
            BudgetVector.from_record(result["base_budget"])
        )
        if result["scenario"] == "short_success":
            assert result["task_outcome"] == "complete"
            assert result["lease_count"] == 0
        elif result["scenario"] == "activity_without_progress":
            assert result["task_outcome"] == "denied"
            assert result["no_progress_denials"] == 1
        elif result["scenario"] == "periodic_loop":
            assert result["cycle_denials"] == 1
        elif result["scenario"] == "material_strategy_recovery":
            assert result["task_outcome"] == "complete"
            assert result["strategy_change_events"] == 1
        elif result["scenario"] == "strategy_paraphrase":
            assert result["denial_reason"] == "strategy_change_not_material"
            assert result["strategy_change_events"] == 1
        elif result["scenario"] == "ceiling_exhaustion":
            assert result["task_outcome"] == "partial"
            assert result["partial_finalization_reason"] == (
                ContinuationPartialReason.LEASE_CEILING_EXHAUSTED.value
            )


def test_geometric_budget_is_a_candidate_not_architectural_law():
    policies = benchmark_policies()
    keys = {item.policy_key for item in policies}
    assert "benchmark.geometric_candidate" in keys
    assert len(keys) == 4
    report = run_budget_profile_benchmark()
    assert "best_policy" not in report
    assert "recommended_policy" not in report


def test_budget_benchmark_is_byte_deterministic():
    left = run_budget_profile_benchmark()
    right = run_budget_profile_benchmark()
    assert canonical_json(left) == canonical_json(right)
    assert left["report_id"] == right["report_id"]


def test_v0_5_reference_fixture_matches_checked_in_canonical_bytes():
    fixture_path = (
        Path(__file__).parents[1]
        / "fixtures/v0.5/progress-continuation-reference.json"
    )
    checked_in = fixture_path.read_text(encoding="utf-8")
    fixture = v0_5_reference_fixture()
    assert checked_in.endswith("\n")
    assert checked_in == canonical_json(fixture) + "\n"
    assert fixture["lease_decisions"]["first_grant"]["status"] == "granted"
    assert fixture["lease_decisions"]["no_progress_denial"]["status"] == (
        "denied"
    )
    assert fixture["partial_finalization"]["record"]["status"] == "partial"


def test_v0_5_budget_fixture_matches_checked_in_canonical_bytes():
    fixture_path = (
        Path(__file__).parents[1] / "fixtures/v0.5/budget-profile-benchmark.json"
    )
    checked_in = fixture_path.read_text(encoding="utf-8")
    fixture = v0_5_budget_benchmark_fixture()
    assert checked_in.endswith("\n")
    assert checked_in == canonical_json(fixture) + "\n"
    assert fixture["benchmark_only"] is True
    assert fixture["correctness_authority"] is False
