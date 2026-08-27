from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from ibae.canonical import canonical_fingerprint, canonical_json, domain_fingerprint
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
    default_obligation_progress_contract,
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
    ToolAuthorityClass,
    ToolPermission,
)
from ibae.obligations import Obligation, ObligationStatus
from ibae.orchestration import (
    ACTION_ID_DOMAIN,
    ActionProposal,
    AdmissionDecision,
    Capability,
    DecisionStatus,
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
    RuntimeReceipt,
    RuntimeSnapshot,
    RuntimeTransition,
    RustRuntimeSession,
)


# Test-harness lookup only; this object identity never enters protocol state.
_REQUEST_AUTHORITIES: dict[int, object] = {}
_ACTIVE_REQUEST_AUTHORITY = object()


def _id(label: str) -> str:
    return canonical_fingerprint({"label": label})


def _authority(runtime: RustRuntimeSession) -> object:
    return _REQUEST_AUTHORITIES[id(runtime)]


def _governed_runtime(
    profile: str = "tiny",
    *,
    session: str = "continuation",
    progress_contract: ProgressMeasureContract | None = None,
):
    continuation_policy = experimental_continuation_profile(
        profile,
        progress_contract=progress_contract,
    )
    governance_policy = GovernancePolicy(
        policy_key="continuation.reference",
        policy_version=1,
        task_profile=profile,
        task_profile_version=1,
        provider_authority=ProviderAuthority.OPENAI,
        tool_permissions=(
            ToolPermission(
                "progress_counter",
                ToolAuthorityClass.PURE_READ,
                False,
                True,
            ),
        ),
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
    runtime, requester_authority = RustRuntimeSession.create_continuation(
        session,
        continuation_policy=continuation_policy,
        continuation_policy_receipt=policy_receipt,
    )
    _REQUEST_AUTHORITIES[id(runtime)] = requester_authority
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
    return default_obligation_progress_contract()


def _progress(task, governance, prior, current):
    return evaluate_progress(
        task_id=task.task_id,
        governance_id=governance.governance_id,
        contract=_progress_contract(),
        prior_state=prior,
        current_state=current,
    )


def _counter_source(
    governance_policy,
    task,
    governance,
    dimension_key,
    value,
    basis_identity,
    epistemic_class,
    *,
    source,
):
    capability = Capability(
        "progress_counter",
        ReplaySafety.CACHEABLE_READ,
        "Read one governance-admitted objective progress counter.",
        semantic_argument_keys=("source",),
    )
    arguments = {"source": source}
    proposal = ActionProposal(
        f"progress-counter.{source}",
        capability.name,
        arguments,
        target_obligation_ids=(_id(f"counter-obligation-{source}"),),
    )
    dependency_fingerprint = _id(f"counter-dependency-{source}")
    decision = AdmissionDecision(
        proposal_id=proposal.proposal_id,
        proposal_key=proposal.proposal_key,
        status=DecisionStatus.ADMITTED,
        logical_tick=1,
        action_id=domain_fingerprint(
            ACTION_ID_DOMAIN,
            {
                "arguments": capability.normalize_arguments(proposal.arguments),
                "capability_id": capability.capability_id,
                "dependency_state_id": dependency_fingerprint,
            },
        ),
    )
    tool_admission = GovernanceWrapper(governance_policy).admit_tool(
        task,
        governance,
        decision,
        proposal,
        capability,
        ToolAuthorityClass.PURE_READ,
        dependency_state_id=dependency_fingerprint,
        requester=PrincipalAuthority.DETERMINISTIC_ORCHESTRATOR,
    )
    runtime = RustRuntimeSession(f"counter-evidence-{source}")
    observation = {
        "basis_identity": basis_identity,
        "dimension_key": dimension_key,
        "epistemic_class": epistemic_class.value,
        "governance_id": governance.governance_id,
        "task_id": task.task_id,
        "value": value,
    }
    transition = runtime.execute_admitted_read(
        decision,
        proposal,
        capability,
        dependency_fingerprint,
        lambda: observation,
    )
    return transition, tool_admission


def _counter_evidence(
    governance_policy,
    task,
    governance,
    dimension_key,
    value,
    basis_identity,
    epistemic_class,
    *,
    source,
):
    return ProgressCounterEvidence(
        *_counter_source(
            governance_policy,
            task,
            governance,
            dimension_key,
            value,
            basis_identity,
            epistemic_class,
            source=source,
        )
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
        runtime_session=runtime,
        orchestration_state=current,
        runtime_snapshot=runtime.snapshot,
        progress=progress,
    )
    return (*bundle, prior, current, progress, state)


def _request_and_decide(
    policy,
    policy_receipt,
    runtime,
    progress,
    state,
    *,
    requested_resources=None,
    requester=PrincipalAuthority.OPENAI_SUPERVISOR,
    strategy_change=None,
    cycle_evidence=None,
    benchmark_observation=None,
    requester_authority=_ACTIVE_REQUEST_AUTHORITY,
):
    if requester_authority is _ACTIVE_REQUEST_AUTHORITY:
        normalized_requester = ContinuationRequester.normalize(requester)
        requester_authority = (
            _REQUEST_AUTHORITIES[id(runtime)]
            if normalized_requester is ContinuationRequester.OPENAI_SUPERVISOR
            else None
        )
    request = ContinuationRequest.from_state(
        state,
        progress=progress,
        requested_resources=(
            policy.lease_schedule[state.leases_granted]
            if requested_resources is None
            else requested_resources
        ),
        requester=requester,
        requester_authority=requester_authority,
        strategy_change=strategy_change,
    )
    decision = evaluate_continuation(
        state,
        request,
        runtime_session=runtime,
        policy=policy,
        policy_receipt=policy_receipt,
        progress=progress,
        strategy_change=strategy_change,
        cycle_evidence=cycle_evidence,
        benchmark_observation=benchmark_observation,
    )
    return request, decision


def _structural_grant(grant: LeaseGrantReceipt, **overrides):
    values = {
        "task_id": grant.task_id,
        "governance_id": grant.governance_id,
        "governance_receipt_id": grant.governance_receipt_id,
        "continuation_policy_id": grant.continuation_policy_id,
        "continuation_policy_receipt_id": grant.continuation_policy_receipt_id,
        "continuation_request_id": grant.continuation_request_id,
        "prior_continuation_state_id": grant.prior_continuation_state_id,
        "orchestration_state_id": grant.orchestration_state_id,
        "runtime_session_id": grant.runtime_session_id,
        "prior_runtime_state_id": grant.prior_runtime_state_id,
        "progress_id": grant.progress_id,
        "strategy_change_id": grant.strategy_change_id,
        "lease_index": grant.lease_index,
        "granted_resources": grant.granted_resources,
        "cumulative_granted": grant.cumulative_granted,
        "total_ceiling": grant.total_ceiling,
        "decision_logical_tick": grant.decision_logical_tick,
    }
    values.update(overrides)
    return LeaseGrantReceipt(**values)


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
            _progress_contract().contract_id,
        )
    with pytest.raises(ValueError, match="only measurable_progress"):
        ContinuationPolicy(
            "bad.progress",
            1,
            "tiny",
            1,
            base,
            (lease,),
            base.add_checked(lease),
            2,
            _progress_contract().contract_id,
            admitted_progress=(ProgressClassification.NO_PROGRESS,),
        )
    with pytest.raises(ValueError, match="only measurable_progress"):
        ContinuationPolicy(
            "bad.new-information",
            1,
            "tiny",
            1,
            base,
            (lease,),
            base.add_checked(lease),
            2,
            _progress_contract().contract_id,
            admitted_progress=(ProgressClassification.NEW_INFORMATION,),
        )


def test_policy_reserves_a_terminal_decision_after_the_lease_schedule():
    base = BudgetVector(2, 2, 1, 0, 6)
    lease = BudgetVector(1, 1, 0, 0, 1)
    with pytest.raises(ValueError, match="reserve one terminal decision"):
        ContinuationPolicy(
            "no.terminal.decision",
            1,
            "tiny",
            1,
            base,
            (lease,),
            base.add_checked(lease),
            1,
            _progress_contract().contract_id,
        )


def test_policy_retains_the_full_short_cycle_detection_window():
    base = BudgetVector(2, 2, 1, 0, 5)
    lease = BudgetVector(1, 1, 0, 0, 1)
    with pytest.raises(ValueError, match="six-transition cycle window"):
        ContinuationPolicy(
            "short.cycle.history",
            1,
            "tiny",
            1,
            base,
            (lease,),
            base.add_checked(lease),
            2,
            _progress_contract().contract_id,
        )


def test_obligation_progress_direction_cannot_be_inverted():
    with pytest.raises(ValueError, match="unsafe direction"):
        ProgressDimension(
            "unsafe.unsatisfied",
            ProgressSource.UNSATISFIED_OBLIGATION_COUNT,
            ProgressDirection.INCREASE,
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


def test_newly_blocked_obligations_do_not_authorize_continuation():
    policy, _, task, governance, policy_receipt, runtime = _governed_runtime(
        "tiny", session="newly-blocked"
    )
    prior = _obligation_states(total=2)
    blocked = OrchestrationState.create(
        tuple(
            item.with_status(
                ObligationStatus.BLOCKED,
                block_reason="Newly discovered external blocker.",
            )
            if index == 0
            else item
            for index, item in enumerate(prior.obligations.obligations)
        )
    )
    progress = _progress(task, governance, prior, blocked)
    assert progress.classification is ProgressClassification.INCOMPARABLE
    state = ContinuationState.create(
        policy=policy,
        policy_receipt=policy_receipt,
        runtime_session=runtime,
        orchestration_state=blocked,
        runtime_snapshot=runtime.snapshot,
        progress=progress,
    )
    _, decision = _request_and_decide(
        policy, policy_receipt, runtime, progress, state
    )
    assert (
        decision.receipt.denial_reason
        is LeaseDenialReason.NO_MEASURABLE_PROGRESS
    )


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
    runtime.execute_read("read", {"path": "b"}, "same", lambda: {"ok": True})
    assert runtime.snapshot.requests == 2
    assert runtime.snapshot.executions == 2
    assert progress.classification is ProgressClassification.NO_PROGRESS
    state = observe_continuation_context(
        state,
        runtime_session=runtime,
        policy=policy,
        orchestration_state=_obligation_states(total=3, satisfied=0),
        runtime_snapshot=runtime.snapshot,
    )
    _, decision = _request_and_decide(
        policy, policy_receipt, runtime, progress, state
    )
    assert not decision.granted
    assert decision.receipt.denial_reason is LeaseDenialReason.NO_MEASURABLE_PROGRESS


def test_progress_record_claims_are_derived_from_bound_measures_and_state():
    *_, progress, _ = _state_and_progress(progressing=False)
    with pytest.raises(ValueError, match="classification does not match"):
        replace(
            progress,
            classification=ProgressClassification.MEASURABLE_PROGRESS,
        )
    with pytest.raises(ValueError, match="completion does not match"):
        replace(progress, task_complete=True)


def test_model_confidence_theatre_cannot_change_no_progress_denial():
    def decision(benchmark_observation=None):
        policy, _, _, _, policy_receipt, runtime, _, _, progress, state = (
            _state_and_progress(progressing=False)
        )
        request = ContinuationRequest.from_state(
            state,
            progress=progress,
            requested_resources=policy.lease_schedule[0],
            requester=PrincipalAuthority.OPENAI_SUPERVISOR,
            requester_authority=_authority(runtime),
        )
        return evaluate_continuation(
            state,
            request,
            runtime_session=runtime,
            policy=policy,
            policy_receipt=policy_receipt,
            progress=progress,
            benchmark_observation=benchmark_observation,
        )

    plain = decision()
    theatrical = decision({"model_statement": "I am 99% done"})
    assert plain.receipt.canonical_record() == theatrical.receipt.canonical_record()
    assert plain.next_state.canonical_record() == theatrical.next_state.canonical_record()


def test_benchmark_observations_are_non_authoritative_for_grants():
    def decision(benchmark_observation):
        policy, _, _, _, policy_receipt, runtime, _, _, progress, state = (
            _state_and_progress()
        )
        request = ContinuationRequest.from_state(
            state,
            progress=progress,
            requested_resources=policy.lease_schedule[0],
            requester=PrincipalAuthority.OPENAI_SUPERVISOR,
            requester_authority=_authority(runtime),
        )
        return evaluate_continuation(
            state,
            request,
            runtime_session=runtime,
            policy=policy,
            policy_receipt=policy_receipt,
            progress=progress,
            benchmark_observation=benchmark_observation,
        )

    left = decision({"wall_clock_ms": 1, "rank": "best"})
    right = decision({"wall_clock_ms": 999999, "rank": "worst"})
    assert left.receipt.canonical_record() == right.receipt.canonical_record()
    assert left.next_state.continuation_state_id == right.next_state.continuation_state_id


def test_regression_new_information_and_incomparable_are_distinct():
    policy, governance_policy, task, governance, _, _, *_ = (
        _state_and_progress()
    )
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
        "failing": _counter_evidence(
            governance_policy,
            task,
            governance,
            "failing",
            7,
            basis,
            EpistemicClass.OBSERVED,
            source="prior-failing",
        ),
        "gates": _counter_evidence(
            governance_policy,
            task,
            governance,
            "gates",
            3,
            basis,
            EpistemicClass.DERIVED,
            source="prior-gates",
        ),
    }
    current_evidence = {
        "failing": _counter_evidence(
            governance_policy,
            task,
            governance,
            "failing",
            3,
            basis,
            EpistemicClass.OBSERVED,
            source="current-failing",
        ),
        "gates": _counter_evidence(
            governance_policy,
            task,
            governance,
            "gates",
            2,
            basis,
            EpistemicClass.DERIVED,
            source="current-gates",
        ),
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
    reordered = evaluate_progress(
        task_id=task.task_id,
        governance_id=governance.governance_id,
        contract=contract,
        prior_state=fewer_satisfied,
        current_state=fewer_satisfied,
        prior_evidence={
            "gates": prior_evidence["gates"],
            "failing": prior_evidence["failing"],
        },
        current_evidence={
            "gates": current_evidence["gates"],
            "failing": current_evidence["failing"],
        },
    )
    assert reordered.canonical_record() == mixed.canonical_record()


def test_model_proposed_external_counter_is_rejected():
    with pytest.raises(ValueError, match="observed or deterministically derived"):
        task_bundle = _governed_runtime(session="model-counter")
        governance_policy, task, governance = task_bundle[1:4]
        _counter_evidence(
            governance_policy,
            task,
            governance,
            "tests.failing",
            1,
            _id("basis"),
            EpistemicClass.MODEL_PROPOSED,
            source="model-proposed",
        )


def test_external_counter_requires_source_bound_native_provenance():
    _, governance_policy, task, governance, _, _ = _governed_runtime(
        session="structural-counter"
    )
    live, admission = _counter_source(
        governance_policy,
        task,
        governance,
        "tests.failing",
        1,
        _id("structural-counter-basis"),
        EpistemicClass.OBSERVED,
        source="structural",
    )
    structural = RuntimeTransition(
        live.observation,
        RuntimeReceipt(live.receipt.canonical_record()),
    )
    with pytest.raises(ValueError, match="source-bound"):
        ProgressCounterEvidence(structural, admission)

    _, unrelated_admission = _counter_source(
        governance_policy,
        task,
        governance,
        "tests.failing",
        1,
        _id("structural-counter-basis"),
        EpistemicClass.OBSERVED,
        source="unrelated",
    )
    with pytest.raises(ValueError, match="does not match tool governance"):
        ProgressCounterEvidence(live, unrelated_admission)


def test_external_counter_progress_must_continue_from_the_live_endpoint():
    contract = ProgressMeasureContract(
        "external.contiguous",
        1,
        (
            ProgressDimension(
                "tests.failing",
                ProgressSource.GOVERNED_EXTERNAL_COUNTER,
                ProgressDirection.DECREASE,
            ),
        ),
    )
    policy, governance_policy, task, governance, policy_receipt, runtime = (
        _governed_runtime(
            "standard",
            session="external-endpoint-continuity",
            progress_contract=contract,
        )
    )
    work = _obligation_states(total=1)
    basis = _id("external-contiguous-basis")

    def counter(value, source):
        return _counter_evidence(
            governance_policy,
            task,
            governance,
            "tests.failing",
            value,
            basis,
            EpistemicClass.OBSERVED,
            source=source,
        )

    progress = evaluate_progress(
        task_id=task.task_id,
        governance_id=governance.governance_id,
        contract=contract,
        prior_state=work,
        current_state=work,
        prior_evidence={"tests.failing": counter(10, "initial-prior")},
        current_evidence={"tests.failing": counter(9, "initial-current")},
    )
    state = ContinuationState.create(
        policy=policy,
        policy_receipt=policy_receipt,
        runtime_session=runtime,
        orchestration_state=work,
        runtime_snapshot=runtime.snapshot,
        progress=progress,
    )
    _, first = _request_and_decide(
        policy, policy_receipt, runtime, progress, state
    )
    application = runtime.apply_lease(first.receipt)
    state = commit_lease_application(
        first.next_state,
        runtime_session=runtime,
        policy=policy,
        grant=first.receipt,
        application=application,
        runtime_snapshot=runtime.snapshot,
    )
    assert state.last_consumed_external_progress_endpoint_id == (
        progress.current_external_endpoint_id
    )

    replay = evaluate_progress(
        task_id=task.task_id,
        governance_id=governance.governance_id,
        contract=contract,
        prior_state=work,
        current_state=work,
        prior_evidence={"tests.failing": counter(10, "replay-prior")},
        current_evidence={"tests.failing": counter(9, "replay-current")},
    )
    assert replay.classification is ProgressClassification.MEASURABLE_PROGRESS
    assert replay.progress_id != progress.progress_id
    with pytest.raises(ValueError, match="continue from the live endpoint"):
        observe_continuation_context(
            state,
            runtime_session=runtime,
            policy=policy,
            orchestration_state=work,
            runtime_snapshot=runtime.snapshot,
            progress=replay,
        )

    fresh = evaluate_progress(
        task_id=task.task_id,
        governance_id=governance.governance_id,
        contract=contract,
        prior_state=work,
        current_state=work,
        prior_evidence={"tests.failing": counter(9, "fresh-prior")},
        current_evidence={"tests.failing": counter(8, "fresh-current")},
    )
    state = observe_continuation_context(
        state,
        runtime_session=runtime,
        policy=policy,
        orchestration_state=work,
        runtime_snapshot=runtime.snapshot,
        progress=fresh,
    )
    _, second = _request_and_decide(
        policy, policy_receipt, runtime, fresh, state
    )
    assert isinstance(second.receipt, LeaseGrantReceipt)


def test_unknown_to_known_external_measure_is_new_information_not_progress():
    _, governance_policy, task, governance, _, _, prior, current, _, _ = (
        _state_and_progress()
    )
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
    evidence = _counter_evidence(
        governance_policy,
        task,
        governance,
        "review.findings",
        5,
        _id("review-basis"),
        EpistemicClass.OBSERVED,
        source="review-receipt",
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
        runtime,
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


def test_supervisor_label_without_native_request_authority_is_denied():
    policy, _, _, _, policy_receipt, runtime, _, _, progress, state = (
        _state_and_progress()
    )
    request = ContinuationRequest.from_state(
        state,
        progress=progress,
        requested_resources=policy.lease_schedule[0],
        requester=PrincipalAuthority.OPENAI_SUPERVISOR,
    )
    decision = evaluate_continuation(
        state,
        request,
        runtime_session=runtime,
        policy=policy,
        policy_receipt=policy_receipt,
        progress=progress,
    )
    assert decision.receipt.denial_reason is LeaseDenialReason.UNAUTHORIZED_REQUESTER
    assert decision.next_state is state
    with pytest.raises(TypeError, match="requester_authority is not trusted"):
        ContinuationRequest.from_state(
            state,
            progress=progress,
            requested_resources=policy.lease_schedule[0],
            requester=PrincipalAuthority.OPENAI_SUPERVISOR,
            requester_authority=object(),
        )
    native = object.__getattribute__(runtime, "_RustRuntimeSession__native")
    with pytest.raises(ValueError, match="already issued"):
        native.take_continuation_request_authority()


def test_native_session_pins_continuation_engine_before_request(monkeypatch):
    import ibae.continuation as continuation_module
    import ibae._runtime as native_runtime

    assert not hasattr(native_runtime, "_register_continuation_engine")

    def substituted_engine(*_args, **_kwargs):
        raise AssertionError("mutable module evaluator must not be consulted")

    monkeypatch.setattr(
        continuation_module, "_evaluate_continuation", substituted_engine
    )
    monkeypatch.setattr(
        continuation_module, "_observe_continuation_context", substituted_engine
    )
    monkeypatch.setattr(
        continuation_module, "_commit_lease_application", substituted_engine
    )
    policy, _, _, _, policy_receipt, runtime, _, current, progress, state = (
        _state_and_progress()
    )
    _, decision = _request_and_decide(
        policy, policy_receipt, runtime, progress, state
    )
    assert isinstance(decision.receipt, LeaseGrantReceipt)
    application = runtime.apply_lease(decision.receipt)
    committed = commit_lease_application(
        decision.next_state,
        runtime_session=runtime,
        policy=policy,
        grant=decision.receipt,
        application=application,
        runtime_snapshot=runtime.snapshot,
    )
    committed_state_id = committed.continuation_state_id
    observed = observe_continuation_context(
        committed,
        runtime_session=runtime,
        policy=policy,
        orchestration_state=current,
        runtime_snapshot=runtime.snapshot,
    )
    assert observed.continuation_state_id == committed_state_id


@pytest.mark.parametrize(
    "target_name",
    (
        "_evaluate_continuation",
        "_observe_continuation_context",
        "_commit_lease_application",
    ),
)
def test_native_engine_rejects_mutated_pinned_function_code(
    monkeypatch, target_name
):
    import ibae.continuation as continuation_module

    def substituted_engine(*_args, **_kwargs):
        return None

    target = getattr(continuation_module, target_name)
    monkeypatch.setattr(target, "__code__", substituted_engine.__code__)
    with pytest.raises(ValueError, match="engine integrity"):
        _state_and_progress()


def test_native_engine_rejects_mutated_evaluator_global(monkeypatch):
    import ibae.continuation as continuation_module

    def substituted_denial(*_args, **_kwargs):
        return None

    monkeypatch.setitem(
        continuation_module._evaluate_continuation.__globals__,
        "_deny_continuation",
        substituted_denial,
    )
    with pytest.raises(ValueError, match="engine integrity"):
        _state_and_progress()


def test_native_engine_rejects_mutated_imported_callable_dependency(monkeypatch):
    import dataclasses

    policy, _, _, _, _, runtime, _, current, _, state = _state_and_progress()

    def substituted_replace(*_args, **_kwargs):
        return None

    with monkeypatch.context() as active:
        active.setattr(dataclasses.replace, "__code__", substituted_replace.__code__)
        with pytest.raises(ValueError, match="engine integrity"):
            observe_continuation_context(
                state,
                runtime_session=runtime,
                policy=policy,
                orchestration_state=current,
                runtime_snapshot=runtime.snapshot,
            )


@pytest.mark.parametrize(
    "descriptor_function",
    (
        CycleEvidence.__dict__["from_snapshot"].__func__,
        RustRuntimeSession.__dict__["_invocation"].__func__,
        ContinuationState.__dict__["has_pending_grant"].fget,
    ),
)
def test_native_engine_rejects_mutated_descriptor_function_code(
    monkeypatch, descriptor_function
):
    def substituted_descriptor(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        descriptor_function,
        "__code__",
        substituted_descriptor.__code__,
    )
    with pytest.raises(ValueError, match="engine integrity"):
        _state_and_progress()


@pytest.mark.parametrize(
    "target_name",
    (
        "_evaluate_continuation",
        "_observe_continuation_context",
        "_commit_lease_application",
    ),
)
def test_native_engine_rechecks_integrity_at_each_authority_entry(
    monkeypatch, target_name
):
    import ibae.continuation as continuation_module

    policy, _, _, _, policy_receipt, runtime, _, current, progress, state = (
        _state_and_progress()
    )
    pending = None
    application = None
    if target_name == "_commit_lease_application":
        _, pending = _request_and_decide(
            policy, policy_receipt, runtime, progress, state
        )
        application = runtime.apply_lease(pending.receipt)

    def substituted_engine(*_args, **_kwargs):
        return None

    target = getattr(continuation_module, target_name)
    monkeypatch.setattr(target, "__code__", substituted_engine.__code__)
    with pytest.raises(ValueError, match="engine integrity"):
        if target_name == "_evaluate_continuation":
            _request_and_decide(
                policy, policy_receipt, runtime, progress, state
            )
        elif target_name == "_observe_continuation_context":
            observe_continuation_context(
                state,
                runtime_session=runtime,
                policy=policy,
                orchestration_state=current,
                runtime_snapshot=runtime.snapshot,
            )
        else:
            assert pending is not None
            assert application is not None
            commit_lease_application(
                pending.next_state,
                runtime_session=runtime,
                policy=policy,
                grant=pending.receipt,
                application=application,
                runtime_snapshot=runtime.snapshot,
            )


def test_native_request_entry_rejects_untrusted_callback_before_invocation():
    policy, _, _, _, policy_receipt, runtime, _, _, progress, state = (
        _state_and_progress()
    )
    request = ContinuationRequest.from_state(
        state,
        progress=progress,
        requested_resources=policy.lease_schedule[0],
        requester=PrincipalAuthority.OPENAI_SUPERVISOR,
        requester_authority=_authority(runtime),
    )
    request_seal = request._native_request_authority()
    native = object.__getattribute__(runtime, "_RustRuntimeSession__native")
    callback_invoked = False

    class MutatingRequest:
        def _canonical_text(self):
            nonlocal callback_invoked
            callback_invoked = True
            return request._canonical_text()

    with pytest.raises(ValueError, match="exact trusted type"):
        request_seal.evaluate(
            native,
            state,
            MutatingRequest(),
            runtime,
            policy,
            policy_receipt,
            progress,
        )
    assert callback_invoked is False


def test_native_lineage_retires_prior_state_after_each_recorded_decision():
    policy, _, _, _, policy_receipt, runtime, _, _, progress, state = (
        _state_and_progress(progressing=False)
    )

    def request_for(current_state):
        return ContinuationRequest.from_state(
            current_state,
            progress=progress,
            requested_resources=policy.lease_schedule[0],
            requester=PrincipalAuthority.OPENAI_SUPERVISOR,
            requester_authority=_authority(runtime),
        )

    first_request = request_for(state)
    stale_parallel_request = request_for(state)
    first = evaluate_continuation(
        state,
        first_request,
        runtime_session=runtime,
        policy=policy,
        policy_receipt=policy_receipt,
        progress=progress,
    )
    assert first.receipt.denial_reason is LeaseDenialReason.NO_MEASURABLE_PROGRESS
    assert first.next_state.lease_requests == 1

    with pytest.raises(ValueError, match="lineage does not match state|superseded"):
        evaluate_continuation(
            state,
            stale_parallel_request,
            runtime_session=runtime,
            policy=policy,
            policy_receipt=policy_receipt,
            progress=progress,
        )

    second = evaluate_continuation(
        first.next_state,
        request_for(first.next_state),
        runtime_session=runtime,
        policy=policy,
        policy_receipt=policy_receipt,
        progress=progress,
    )
    assert second.next_state.lease_requests == 2


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

    policy, _, _, _, policy_receipt, governed_runtime, _, _, progress, state = (
        _state_and_progress()
    )
    _, decision = _request_and_decide(
        policy, policy_receipt, governed_runtime, progress, state
    )
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
    policy, _, _, _, policy_receipt, runtime, _, _, progress, state = (
        _state_and_progress()
    )
    valid = ContinuationRequest.from_state(
        state,
        progress=progress,
        requested_resources=policy.lease_schedule[0],
        requester=PrincipalAuthority.OPENAI_SUPERVISOR,
    )
    stale_governance = replace(valid, governance_id=_id("foreign-governance"))
    with pytest.raises(ValueError, match="not bound to supervisor authority"):
        stale_governance._with_request_authority(_authority(runtime))

    stale_progress = replace(
        valid, progress_id=_id("stale-progress")
    )._with_request_authority(_authority(runtime))
    denied = evaluate_continuation(
        state,
        stale_progress,
        runtime_session=runtime,
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
    skipped_request = replace(request, lease_index=2)._with_request_authority(
        _authority(runtime)
    )
    denied = evaluate_continuation(
        state,
        skipped_request,
        runtime_session=runtime,
        policy=policy,
        policy_receipt=policy_receipt,
        progress=progress,
    )
    assert denied.receipt.denial_reason is LeaseDenialReason.LEASE_INDEX_MISMATCH

    request = ContinuationRequest.from_state(
        denied.next_state,
        progress=progress,
        requested_resources=policy.lease_schedule[0],
        requester=PrincipalAuthority.OPENAI_SUPERVISOR,
        requester_authority=_authority(runtime),
    )
    valid = evaluate_continuation(
        denied.next_state,
        request,
        runtime_session=runtime,
        policy=policy,
        policy_receipt=policy_receipt,
        progress=progress,
    )
    assert isinstance(valid.receipt, LeaseGrantReceipt)
    with pytest.raises(ValueError, match="native lease grant seal does not match"):
        replace(valid.receipt, lease_index=2)
    unissued_grant = _structural_grant(
        valid.receipt,
        lease_index=2,
    )
    application = runtime.apply_lease_transition(unissued_grant)
    assert application.receipt.status == "rejected"
    assert (
        application.receipt.rejection_reason
        == "IBAE-RT-LEASE-REJECT-LEASE-INDEX"
    )
    assert runtime.snapshot.continuation.leases_applied == 0


def test_hash_consistent_but_unissued_grant_cannot_extend_native_limits(
    monkeypatch,
):
    policy, _, _, _, policy_receipt, runtime, _, _, progress, state = (
        _state_and_progress()
    )
    _, decision = _request_and_decide(
        policy, policy_receipt, runtime, progress, state
    )
    assert isinstance(decision.receipt, LeaseGrantReceipt)
    structural_exact = _structural_grant(decision.receipt)
    assert structural_exact.canonical_record() == decision.receipt.canonical_record()
    assert not structural_exact.governance_bound
    fabricated = _structural_grant(
        decision.receipt,
        continuation_request_id=_id("fabricated-request"),
        progress_id=_id("fabricated-progress"),
    )
    assert fabricated.receipt_id != decision.receipt.receipt_id
    assert not fabricated.source_bound
    before = runtime.snapshot.canonical_record()
    rejected = runtime.apply_lease_transition(fabricated)
    assert rejected.receipt.status == "rejected"
    assert (
        rejected.receipt.rejection_reason
        == "IBAE-RT-LEASE-REJECT-UNISSUED-GRANT"
    )
    assert runtime.snapshot.canonical_record() == before

    native = object.__getattribute__(runtime, "_RustRuntimeSession__native")
    assert not hasattr(runtime, "_native_continuation_session")
    assert not hasattr(native, "issue_lease_grant")
    import ibae.continuation as continuation_module

    monkeypatch.setattr(
        continuation_module,
        "_validate_governance_capability",
        lambda *_: True,
        raising=False,
    )
    assert not hasattr(native, "issue_lease_grant")

    duplicate, duplicate_authority = RustRuntimeSession.create_continuation(
        "state-tiny-True",
        continuation_policy=policy,
        continuation_policy_receipt=policy_receipt,
    )
    duplicate_request = ContinuationRequest.from_state(
        decision.next_state,
        progress=progress,
        requested_resources=policy.lease_schedule[0],
        requester=PrincipalAuthority.OPENAI_SUPERVISOR,
        requester_authority=duplicate_authority,
    )
    with pytest.raises(ValueError, match="does not bind native session"):
        evaluate_continuation(
            decision.next_state,
            duplicate_request,
            runtime_session=duplicate,
            policy=policy,
            policy_receipt=policy_receipt,
            progress=progress,
        )

    from ibae._runtime import (
        NativeContinuationRequestSeal,
        NativeContinuationStateSeal,
        NativeContinuationSupervisorAuthority,
        NativeLeaseGrantSeal,
    )

    with pytest.raises(TypeError):
        NativeLeaseGrantSeal()
    with pytest.raises(TypeError):
        NativeContinuationSupervisorAuthority()
    with pytest.raises(TypeError):
        NativeContinuationRequestSeal()
    with pytest.raises(TypeError):
        NativeContinuationStateSeal()


def test_stale_grant_and_duplicate_application_are_state_neutral():
    policy, _, _, _, policy_receipt, runtime, _, _, progress, state = (
        _state_and_progress()
    )
    _, decision = _request_and_decide(
        policy, policy_receipt, runtime, progress, state
    )
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
    _, decision = _request_and_decide(
        policy, policy_receipt, runtime, progress, state
    )
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
    _, decision = _request_and_decide(
        policy, policy_receipt, runtime, progress, state
    )
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
        runtime_session=runtime,
        policy=policy,
        grant=grant,
        application=application,
        runtime_snapshot=after,
    )
    assert not committed.has_pending_grant
    assert committed.runtime_state_id == after.state_id


def test_application_commit_requires_the_exact_live_native_session():
    left = _state_and_progress()
    right = _state_and_progress()
    (
        left_policy,
        _,
        _,
        _,
        left_receipt,
        left_runtime,
        _,
        _,
        left_progress,
        left_state,
    ) = left
    (
        right_policy,
        _,
        _,
        _,
        right_receipt,
        right_runtime,
        _,
        _,
        right_progress,
        right_state,
    ) = right
    _, left_decision = _request_and_decide(
        left_policy,
        left_receipt,
        left_runtime,
        left_progress,
        left_state,
    )
    _, right_decision = _request_and_decide(
        right_policy,
        right_receipt,
        right_runtime,
        right_progress,
        right_state,
    )
    right_application = right_runtime.apply_lease(right_decision.receipt)
    structural_application = RuntimeLeaseApplicationReceipt(
        right_application.canonical_record()
    )
    structural_snapshot = RuntimeSnapshot.from_record(
        right_runtime.snapshot.canonical_record()
    )
    assert left_runtime.snapshot.session_id == structural_snapshot.session_id
    assert left_runtime.snapshot.state_id != structural_snapshot.state_id

    with pytest.raises(ValueError, match="not the live native session state"):
        commit_lease_application(
            left_decision.next_state,
            runtime_session=left_runtime,
            policy=left_policy,
            grant=left_decision.receipt,
            application=structural_application,
            runtime_snapshot=structural_snapshot,
        )
    with pytest.raises(ValueError, match="decision lineage"):
        replace(
            left_decision.next_state,
            runtime_state_id=structural_snapshot.state_id,
        )


def test_partial_lease_vectors_extend_resources_independently():
    policy, _, _, _, policy_receipt, runtime, _, _, progress, state = (
        _state_and_progress()
    )
    retry_only = BudgetVector(retry_delta=1)
    _, decision = _request_and_decide(
        policy,
        policy_receipt,
        runtime,
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
    policy, _, _, _, policy_receipt, runtime, _, _, progress, state = (
        _state_and_progress()
    )
    request = ContinuationRequest.from_state(
        state,
        progress=progress,
        requested_resources=BudgetVector(mutation_delta=1),
        requester=PrincipalAuthority.OPENAI_SUPERVISOR,
        requester_authority=_authority(runtime),
    )
    denied = evaluate_continuation(
        state,
        request,
        runtime_session=runtime,
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


def test_strategy_change_receipt_claims_are_revalidated_from_bound_material():
    _, _, task, governance, _, _, *_ = _state_and_progress()
    state, prior, alternate = _strategy_state()
    admitted = evaluate_strategy_change(
        task_id=task.task_id,
        governance_id=governance.governance_id,
        orchestration_state=state,
        prior_strategy=prior,
        proposed_strategy=alternate,
    )
    assert admitted.status is StrategyChangeStatus.ADMITTED
    with pytest.raises(ValueError, match="do not match bound material"):
        replace(
            admitted,
            proposed_strategy_material_id=_id("fabricated-strategy-material"),
        )
    with pytest.raises(ValueError, match="do not match bound material"):
        replace(
            admitted,
            reason=StrategyChangeReason.NOT_MATERIAL,
            status=StrategyChangeStatus.REJECTED,
        )


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


def test_recovery_strategy_requires_a_bound_obligation_target():
    _, prior, alternate = _strategy_state()
    with pytest.raises(ValueError, match="at least one target obligation"):
        StrategyMaterialization(
            alternate.strategy,
            capability_frontier=alternate.capability_frontier,
            target_obligation_ids=(),
            dependency_path=prior.dependency_path,
            recovery_mode="alternate",
        )


def test_material_strategy_change_is_alternative_justification_not_progress():
    policy, _, task, governance, policy_receipt, runtime = _governed_runtime(
        "standard", session="strategy-recovery"
    )
    orchestration, prior_strategy, alternate = _strategy_state()
    no_progress = _progress(task, governance, orchestration, orchestration)
    state = ContinuationState.create(
        policy=policy,
        policy_receipt=policy_receipt,
        runtime_session=runtime,
        orchestration_state=orchestration,
        runtime_snapshot=runtime.snapshot,
        strategy=prior_strategy,
        progress=no_progress,
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
        runtime,
        no_progress,
        state,
        strategy_change=change,
    )
    assert decision.granted
    assert decision.next_state.progress_state is ProgressState.STRATEGY_CHANGED
    assert decision.next_state.strategy_recoveries == 1


def test_native_initial_state_seal_rejects_strategy_lineage_injection():
    policy, _, task, governance, policy_receipt, runtime = _governed_runtime(
        "standard", session="stale-strategy-lineage"
    )
    orchestration, prior_strategy, _ = _strategy_state()
    no_progress = _progress(task, governance, orchestration, orchestration)
    state = ContinuationState.create(
        policy=policy,
        policy_receipt=policy_receipt,
        runtime_session=runtime,
        orchestration_state=orchestration,
        runtime_snapshot=runtime.snapshot,
        strategy=prior_strategy,
        progress=no_progress,
    )
    assert state.lease_requests == 0
    with pytest.raises(ValueError, match="decision lineage does not match"):
        replace(
            state, current_strategy_material_id=_id("newer-strategy-material")
        )
    unsealed_injection = replace(
        state,
        _decision_lineage_capability=None,
        current_strategy_material_id=_id("newer-strategy-material"),
    )
    with pytest.raises(ValueError, match="lacks evaluated decision lineage"):
        ContinuationRequest.from_state(
            unsealed_injection,
            progress=no_progress,
            requested_resources=policy.lease_schedule[0],
            requester=PrincipalAuthority.OPENAI_SUPERVISOR,
            requester_authority=_authority(runtime),
        )


def test_native_initial_state_seal_derives_the_exact_decision_seed():
    import ibae.continuation as continuation_module

    policy, _, task, governance, policy_receipt, runtime = _governed_runtime(
        "tiny", session="initial-decision-seed"
    )
    prior = _obligation_states(total=2, satisfied=0)
    current = _obligation_states(total=2, satisfied=1)
    progress = _progress(task, governance, prior, current)
    snapshot = runtime.snapshot
    forged = ContinuationState(
        task_id=task.task_id,
        governance_id=governance.governance_id,
        governance_receipt_id=policy_receipt.governance_receipt_id,
        continuation_policy_id=policy.continuation_policy_id,
        continuation_policy_receipt_id=policy_receipt.receipt_id,
        progress_contract_id=policy.progress_contract_id,
        orchestration_state_id=current.state_id,
        runtime_session_id=snapshot.session_id,
        runtime_state_id=snapshot.state_id,
        lease_requests=0,
        leases_granted=0,
        leases_denied=0,
        cumulative_granted=BudgetVector.zero(),
        continuation_logical_tick=0,
        decision_aggregate_id=_id("caller-selected-decision-seed"),
        decision_receipt_ids=(),
        strategy_recoveries=0,
        current_strategy_material_id=None,
        last_progress_id=progress.progress_id,
        progress_event_count=1,
        progress_aggregate_id=continuation_module._progress_aggregate((progress,)),
        last_consumed_progress_id=None,
        last_external_progress_endpoint_id=progress.current_external_endpoint_id,
        last_consumed_external_progress_endpoint_id=None,
        last_progress_classification=progress.classification,
        last_decision="none",
        last_denial_reason=None,
        progress_state=ProgressState.PROGRESSING,
    )
    native = object.__getattribute__(runtime, "_RustRuntimeSession__native")
    with pytest.raises(ValueError, match="decision aggregate is invalid"):
        native.seal_initial_continuation_state(
            forged,
            current,
            progress,
            None,
        )

    forged_progress_aggregate = replace(
        forged,
        decision_aggregate_id=continuation_module._initial_decision_aggregate(
            task_id=task.task_id,
            governance_id=governance.governance_id,
            continuation_policy_id=policy.continuation_policy_id,
        ),
        progress_aggregate_id=_id("caller-selected-progress-aggregate"),
    )
    with pytest.raises(ValueError, match="initial continuation progress lineage"):
        native.seal_initial_continuation_state(
            forged_progress_aggregate,
            current,
            progress,
            None,
        )

    legitimate = ContinuationState.create(
        policy=policy,
        policy_receipt=policy_receipt,
        runtime_session=runtime,
        orchestration_state=current,
        runtime_snapshot=snapshot,
        progress=progress,
    )
    assert legitimate.decision_aggregate_id != forged.decision_aggregate_id


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
        runtime_session=runtime,
        orchestration_state=orchestration,
        runtime_snapshot=runtime.snapshot,
        progress=progress,
    )
    _, decision = _request_and_decide(
        policy,
        policy_receipt,
        runtime,
        progress,
        state,
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
        runtime_session=runtime,
        orchestration_state=orchestration,
        runtime_snapshot=runtime.snapshot,
        strategy=prior_strategy,
        progress=no_progress,
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
        runtime,
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
        runtime,
        no_progress,
        denied.next_state,
        strategy_change=admitted_change,
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
        runtime_session=runtime,
        orchestration_state=orchestration,
        runtime_snapshot=runtime.snapshot,
        strategy=prior_strategy,
        progress=progress,
    )
    first_change = evaluate_strategy_change(
        task_id=task.task_id,
        governance_id=governance.governance_id,
        orchestration_state=orchestration,
        prior_strategy=prior_strategy,
        proposed_strategy=alternate,
    )
    _, first = _request_and_decide(
        policy,
        policy_receipt,
        runtime,
        progress,
        state,
        strategy_change=first_change,
    )
    application = runtime.apply_lease(first.receipt)
    state = commit_lease_application(
        first.next_state,
        runtime_session=runtime,
        policy=policy,
        grant=first.receipt,
        application=application,
        runtime_snapshot=runtime.snapshot,
    )
    assert state.strategy_recoveries == policy.max_strategy_recoveries

    from ibae._runtime import NativeContinuationStateSeal

    with pytest.raises(TypeError):
        NativeContinuationStateSeal()
    assert evaluate_continuation.__closure__ is None
    with pytest.raises(ValueError, match="decision lineage does not match"):
        replace(state, strategy_recoveries=0)
    reconstructed = replace(
        state,
        strategy_recoveries=0,
        _decision_lineage_capability=None,
    )
    second_change = evaluate_strategy_change(
        task_id=task.task_id,
        governance_id=governance.governance_id,
        orchestration_state=orchestration,
        prior_strategy=alternate,
        proposed_strategy=prior_strategy,
    )
    request = ContinuationRequest.from_state(
        state,
        progress=progress,
        requested_resources=policy.lease_schedule[state.leases_granted],
        requester=PrincipalAuthority.OPENAI_SUPERVISOR,
        requester_authority=_authority(runtime),
        strategy_change=second_change,
    )
    with pytest.raises(ValueError, match="lacks evaluated decision lineage"):
        evaluate_continuation(
            reconstructed,
            request,
            runtime_session=runtime,
            policy=policy,
            policy_receipt=policy_receipt,
            progress=progress,
            strategy_change=second_change,
        )
    decision = evaluate_continuation(
        state,
        request,
        runtime_session=runtime,
        policy=policy,
        policy_receipt=policy_receipt,
        progress=progress,
        strategy_change=second_change,
    )
    assert (
        decision.receipt.denial_reason
        is LeaseDenialReason.STRATEGY_RECOVERY_EXHAUSTED
    )


def test_decision_lineage_binds_semantic_decision_state():
    policy, _, _, _, policy_receipt, runtime, _, current, progress, state = (
        _state_and_progress("standard")
    )
    with pytest.raises(ValueError, match="last decision must match"):
        replace(
            state,
            last_decision="denied",
            last_denial_reason=LeaseDenialReason.NO_MEASURABLE_PROGRESS,
            last_progress_classification=ProgressClassification.NO_PROGRESS,
            progress_state=ProgressState.STALLED,
        )
    _, granted = _request_and_decide(
        policy, policy_receipt, runtime, progress, state
    )
    application = runtime.apply_lease(granted.receipt)
    state = commit_lease_application(
        granted.next_state,
        runtime_session=runtime,
        policy=policy,
        grant=granted.receipt,
        application=application,
        runtime_snapshot=runtime.snapshot,
    )
    with pytest.raises(ValueError, match="decision lineage does not match"):
        replace(
            state,
            last_progress_classification=ProgressClassification.NO_PROGRESS,
            progress_state=ProgressState.STALLED,
        )
    reconstructed = replace(
        state,
        _decision_lineage_capability=None,
        last_progress_classification=ProgressClassification.NO_PROGRESS,
        progress_state=ProgressState.STALLED,
    )
    with pytest.raises(ValueError, match="lacks evaluated decision lineage"):
        ContinuationCheckpoint(
            state=reconstructed,
            policy=policy,
            orchestration_state=current,
            runtime_snapshot=runtime.snapshot,
            progress=progress,
            partial_reason=ContinuationPartialReason.NO_PROGRESS,
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
        runtime_session=runtime,
        orchestration_state=complete,
        runtime_snapshot=runtime.snapshot,
        progress=progress,
    )
    _, decision = _request_and_decide(
        policy, policy_receipt, runtime, progress, state
    )
    assert decision.receipt.denial_reason is LeaseDenialReason.TASK_ALREADY_COMPLETE
    assert decision.next_state.progress_state is ProgressState.COMPLETE


def test_pending_grant_blocks_another_request_until_rust_applies_it():
    policy, _, _, _, policy_receipt, runtime, _, _, progress, state = (
        _state_and_progress("standard")
    )
    _, first = _request_and_decide(
        policy, policy_receipt, runtime, progress, state
    )
    assert first.next_state.has_pending_grant
    second_request = ContinuationRequest.from_state(
        first.next_state,
        progress=progress,
        requested_resources=policy.lease_schedule[1],
        requester=PrincipalAuthority.OPENAI_SUPERVISOR,
        requester_authority=_authority(runtime),
    )
    second = evaluate_continuation(
        first.next_state,
        second_request,
        runtime_session=runtime,
        policy=policy,
        policy_receipt=policy_receipt,
        progress=progress,
    )
    assert (
        second.receipt.denial_reason
        is LeaseDenialReason.PENDING_LEASE_APPLICATION
    )


def test_earlier_denial_cannot_install_an_unobserved_progress_endpoint():
    (
        policy,
        _,
        task,
        governance,
        policy_receipt,
        runtime,
        prior,
        current,
        progress,
        state,
    ) = _state_and_progress("standard")
    _, first = _request_and_decide(
        policy, policy_receipt, runtime, progress, state
    )
    assert first.next_state.has_pending_grant

    unrelated_prior = prior.advance(
        logical_tick=1,
        event_ids=(_id("unrelated-progress-lineage"),),
    )
    unrelated = _progress(task, governance, unrelated_prior, current)
    assert unrelated.classification is ProgressClassification.MEASURABLE_PROGRESS
    assert unrelated.progress_id != progress.progress_id

    request = ContinuationRequest.from_state(
        first.next_state,
        progress=progress,
        requested_resources=policy.lease_schedule[1],
        requester=PrincipalAuthority.OPENAI_SUPERVISOR,
    )
    request = replace(
        request, progress_id=unrelated.progress_id
    )._with_request_authority(_authority(runtime))
    denied = evaluate_continuation(
        first.next_state,
        request,
        runtime_session=runtime,
        policy=policy,
        policy_receipt=policy_receipt,
        progress=unrelated,
    )
    assert (
        denied.receipt.denial_reason
        is LeaseDenialReason.PENDING_LEASE_APPLICATION
    )
    assert denied.next_state.last_progress_id == progress.progress_id
    assert (
        denied.next_state.last_progress_classification
        is progress.classification
    )

    application = runtime.apply_lease(first.receipt)
    committed = commit_lease_application(
        denied.next_state,
        runtime_session=runtime,
        policy=policy,
        grant=first.receipt,
        application=application,
        runtime_snapshot=runtime.snapshot,
    )
    valid_shape = ContinuationRequest.from_state(
        committed,
        progress=progress,
        requested_resources=policy.lease_schedule[1],
        requester=PrincipalAuthority.OPENAI_SUPERVISOR,
    )
    forged = replace(
        valid_shape, progress_id=unrelated.progress_id
    )._with_request_authority(_authority(runtime))
    stale = evaluate_continuation(
        committed,
        forged,
        runtime_session=runtime,
        policy=policy,
        policy_receipt=policy_receipt,
        progress=unrelated,
    )
    assert stale.receipt.denial_reason is LeaseDenialReason.STALE_PROGRESS
    assert stale.next_state.last_progress_id == progress.progress_id


def test_one_measurable_progress_endpoint_authorizes_at_most_one_grant():
    (
        policy,
        _,
        task,
        governance,
        policy_receipt,
        runtime,
        _,
        current,
        progress,
        state,
    ) = _state_and_progress("standard")
    _, first = _request_and_decide(
        policy, policy_receipt, runtime, progress, state
    )
    application = runtime.apply_lease(first.receipt)
    state = commit_lease_application(
        first.next_state,
        runtime_session=runtime,
        policy=policy,
        grant=first.receipt,
        application=application,
        runtime_snapshot=runtime.snapshot,
    )
    assert state.last_consumed_progress_id == progress.progress_id

    _, reused = _request_and_decide(
        policy, policy_receipt, runtime, progress, state
    )
    assert reused.receipt.denial_reason is LeaseDenialReason.NO_MEASURABLE_PROGRESS

    later = _obligation_states(total=3, satisfied=2)
    fresh_progress = _progress(task, governance, current, later)
    state = observe_continuation_context(
        reused.next_state,
        runtime_session=runtime,
        policy=policy,
        orchestration_state=later,
        runtime_snapshot=runtime.snapshot,
        progress=fresh_progress,
    )
    _, fresh = _request_and_decide(
        policy, policy_receipt, runtime, fresh_progress, state
    )
    assert isinstance(fresh.receipt, LeaseGrantReceipt)
    assert fresh.next_state.last_consumed_progress_id == fresh_progress.progress_id


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
        runtime_session=runtime,
        orchestration_state=orchestration_states[1],
        runtime_snapshot=runtime.snapshot,
        progress=progress,
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
                runtime_session=runtime,
                policy=policy,
                orchestration_state=orchestration_states[index + 1],
                runtime_snapshot=runtime.snapshot,
                progress=progress,
            )
        _, decision = _request_and_decide(
            policy, policy_receipt, runtime, progress, state
        )
        assert isinstance(decision.receipt, LeaseGrantReceipt)
        application = runtime.apply_lease(decision.receipt)
        state = commit_lease_application(
            decision.next_state,
            runtime_session=runtime,
            policy=policy,
            grant=decision.receipt,
            application=application,
            runtime_snapshot=runtime.snapshot,
        )

    projection = state.compact_projection(policy)
    assert projection["lease_requests_remaining"] > 0
    assert projection["lease_schedule_slots_remaining"] == 0
    assert projection["leases_remaining"] == 0
    assert projection["legal_recovery_actions"] == []
    assert projection["material_strategy_change_admissible"] is False
    checkpoint = ContinuationCheckpoint(
        state=state,
        policy=policy,
        orchestration_state=orchestration_states[2],
        runtime_snapshot=runtime.snapshot,
        progress=progress,
    )
    assert checkpoint.leases_remaining == 0

    progress = _progress(
        task, governance, orchestration_states[2], orchestration_states[3]
    )
    state = observe_continuation_context(
        state,
        runtime_session=runtime,
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
        requester_authority=_authority(runtime),
    )
    exhausted = evaluate_continuation(
        state,
        request,
        runtime_session=runtime,
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
    policy, _, _, _, policy_receipt, runtime, _, _, progress, state = (
        _state_and_progress()
    )
    excessive = replace(
        policy.lease_schedule[0],
        request_delta=policy.lease_schedule[0].request_delta + 1,
    )
    _, denied = _request_and_decide(
        policy,
        policy_receipt,
        runtime,
        progress,
        state,
        requested_resources=excessive,
    )
    assert (
        denied.receipt.denial_reason
        is LeaseDenialReason.AMOUNT_EXCEEDS_SCHEDULE
    )

    with pytest.raises(ValueError, match="decision lineage does not match"):
        replace(
            state,
            cumulative_granted=BudgetVector(request_delta=MAX_U64),
        )


def test_denials_are_finitely_bounded_by_request_policy():
    policy, _, _, _, policy_receipt, runtime, _, current, progress, state = (
        _state_and_progress("tiny", progressing=False)
    )
    for _ in range(policy.max_lease_requests):
        _, decision = _request_and_decide(
            policy, policy_receipt, runtime, progress, state
        )
        state = decision.next_state
    assert state.lease_requests == policy.max_lease_requests
    assert state.leases_denied == policy.max_lease_requests
    projection = state.compact_projection(policy)
    assert projection["lease_requests_remaining"] == 0
    assert projection["lease_schedule_slots_remaining"] == 1
    assert projection["leases_remaining"] == 0
    assert projection["legal_recovery_actions"] == []
    assert projection["material_strategy_change_admissible"] is False
    checkpoint = ContinuationCheckpoint(
        state=state,
        policy=policy,
        orchestration_state=current,
        runtime_snapshot=runtime.snapshot,
        progress=progress,
    )
    assert checkpoint.leases_remaining == 0
    request = ContinuationRequest.from_state(
        state,
        progress=progress,
        requested_resources=policy.lease_schedule[0],
        requester=PrincipalAuthority.OPENAI_SUPERVISOR,
        requester_authority=_authority(runtime),
    )
    final = evaluate_continuation(
        state,
        request,
        runtime_session=runtime,
        policy=policy,
        policy_receipt=policy_receipt,
        progress=progress,
    )
    assert final.receipt.denial_reason is LeaseDenialReason.LEASE_REQUEST_LIMIT
    assert final.next_state is state


def test_watchdog_exhaustion_uses_effective_checkpoint_lease_capacity():
    policy, _, _, _, policy_receipt, runtime, _, current, progress, state = (
        _state_and_progress("tiny", progressing=False)
    )
    for _ in range(policy.max_lease_requests):
        _, decision = _request_and_decide(
            policy, policy_receipt, runtime, progress, state
        )
        state = decision.next_state
    assert state.progress_state is ProgressState.STALLED

    checkpoint = ContinuationCheckpoint(
        state=state,
        policy=policy,
        orchestration_state=current,
        runtime_snapshot=runtime.snapshot,
        progress=progress,
        partial_reason=ContinuationPartialReason.WATCHDOG_EXPIRED,
    )
    assert checkpoint.leases_remaining == 0
    observation = WatchdogObservation(
        state.task_id,
        state.governance_id,
        state.orchestration_state_id,
        state.runtime_state_id,
        state.continuation_state_id,
        60_000,
        lease_exhausted=True,
    )
    partial = ContinuationPartialReceipt(
        state=state,
        checkpoint=checkpoint,
        reason=ContinuationPartialReason.WATCHDOG_EXPIRED,
        watchdog_observation=observation,
    )
    assert partial.watchdog_observation_id == observation.observation_id
    with pytest.raises(ValueError, match="effective checkpoint capacity"):
        ContinuationPartialReceipt(
            state=state,
            checkpoint=checkpoint,
            reason=ContinuationPartialReason.WATCHDOG_EXPIRED,
            watchdog_observation=replace(observation, lease_exhausted=False),
        )


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


def test_checkpoint_status_must_equal_the_live_continuation_state():
    policy, _, _, _, _, runtime, _, current, progress, state = (
        _state_and_progress(progressing=False)
    )
    assert state.progress_state is ProgressState.STALLED
    with pytest.raises(ValueError, match="status does not match"):
        ContinuationCheckpoint(
            state=state,
            policy=policy,
            orchestration_state=current,
            runtime_snapshot=runtime.snapshot,
            progress=progress,
            checkpoint_status=ProgressState.COMPLETE,
        )


def test_checkpoint_rejects_strategy_absent_from_live_state():
    policy, _, _, _, _, runtime, _, current, progress, state = (
        _state_and_progress()
    )
    _, unrelated_strategy, _ = _strategy_state()
    assert state.current_strategy_material_id is None
    with pytest.raises(ValueError, match="checkpoint strategy identity is stale"):
        ContinuationCheckpoint(
            state=state,
            policy=policy,
            orchestration_state=current,
            runtime_snapshot=runtime.snapshot,
            progress=progress,
            strategy=unrelated_strategy,
        )


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


def test_checkpoint_progress_must_equal_the_live_ledger_endpoint():
    policy, _, task, governance, _, runtime, prior, current, progress, state = (
        _state_and_progress()
    )
    alternate_prior = _obligation_states(total=3, satisfied=2)
    unrelated = _progress(task, governance, alternate_prior, current)
    assert unrelated.progress_id != progress.progress_id
    with pytest.raises(ValueError, match="checkpoint progress identity is stale"):
        ContinuationCheckpoint(
            state=state,
            policy=policy,
            orchestration_state=current,
            runtime_snapshot=runtime.snapshot,
            progress=unrelated,
        )
    assert prior.state_id == progress.prior_orchestration_state_id


def test_context_rebind_requires_the_actual_prior_orchestration_state():
    policy, _, task, governance, _, runtime, _, _, _, state = (
        _state_and_progress()
    )
    unrelated_prior = _obligation_states(total=4, satisfied=0)
    next_state = _obligation_states(total=3, satisfied=2)
    fabricated = _progress(task, governance, unrelated_prior, next_state)
    with pytest.raises(ValueError, match="progress does not bind"):
        observe_continuation_context(
            state,
            runtime_session=runtime,
            policy=policy,
            orchestration_state=next_state,
            runtime_snapshot=runtime.snapshot,
            progress=fabricated,
        )


def test_context_observation_requires_the_exact_live_native_snapshot():
    policy, _, _, _, _, runtime, _, current, _, state = _state_and_progress()
    live = runtime.snapshot
    fabricated = replace(
        live,
        logical_tick=live.logical_tick + 1,
        state_id=_id("fabricated-runtime-snapshot"),
    )
    with pytest.raises(ValueError, match="not the live native session state"):
        observe_continuation_context(
            state,
            runtime_session=runtime,
            policy=policy,
            orchestration_state=current,
            runtime_snapshot=fabricated,
        )

    observed = observe_continuation_context(
        state,
        runtime_session=runtime,
        policy=policy,
        orchestration_state=current,
        runtime_snapshot=live,
    )
    assert observed.runtime_state_id == live.state_id


def test_context_rebind_does_not_advertise_recovery_without_prior_strategy():
    policy, _, task, governance, policy_receipt, runtime, _, current, progress, state = (
        _state_and_progress("standard")
    )
    assert state.progress_state is ProgressState.PROGRESSING
    _, granted = _request_and_decide(
        policy, policy_receipt, runtime, progress, state
    )
    application = runtime.apply_lease(granted.receipt)
    state = commit_lease_application(
        granted.next_state,
        runtime_session=runtime,
        policy=policy,
        grant=granted.receipt,
        application=application,
        runtime_snapshot=runtime.snapshot,
    )

    stalled_progress = _progress(task, governance, current, current)
    state = observe_continuation_context(
        state,
        runtime_session=runtime,
        policy=policy,
        orchestration_state=current,
        runtime_snapshot=runtime.snapshot,
        progress=stalled_progress,
    )
    assert state.progress_state is ProgressState.STALLED
    projection = state.compact_projection(policy)
    assert projection["legal_recovery_actions"] == ["provide_objective_progress"]
    assert projection["material_strategy_change_admissible"] is False

    complete = _obligation_states(total=3, satisfied=3)
    complete_progress = _progress(task, governance, current, complete)
    state = observe_continuation_context(
        state,
        runtime_session=runtime,
        policy=policy,
        orchestration_state=complete,
        runtime_snapshot=runtime.snapshot,
        progress=complete_progress,
    )
    assert state.progress_state is ProgressState.COMPLETE
    assert state.compact_projection(policy)["legal_recovery_actions"] == []


def test_compact_state_advertises_recovery_when_prior_strategy_exists():
    policy, _, task, governance, policy_receipt, runtime = _governed_runtime(
        "standard", session="compact-strategy-recovery"
    )
    orchestration, prior_strategy, _ = _strategy_state()
    stalled = _progress(task, governance, orchestration, orchestration)
    state = ContinuationState.create(
        policy=policy,
        policy_receipt=policy_receipt,
        runtime_session=runtime,
        orchestration_state=orchestration,
        runtime_snapshot=runtime.snapshot,
        strategy=prior_strategy,
        progress=stalled,
    )
    projection = state.compact_projection(policy)
    assert "propose_material_strategy_change" in projection[
        "legal_recovery_actions"
    ]
    assert projection["material_strategy_change_admissible"] is True


def test_request_requires_the_live_progress_ledger_endpoint():
    policy, _, task, governance, _, _, prior, current, _, state = (
        _state_and_progress()
    )
    unrelated_prior = _obligation_states(total=4, satisfied=0)
    unrelated = _progress(task, governance, unrelated_prior, current)
    assert unrelated.prior_orchestration_state_id != prior.state_id
    with pytest.raises(ValueError, match="live continuation ledger"):
        ContinuationRequest.from_state(
            state,
            progress=unrelated,
            requested_resources=policy.lease_schedule[0],
            requester=PrincipalAuthority.OPENAI_SUPERVISOR,
        )


def test_policy_rejects_progress_from_an_unapproved_contract():
    policy, _, task, governance, policy_receipt, runtime, prior, current, _, state = (
        _state_and_progress()
    )
    foreign_contract = ProgressMeasureContract(
        "foreign.obligation-progress",
        1,
        _progress_contract().dimensions,
    )
    foreign = evaluate_progress(
        task_id=task.task_id,
        governance_id=governance.governance_id,
        contract=foreign_contract,
        prior_state=prior,
        current_state=current,
    )
    state_progress = _progress(task, governance, prior, current)
    request = replace(
        ContinuationRequest.from_state(
            state,
            progress=state_progress,
            requested_resources=policy.lease_schedule[0],
            requester=PrincipalAuthority.OPENAI_SUPERVISOR,
        ),
        progress_id=foreign.progress_id,
    )._with_request_authority(_authority(runtime))
    denied = evaluate_continuation(
        state,
        request,
        runtime_session=runtime,
        policy=policy,
        policy_receipt=policy_receipt,
        progress=foreign,
    )
    assert state_progress.progress_id == state.last_progress_id
    assert denied.receipt.denial_reason is LeaseDenialReason.STALE_PROGRESS


def test_compact_continuation_evidence_uses_aggregates_not_verbose_traces():
    policy, _, _, _, policy_receipt, runtime, _, current, progress, state = (
        _state_and_progress()
    )
    _, decision = _request_and_decide(
        policy, policy_receipt, runtime, progress, state
    )
    application = runtime.apply_lease(decision.receipt)
    state = commit_lease_application(
        decision.next_state,
        runtime_session=runtime,
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


def test_continuation_evidence_requires_a_contiguous_live_progress_trace():
    policy, _, task, governance, _, runtime, _, current, first, state = (
        _state_and_progress("standard")
    )
    later = _obligation_states(total=3, satisfied=2)
    second = _progress(task, governance, current, later)
    state = observe_continuation_context(
        state,
        runtime_session=runtime,
        policy=policy,
        orchestration_state=later,
        runtime_snapshot=runtime.snapshot,
        progress=second,
    )
    valid = ContinuationEvidenceReceipt(
        state=state,
        policy=policy,
        progress_records=(first, second),
    )
    assert valid.final_progress_id == state.last_progress_id
    assert valid.progress_events == state.progress_event_count == 2
    assert valid.progress_aggregate_id == state.progress_aggregate_id
    with pytest.raises(ValueError, match="full live history"):
        ContinuationEvidenceReceipt(
            state=state,
            policy=policy,
            progress_records=(second,),
        )
    with pytest.raises(ValueError, match="endpoint"):
        ContinuationEvidenceReceipt(
            state=state,
            policy=policy,
            progress_records=(first,),
        )
    with pytest.raises(ValueError, match="endpoint|contiguous"):
        ContinuationEvidenceReceipt(
            state=state,
            policy=policy,
            progress_records=(second, first),
        )
    unrelated = _obligation_states(total=4, satisfied=1)
    disconnected = _progress(task, governance, unrelated, unrelated)
    with pytest.raises(ValueError, match="contiguous"):
        ContinuationEvidenceReceipt(
            state=state,
            policy=policy,
            progress_records=(first, disconnected, second),
        )


def test_ai_projection_exposes_exact_remaining_capacity_and_recovery_actions():
    policy, _, _, _, policy_receipt, runtime, _, _, progress, state = (
        _state_and_progress(progressing=False)
    )
    _, decision = _request_and_decide(
        policy, policy_receipt, runtime, progress, state
    )
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
    policy, runtime, current, progress, state = _partial_context(reason)
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


def _partial_context(reason):
    if reason is ContinuationPartialReason.NO_PROGRESS:
        policy, _, _, _, policy_receipt, runtime, _, current, progress, state = (
            _state_and_progress("standard", progressing=False)
        )
        _, denied = _request_and_decide(
            policy, policy_receipt, runtime, progress, state
        )
        return policy, runtime, current, progress, denied.next_state

    if reason is ContinuationPartialReason.TERMINAL_CYCLE:
        policy, _, task, governance, policy_receipt, runtime = _governed_runtime(
            "standard", session="partial-terminal-cycle"
        )
        for label in "abab":
            runtime.execute_read(
                "read", {"path": label}, "partial-cycle", lambda: label
            )
        cycle = CycleEvidence.from_snapshot(runtime.snapshot)
        assert cycle is not None
        current = _obligation_states(total=2)
        progress = _progress(task, governance, current, current)
        state = ContinuationState.create(
            policy=policy,
            policy_receipt=policy_receipt,
            runtime_session=runtime,
            orchestration_state=current,
            runtime_snapshot=runtime.snapshot,
            progress=progress,
        )
        _, denied = _request_and_decide(
            policy,
            policy_receipt,
            runtime,
            progress,
            state,
            cycle_evidence=cycle,
        )
        return policy, runtime, current, progress, denied.next_state

    if reason is ContinuationPartialReason.STRATEGY_RECOVERY_EXHAUSTED:
        policy, _, task, governance, policy_receipt, runtime = _governed_runtime(
            "standard", session="partial-strategy-exhausted"
        )
        current, primary, alternate = _strategy_state()
        progress = _progress(task, governance, current, current)
        state = ContinuationState.create(
            policy=policy,
            policy_receipt=policy_receipt,
            runtime_session=runtime,
            orchestration_state=current,
            runtime_snapshot=runtime.snapshot,
            strategy=primary,
            progress=progress,
        )
        first_change = evaluate_strategy_change(
            task_id=task.task_id,
            governance_id=governance.governance_id,
            orchestration_state=current,
            prior_strategy=primary,
            proposed_strategy=alternate,
        )
        _, first = _request_and_decide(
            policy,
            policy_receipt,
            runtime,
            progress,
            state,
            strategy_change=first_change,
        )
        application = runtime.apply_lease(first.receipt)
        state = commit_lease_application(
            first.next_state,
            runtime_session=runtime,
            policy=policy,
            grant=first.receipt,
            application=application,
            runtime_snapshot=runtime.snapshot,
        )
        second_change = evaluate_strategy_change(
            task_id=task.task_id,
            governance_id=governance.governance_id,
            orchestration_state=current,
            prior_strategy=alternate,
            proposed_strategy=primary,
        )
        _, denied = _request_and_decide(
            policy,
            policy_receipt,
            runtime,
            progress,
            state,
            strategy_change=second_change,
        )
        return policy, runtime, current, progress, denied.next_state

    policy, _, task, governance, policy_receipt, runtime = _governed_runtime(
        "standard", session="partial-lease-ceiling"
    )
    states = tuple(_obligation_states(total=4, satisfied=i) for i in range(4))
    progress = _progress(task, governance, states[0], states[1])
    state = ContinuationState.create(
        policy=policy,
        policy_receipt=policy_receipt,
        runtime_session=runtime,
        orchestration_state=states[1],
        runtime_snapshot=runtime.snapshot,
        progress=progress,
    )
    for index in range(policy.max_leases):
        if index:
            progress = _progress(task, governance, states[index], states[index + 1])
            state = observe_continuation_context(
                state,
                runtime_session=runtime,
                policy=policy,
                orchestration_state=states[index + 1],
                runtime_snapshot=runtime.snapshot,
                progress=progress,
            )
        _, granted = _request_and_decide(
            policy, policy_receipt, runtime, progress, state
        )
        application = runtime.apply_lease(granted.receipt)
        state = commit_lease_application(
            granted.next_state,
            runtime_session=runtime,
            policy=policy,
            grant=granted.receipt,
            application=application,
            runtime_snapshot=runtime.snapshot,
        )
    progress = _progress(task, governance, states[2], states[3])
    state = observe_continuation_context(
        state,
        runtime_session=runtime,
        policy=policy,
        orchestration_state=states[3],
        runtime_snapshot=runtime.snapshot,
        progress=progress,
    )
    request = ContinuationRequest.from_state(
        state,
        progress=progress,
        requested_resources=BudgetVector(request_delta=1),
        requester=PrincipalAuthority.OPENAI_SUPERVISOR,
        requester_authority=_authority(runtime),
    )
    denied = evaluate_continuation(
        state,
        request,
        runtime_session=runtime,
        policy=policy,
        policy_receipt=policy_receipt,
        progress=progress,
    )
    return policy, runtime, states[3], progress, denied.next_state


def test_partial_receipt_rejects_reason_mismatch():
    policy, runtime, current, progress, state = _partial_context(
        ContinuationPartialReason.NO_PROGRESS
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


@pytest.mark.parametrize(
    "reason",
    (
        ContinuationPartialReason.NO_PROGRESS,
        ContinuationPartialReason.STRATEGY_RECOVERY_EXHAUSTED,
    ),
)
def test_checkpoint_requires_the_actual_denial(reason):
    policy, _, _, _, _, runtime, _, current, progress, state = (
        _state_and_progress(progressing=False)
    )
    with pytest.raises(ValueError, match="actual lease denial"):
        ContinuationCheckpoint(
            state=state,
            policy=policy,
            orchestration_state=current,
            runtime_snapshot=runtime.snapshot,
            progress=progress,
            partial_reason=reason,
        )


def test_checkpoint_rejects_partial_reason_for_progressing_state():
    policy, _, _, _, _, runtime, _, current, progress, state = (
        _state_and_progress()
    )
    with pytest.raises(ValueError, match="continuation progress state"):
        ContinuationCheckpoint(
            state=state,
            policy=policy,
            orchestration_state=current,
            runtime_snapshot=runtime.snapshot,
            progress=progress,
            partial_reason=ContinuationPartialReason.NO_PROGRESS,
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
    exhausted = replace(observation, lease_exhausted=True)
    assert exhausted.observation_id != observation.observation_id


@pytest.mark.parametrize("field", ("orchestration_state_id", "runtime_state_id"))
def test_watchdog_observation_requires_the_exact_live_context(field):
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
    )
    checkpoint = ContinuationCheckpoint(
        state=state,
        policy=policy,
        orchestration_state=current,
        runtime_snapshot=runtime.snapshot,
        progress=progress,
        partial_reason=ContinuationPartialReason.WATCHDOG_EXPIRED,
    )
    stale = replace(observation, **{field: _id(f"stale-{field}")})
    with pytest.raises(ValueError, match="does not bind partial state"):
        ContinuationPartialReceipt(
            state=state,
            checkpoint=checkpoint,
            reason=ContinuationPartialReason.WATCHDOG_EXPIRED,
            watchdog_observation=stale,
        )


def test_partial_evidence_ids_are_derived_from_the_bound_checkpoint():
    policy, _, _, _, _, runtime, _, current, progress, state = (
        _state_and_progress()
    )
    compact_id = _id("checkpoint-compact-evidence")
    execution_id = _id("checkpoint-execution")
    checkpoint = ContinuationCheckpoint(
        state=state,
        policy=policy,
        orchestration_state=current,
        runtime_snapshot=runtime.snapshot,
        progress=progress,
        compact_evidence_receipt_id=compact_id,
        relevant_receipt_id=execution_id,
        partial_reason=ContinuationPartialReason.WATCHDOG_EXPIRED,
    )
    observation = WatchdogObservation(
        state.task_id,
        state.governance_id,
        state.orchestration_state_id,
        state.runtime_state_id,
        state.continuation_state_id,
        1,
    )
    partial = ContinuationPartialReceipt(
        state=state,
        checkpoint=checkpoint,
        reason=ContinuationPartialReason.WATCHDOG_EXPIRED,
        watchdog_observation=observation,
    )
    assert partial.compact_evidence_receipt_id == compact_id
    assert partial.execution_receipt_id == execution_id
    with pytest.raises(ValueError, match="does not match checkpoint"):
        ContinuationPartialReceipt(
            state=state,
            checkpoint=checkpoint,
            reason=ContinuationPartialReason.WATCHDOG_EXPIRED,
            compact_evidence_receipt_id=_id("unrelated-compact-evidence"),
            watchdog_observation=observation,
        )
    with pytest.raises(ValueError, match="does not match checkpoint"):
        ContinuationPartialReceipt(
            state=state,
            checkpoint=checkpoint,
            reason=ContinuationPartialReason.WATCHDOG_EXPIRED,
            execution_receipt_id=_id("unrelated-execution"),
            watchdog_observation=observation,
        )


def test_checkpoint_and_partial_records_are_byte_deterministic():
    policy, runtime, current, progress, state = _partial_context(
        ContinuationPartialReason.NO_PROGRESS
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
    with pytest.raises(ValueError, match="create_continuation"):
        RustRuntimeSession(
            "direct-continuation",
            continuation_policy=policy,
            continuation_policy_receipt=policy_receipt,
        )


def test_records_are_immutable_and_domain_separated():
    policy, _, _, _, policy_receipt, runtime, _, _, progress, state = (
        _state_and_progress()
    )
    request, decision = _request_and_decide(
        policy, policy_receipt, runtime, progress, state
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
        base_deficit = BudgetVector.from_record(result["base_budget_deficit"])
        if not base_deficit.is_zero:
            assert result["task_outcome"] == "denied"
            assert result["denial_reason"] == "base_budget_exhausted"
            assert result["lease_count"] == 0
            continue
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
