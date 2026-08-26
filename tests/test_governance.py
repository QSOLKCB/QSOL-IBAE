from __future__ import annotations

from collections.abc import Mapping
from dataclasses import FrozenInstanceError, replace

import pytest

from ibae.canonical import canonical_fingerprint, domain_fingerprint
from ibae.evidence import (
    CompactEvidenceReceipt,
    EvidenceAccumulator,
    authorization_manifest_identity,
)
from ibae.governance import (
    BENCHMARK_ID_DOMAIN,
    COMPACT_EVIDENCE_GATE_KEY,
    EXECUTION_ID_DOMAIN,
    EXECUTION_PLAN_ID_DOMAIN,
    EXECUTION_RECEIPT_GATE_KEY,
    FINAL_ACCEPTANCE_ID_DOMAIN,
    GOVERNANCE_ID_DOMAIN,
    GOVERNANCE_PROTOCOL_VERSION,
    MAX_REQUIRED_GATES,
    MAX_TOOL_PERMISSIONS,
    ORCHESTRATION_ID_DOMAIN,
    ORCHESTRATION_RECEIPT_GATE_KEY,
    SUPPORTED_REQUIRED_GATE_KEYS,
    TASK_ID_DOMAIN,
    AcceptanceGateResult,
    BenchmarkReceipt,
    ExecutionPlanReceipt,
    ExecutionReceipt,
    GovernancePolicy,
    GovernanceReceipt,
    GovernanceRejected,
    GovernanceRejectionReason,
    GovernanceWrapper,
    PartialReceipt,
    PrincipalAuthority,
    ProviderAuthority,
    ReceiptStage,
    ReceiptValidator,
    RejectionReceipt,
    TaskReceipt,
    ToolAuthorityClass,
    ToolPermission,
)
from ibae.orchestration import (
    ACTION_ID_DOMAIN,
    ActionProposal,
    AdmissionDecision,
    AdmissionReceipt,
    AuthorityLayer,
    BatchStatus,
    Capability,
    DecisionStatus,
    ProposalOrdering,
    ReplaySafety,
)
from ibae.runtime import (
    RUNTIME_PROTOCOL_VERSION,
    RUNTIME_RECEIPT_DOMAIN,
    RuntimeReceipt,
    RustRuntimeSession,
)


def _id(label: str) -> str:
    return canonical_fingerprint({"label": label})


def _oversized_records(value, limit: int):
    for _ in range(limit + 1):
        yield value


class _HostileOversizedMapping(Mapping):
    """Mapping whose ``items`` path is unusable and key stream never ends."""

    def __init__(self, values):
        self._values = dict(values)

    def __getitem__(self, key):
        if key in self._values:
            return self._values[key]
        return True

    def __iter__(self):
        yield from self._values
        index = 0
        while True:
            yield f"hostile_extra_{index}"
            index += 1

    def __len__(self):
        return len(self._values) + 1

    def items(self):
        raise AssertionError("fixed-schema parsers must not trust Mapping.items()")


def _permission(
    name: str,
    authority_class: ToolAuthorityClass,
    *,
    mutation: bool = False,
    cache: bool = False,
) -> ToolPermission:
    return ToolPermission(name, authority_class, mutation, cache)


def _tool_bundle(
    tool_name: str,
    authority_class: ToolAuthorityClass,
    arguments,
    *,
    label: str,
    occurrence_key: str | None = None,
    dependency_state_id: str | None = None,
):
    replay_safety = (
        ReplaySafety.CACHEABLE_READ
        if authority_class
        in {ToolAuthorityClass.PURE_READ, ToolAuthorityClass.SNAPSHOT_READ}
        else ReplaySafety.OCCURRENCE_SENSITIVE
    )
    required_state_keys = (
        ("snapshot",)
        if authority_class is ToolAuthorityClass.SNAPSHOT_READ
        else ()
    )
    capability = Capability(
        tool_name,
        replay_safety,
        f"Governed {tool_name} capability.",
        required_state_keys=required_state_keys,
        semantic_argument_keys=tuple(sorted(arguments)) if isinstance(arguments, dict) else (),
    )
    proposal = ActionProposal(
        f"proposal.{label}",
        tool_name,
        arguments,
        target_obligation_ids=(_id(f"obligation-{label}"),),
        required_state_keys=required_state_keys,
        occurrence_key=occurrence_key,
    )
    active_dependency = (
        _id(f"dependency-{label}")
        if dependency_state_id is None
        else dependency_state_id
    )
    action_record = {
        "arguments": capability.normalize_arguments(proposal.arguments),
        "capability_id": capability.capability_id,
        "dependency_state_id": active_dependency,
    }
    if replay_safety is ReplaySafety.OCCURRENCE_SENSITIVE:
        action_record["occurrence_key"] = occurrence_key
    decision = AdmissionDecision(
        proposal_id=proposal.proposal_id,
        proposal_key=proposal.proposal_key,
        status=DecisionStatus.ADMITTED,
        logical_tick=1,
        action_id=domain_fingerprint(ACTION_ID_DOMAIN, action_record),
        dependency_state_keys=required_state_keys,
    )
    return decision, proposal, capability, active_dependency


def _policy(version: int = 1) -> GovernancePolicy:
    return GovernancePolicy(
        policy_key="research.default",
        policy_version=version,
        task_profile="tiny",
        task_profile_version=1,
        provider_authority=ProviderAuthority.OPENAI,
        tool_permissions=(
            _permission("mutate.denied", ToolAuthorityClass.IDEMPOTENT_MUTATION),
            _permission(
                "mutate.idempotent",
                ToolAuthorityClass.IDEMPOTENT_MUTATION,
                mutation=True,
            ),
            _permission(
                "mutate.non_idempotent",
                ToolAuthorityClass.NON_IDEMPOTENT_MUTATION,
                mutation=True,
            ),
            _permission(
                "read.pure", ToolAuthorityClass.PURE_READ, cache=True
            ),
            _permission(
                "read.snapshot", ToolAuthorityClass.SNAPSHOT_READ, cache=True
            ),
            _permission("read.volatile", ToolAuthorityClass.VOLATILE_READ),
        ),
        required_gate_keys=(
            COMPACT_EVIDENCE_GATE_KEY,
            ORCHESTRATION_RECEIPT_GATE_KEY,
            EXECUTION_RECEIPT_GATE_KEY,
        ),
    )


def _admission_receipt(
    *,
    action_id: str | None = None,
    decision: AdmissionDecision | None = None,
    status: BatchStatus = BatchStatus.PROCESSED,
    ordering: ProposalOrdering = ProposalOrdering.CANONICAL_INDEPENDENT,
) -> AdmissionReceipt:
    if status is not BatchStatus.PROCESSED:
        raise AssertionError("tests construct rejected batches separately")
    if decision is None:
        active_action_id = _id("runtime-admission") if action_id is None else action_id
        active_decision = AdmissionDecision(
            proposal_id=_id("proposal"),
            proposal_key="proposal.read",
            status=DecisionStatus.ADMITTED,
            logical_tick=1,
            action_id=active_action_id,
        )
    else:
        active_decision = decision
    return AdmissionReceipt(
        batch_id=_id("batch"),
        strategy_id=_id("strategy"),
        prior_state_id=_id("orchestration-prior"),
        next_state_id=_id("orchestration-next"),
        status=BatchStatus.PROCESSED,
        proposal_ordering=ordering,
        logical_tick_start=0,
        logical_tick_end=1,
        decisions=(active_decision,),
    )


def _runtime_receipt(
    *,
    accepted: bool = True,
    admission_id: str | None = None,
    admission_label: str = "runtime-admission",
    arguments_id: str | None = None,
    arguments_label: str = "arguments",
    transition_label: str = "transition",
    command_label: str = "command",
    session_label: str = "runtime-session",
    prior_state_label: str = "runtime-prior",
    resulting_state_label: str = "runtime-next",
    dependency_fingerprint: str | None = None,
    tool_name: str = "read.pure",
    logical_tick: int | None = None,
) -> RuntimeReceipt:
    active_tick = (3 if accepted else 2) if logical_tick is None else logical_tick
    body = {
        "admission_id": (
            _id(admission_label) if admission_id is None else admission_id
        ),
        "arguments_id": (
            _id(arguments_label) if arguments_id is None else arguments_id
        ),
        "authority_layer": "execution",
        "budget_delta": {
            "cache_hits": 0,
            "executions": 1,
            "requests": 1,
            "retries": 0,
        },
        "cache_status": "cold_execution" if accepted else None,
        "command_id": _id(command_label),
        "command_type": "execute_read",
        "dependency_fingerprint": (
            _id("dependency")
            if dependency_fingerprint is None
            else dependency_fingerprint
        ),
        "logical_tick": active_tick,
        "logical_tick_delta": 3 if accepted else 2,
        "observation_id": _id("observation") if accepted else None,
        "prior_state_id": _id(prior_state_label),
        "protocol_version": RUNTIME_PROTOCOL_VERSION,
        "rejection": (
            None
            if accepted
            else {
                "authority_layer": "execution",
                "blocking_runtime_state": {
                    "counters": {
                        "cache_hits": 0,
                        "executions": 1,
                        "requests": 1,
                        "retries": 0,
                    },
                    "limits": {
                        "max_executions": 16,
                        "max_history": 32,
                        "max_requests": 32,
                        "max_retries": 4,
                    },
                    "logical_tick": 2,
                    "state_id": _id(resulting_state_label),
                },
                "invariant_ids": ["IBAE-REUSE-004", "IBAE-RT-005"],
                "reason_code": "IBAE-RT-REJECT-INVALID-OBSERVATION",
            }
        ),
        "resulting_state_id": _id(resulting_state_label),
        "session_id": _id(session_label),
        "status": "accepted" if accepted else "rejected",
        "tool_key": _id("tool-key"),
        "tool_name": tool_name,
        "transition_id": _id(transition_label) if accepted else None,
    }
    return RuntimeReceipt(
        {
            **body,
            "receipt_id": domain_fingerprint(RUNTIME_RECEIPT_DOMAIN, body),
        }
    )


def _context():
    policy = _policy()
    wrapper = GovernanceWrapper(policy)
    task, governance = wrapper.admit_task(
        "task.example",
        {"claim": "all declared gates pass"},
        requester=PrincipalAuthority.OPENAI_SUPERVISOR,
    )
    decision, proposal, capability, dependency_state_id = _tool_bundle(
        "read.pure",
        ToolAuthorityClass.PURE_READ,
        {"label": "arguments"},
        label="context",
        dependency_state_id=_id("dependency"),
    )
    tool_admission = wrapper.admit_tool(
        task,
        governance,
        decision,
        proposal,
        capability,
        ToolAuthorityClass.PURE_READ,
        dependency_state_id=dependency_state_id,
        requester=PrincipalAuthority.DETERMINISTIC_ORCHESTRATOR,
    )
    admission = _admission_receipt(decision=decision)
    orchestration = wrapper.bind_orchestration(
        task,
        governance,
        admission,
        (tool_admission,),
    )
    runtime = _runtime_receipt(
        admission_id=tool_admission.action_id,
        arguments_id=tool_admission.arguments_id,
        dependency_fingerprint=tool_admission.dependency_fingerprint,
        tool_name=tool_admission.tool_name,
    )
    execution = ExecutionReceipt(
        policy,
        task,
        governance,
        orchestration,
        runtime,
        runtime,
        aggregate_admission_id=_id("aggregate-admission"),
        aggregate_input_id=_id("aggregate-input"),
        aggregate_result_id=_id("aggregate-result"),
        aggregate_receipt_id=_id("aggregate-receipts"),
        transition_count=1,
    )
    return policy, wrapper, task, governance, admission, orchestration, runtime, execution


def _live_accumulator(task, policy, orchestration) -> EvidenceAccumulator:
    try:
        return EvidenceAccumulator(
            task.task_id,
            policy.governance_id,
            orchestration.orchestration_id,
            authorization_manifest=orchestration.authorization_manifest,
            max_cases=8,
            max_failure_details=2,
        )
    except ImportError as exc:
        pytest.skip(f"native evidence reducer is not rebuilt locally: {exc}")


def _execute_live_read(
    orchestration,
    session_key: str,
    *,
    admission_id: str | None = None,
    arguments=None,
    dependency_fingerprint: str | None = None,
    tool_name: str | None = None,
    result=None,
):
    tool_admission = orchestration.tool_admissions[0]
    runtime = RustRuntimeSession(session_key)
    transition = runtime.execute_read_transition(
        tool_admission.tool_name if tool_name is None else tool_name,
        tool_admission.arguments if arguments is None else arguments,
        (
            tool_admission.dependency_fingerprint
            if dependency_fingerprint is None
            else dependency_fingerprint
        ),
        lambda: {"value": 1} if result is None else result,
        admission_id=(
            tool_admission.action_id if admission_id is None else admission_id
        ),
    )
    return runtime, transition.receipt


def _satisfied_gates(orchestration, execution, evidence):
    return (
        AcceptanceGateResult(
            COMPACT_EVIDENCE_GATE_KEY,
            True,
            evidence.receipt_id,
        ),
        AcceptanceGateResult(
            ORCHESTRATION_RECEIPT_GATE_KEY,
            True,
            orchestration.receipt_id,
        ),
        AcceptanceGateResult(
            EXECUTION_RECEIPT_GATE_KEY,
            True,
            execution.receipt_id,
        ),
    )


def _live_final_context():
    policy, wrapper, task, governance, admission, orchestration, _, _ = _context()
    accumulator = _live_accumulator(task, policy, orchestration)
    _, runtime = _execute_live_read(orchestration, "governance-live-runtime")
    accumulator.record_runtime_case(runtime)
    summary = accumulator.aggregate_summary()
    execution = wrapper.bind_execution(
        task,
        governance,
        orchestration,
        summary,
    )
    evidence = accumulator.finalize(execution.execution_id)
    gates = _satisfied_gates(orchestration, execution, evidence)
    return (
        policy,
        wrapper,
        task,
        governance,
        admission,
        orchestration,
        runtime,
        execution,
        evidence,
        gates,
    )


def test_openai_is_the_only_remote_provider_and_policy_version_is_identity_bearing():
    first = _policy(1)
    second = _policy(2)
    assert first.provider_authority is ProviderAuthority.OPENAI
    assert first.governance_id != second.governance_id
    malformed = first.canonical_record()
    malformed["provider_authority"] = "anthropic"
    with pytest.raises(ValueError, match="unknown authority"):
        GovernancePolicy.from_record(malformed)
    with pytest.raises(ValueError, match="provider authority must be openai"):
        replace(first, provider_authority="openai")


def test_policy_authority_roles_and_acceptance_gate_registry_are_closed():
    policy = _policy()
    assert policy.required_gate_keys == tuple(sorted(SUPPORTED_REQUIRED_GATE_KEYS))
    assert policy.canonical_record()["protocol_version"] == GOVERNANCE_PROTOCOL_VERSION
    with pytest.raises(ValueError, match="supervisor authority is fixed"):
        replace(
            policy,
            supervisor_authority=PrincipalAuthority.LOCAL_CANDIDATE_WORKER,
        )
    with pytest.raises(ValueError, match="closed v1 acceptance gate set"):
        replace(policy, required_gate_keys=(COMPACT_EVIDENCE_GATE_KEY,))
    with pytest.raises(ValueError, match="closed v1 acceptance gate set"):
        replace(
            policy,
            required_gate_keys=(*policy.required_gate_keys, "tests.green"),
        )
    malformed = policy.canonical_record()
    malformed["unexpected"] = True
    with pytest.raises(ValueError, match="v1 schema"):
        ReceiptValidator.validate_policy(malformed)


def test_policy_parser_bounds_untrusted_permission_and_gate_iterables():
    policy = _policy()
    oversized_permissions = policy.canonical_record()
    permission = oversized_permissions["tool_permissions"][0]
    oversized_permissions["tool_permissions"] = _oversized_records(
        permission,
        MAX_TOOL_PERMISSIONS,
    )
    with pytest.raises(ValueError, match="hard limit"):
        GovernancePolicy.from_record(oversized_permissions)

    oversized_gates = policy.canonical_record()
    oversized_gates["required_gate_keys"] = _oversized_records(
        COMPACT_EVIDENCE_GATE_KEY,
        MAX_REQUIRED_GATES,
    )
    with pytest.raises(ValueError, match="hard limit"):
        GovernancePolicy.from_record(oversized_gates)

    with pytest.raises(ValueError, match="hard limit"):
        GovernancePolicy.from_record(
            _HostileOversizedMapping(policy.canonical_record())
        )


def test_policy_protocol_version_is_identity_bearing_and_exact():
    policy = _policy()
    malformed = policy.canonical_record()
    malformed["protocol_version"] = "IBAE-GOVERNANCE-PROTOCOL-V999"
    with pytest.raises(ValueError, match="bound authority"):
        GovernancePolicy.from_record(malformed)


def test_tool_permissions_require_explicit_non_contradictory_authority():
    with pytest.raises(TypeError):
        ToolPermission("mutate", ToolAuthorityClass.IDEMPOTENT_MUTATION)  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="read tools"):
        ToolPermission("read", ToolAuthorityClass.PURE_READ, True, False)
    with pytest.raises(ValueError, match="observation cache"):
        ToolPermission(
            "mutate",
            ToolAuthorityClass.IDEMPOTENT_MUTATION,
            True,
            True,
        )
    with pytest.raises(ValueError, match="volatile"):
        ToolPermission("volatile", ToolAuthorityClass.VOLATILE_READ, False, True)


@pytest.mark.parametrize(
    "requester",
    [
        PrincipalAuthority.LOCAL_CANDIDATE_WORKER,
        PrincipalAuthority.DETERMINISTIC_ORCHESTRATOR,
        PrincipalAuthority.RUST_EXECUTION_RUNTIME,
    ],
)
def test_only_openai_supervisor_can_admit_a_task(requester: PrincipalAuthority):
    wrapper = GovernanceWrapper(_policy())
    with pytest.raises(GovernanceRejected) as rejected:
        wrapper.admit_task("task.example", {}, requester=requester)
    assert rejected.value.receipt.status == "rejected"
    assert (
        rejected.value.receipt.reason
        is GovernanceRejectionReason.AUTHORITY_ESCALATION
    )
    assert "IBAE-LAY-002" in rejected.value.receipt.invariant_ids


def test_governance_state_is_immutable_and_returned_policy_is_a_copy():
    policy, wrapper, task, governance, *_ = _context()
    with pytest.raises(FrozenInstanceError):
        governance.policy_version = 99  # type: ignore[misc]
    returned = wrapper.policy_record
    returned["policy_version"] = 99
    assert wrapper.governance_id == policy.governance_id
    wrapper_identity = wrapper.governance_id
    object.__setattr__(policy, "policy_version", 2)
    assert policy.governance_id != wrapper_identity
    assert wrapper.governance_id == wrapper_identity
    assert wrapper.policy_record["policy_version"] == 1
    next_task, next_governance = wrapper.admit_task(
        "task.snapshot-policy",
        {"claim": "caller mutation cannot rewrite wrapper authority"},
        requester=PrincipalAuthority.OPENAI_SUPERVISOR,
    )
    assert next_governance.governance_id == wrapper_identity
    assert next_task.required_gate_keys == task.required_gate_keys
    task_contract = task.acceptance_contract
    task_contract["claim"] = "forged"
    assert task.acceptance_contract["claim"] != "forged"


def test_only_orchestrator_can_admit_tools_and_unknown_tools_fail_closed():
    _, wrapper, task, governance, *_ = _context()
    decision, proposal, capability, dependency_state_id = _tool_bundle(
        "read.pure",
        ToolAuthorityClass.PURE_READ,
        {},
        label="requester-authority",
    )
    for requester in (
        PrincipalAuthority.OPENAI_SUPERVISOR,
        PrincipalAuthority.LOCAL_CANDIDATE_WORKER,
        PrincipalAuthority.RUST_EXECUTION_RUNTIME,
    ):
        with pytest.raises(GovernanceRejected) as rejected:
            wrapper.admit_tool(
                task,
                governance,
                decision,
                proposal,
                capability,
                ToolAuthorityClass.PURE_READ,
                dependency_state_id=dependency_state_id,
                requester=requester,
            )
        assert rejected.value.receipt.reason is GovernanceRejectionReason.AUTHORITY_ESCALATION

    unknown_decision, unknown_proposal, unknown_capability, unknown_dependency = (
        _tool_bundle(
            "read.unknown",
            ToolAuthorityClass.PURE_READ,
            {},
            label="unknown-tool",
        )
    )
    with pytest.raises(GovernanceRejected) as unknown:
        wrapper.admit_tool(
            task,
            governance,
            unknown_decision,
            unknown_proposal,
            unknown_capability,
            ToolAuthorityClass.PURE_READ,
            dependency_state_id=unknown_dependency,
            requester=PrincipalAuthority.DETERMINISTIC_ORCHESTRATOR,
        )
    assert unknown.value.receipt.reason is GovernanceRejectionReason.UNKNOWN_TOOL_PERMISSION


def test_tool_admission_invalid_authority_contexts_emit_rejection_receipts():
    _, wrapper, _, governance, *_ = _context()
    decision, proposal, capability, dependency_state_id = _tool_bundle(
        "read.pure",
        ToolAuthorityClass.PURE_READ,
        {},
        label="invalid-governance-context",
    )

    with pytest.raises(GovernanceRejected) as malformed:
        wrapper.admit_tool(
            object(),  # type: ignore[arg-type]
            governance,
            decision,
            proposal,
            capability,
            ToolAuthorityClass.PURE_READ,
            dependency_state_id=dependency_state_id,
            requester=PrincipalAuthority.DETERMINISTIC_ORCHESTRATOR,
        )
    assert (
        malformed.value.receipt.reason
        is GovernanceRejectionReason.INVALID_BOUND_RECEIPT
    )
    assert malformed.value.receipt.bound_receipt_ids == ()

    foreign_wrapper = GovernanceWrapper(_policy(version=2))
    foreign_task, foreign_governance = foreign_wrapper.admit_task(
        "task.foreign",
        {"claim": "belongs to another governance policy"},
        requester=PrincipalAuthority.OPENAI_SUPERVISOR,
    )
    with pytest.raises(GovernanceRejected) as foreign:
        wrapper.admit_tool(
            foreign_task,
            foreign_governance,
            decision,
            proposal,
            capability,
            ToolAuthorityClass.PURE_READ,
            dependency_state_id=dependency_state_id,
            requester=PrincipalAuthority.DETERMINISTIC_ORCHESTRATOR,
        )
    assert (
        foreign.value.receipt.reason
        is GovernanceRejectionReason.INVALID_BOUND_RECEIPT
    )
    assert foreign.value.receipt.bound_receipt_ids == ()


def test_orchestration_binding_invalid_contexts_emit_rejection_receipts():
    _, wrapper, task, governance, admission, orchestration, *_ = _context()
    foreign_wrapper = GovernanceWrapper(_policy(version=2))
    foreign_task, foreign_governance = foreign_wrapper.admit_task(
        "task.foreign-orchestration",
        {"claim": "belongs to another governance policy"},
        requester=PrincipalAuthority.OPENAI_SUPERVISOR,
    )
    missing_slot_task = TaskReceipt.from_record(task.canonical_record())
    object.__delattr__(missing_slot_task, "task_key")

    for candidate_task, candidate_governance in (
        (object(), governance),
        (missing_slot_task, governance),
        (task, object()),
        (task, foreign_governance),
        (foreign_task, foreign_governance),
    ):
        with pytest.raises(GovernanceRejected) as rejected:
            wrapper.bind_orchestration(
                candidate_task,  # type: ignore[arg-type]
                candidate_governance,  # type: ignore[arg-type]
                admission,
                orchestration.tool_admissions,
            )
        assert (
            rejected.value.receipt.reason
            is GovernanceRejectionReason.INVALID_BOUND_RECEIPT
        )
        assert rejected.value.receipt.stage is ReceiptStage.ORCHESTRATION
        assert rejected.value.receipt.task_id is None
        assert rejected.value.receipt.bound_receipt_ids == ()


def test_execution_binding_invalid_contexts_emit_rejection_receipts():
    _, wrapper, task, governance, _, orchestration, *_ = _context()
    foreign_wrapper = GovernanceWrapper(_policy(version=2))
    foreign_task, foreign_governance = foreign_wrapper.admit_task(
        "task.foreign-execution",
        {"claim": "belongs to another governance policy"},
        requester=PrincipalAuthority.OPENAI_SUPERVISOR,
    )
    missing_slot_task = TaskReceipt.from_record(task.canonical_record())
    object.__delattr__(missing_slot_task, "task_key")

    for candidate_task, candidate_governance, candidate_orchestration in (
        (object(), governance, orchestration),
        (missing_slot_task, governance, orchestration),
        (task, object(), orchestration),
        (task, foreign_governance, orchestration),
        (foreign_task, foreign_governance, orchestration),
        (task, governance, object()),
    ):
        with pytest.raises(GovernanceRejected) as rejected:
            wrapper.bind_execution(
                candidate_task,  # type: ignore[arg-type]
                candidate_governance,  # type: ignore[arg-type]
                candidate_orchestration,  # type: ignore[arg-type]
                object(),
            )
        assert (
            rejected.value.receipt.reason
            is GovernanceRejectionReason.INVALID_BOUND_RECEIPT
        )
        assert rejected.value.receipt.stage is ReceiptStage.EXECUTION
        assert rejected.value.receipt.task_id is None
        assert rejected.value.receipt.bound_receipt_ids == ()


def test_read_classes_preserve_declared_cache_and_dependency_semantics():
    _, wrapper, task, governance, *_ = _context()
    pure_decision, pure_proposal, pure_capability, pure_dependency = _tool_bundle(
        "read.pure",
        ToolAuthorityClass.PURE_READ,
        {"key": "value"},
        label="pure-read",
    )
    pure = wrapper.admit_tool(
        task,
        governance,
        pure_decision,
        pure_proposal,
        pure_capability,
        ToolAuthorityClass.PURE_READ,
        dependency_state_id=pure_dependency,
        requester=PrincipalAuthority.DETERMINISTIC_ORCHESTRATOR,
    )
    assert pure.cache_reuse_permitted is True
    assert pure.occurrence_key is None

    snapshot_decision, snapshot_proposal, snapshot_capability, snapshot_dependency = (
        _tool_bundle(
            "read.snapshot",
            ToolAuthorityClass.SNAPSHOT_READ,
            {},
            label="snapshot-read",
        )
    )
    with pytest.raises(GovernanceRejected) as missing_dependency:
        wrapper.admit_tool(
            task,
            governance,
            snapshot_decision,
            snapshot_proposal,
            snapshot_capability,
            ToolAuthorityClass.SNAPSHOT_READ,
            dependency_state_id=None,
            requester=PrincipalAuthority.DETERMINISTIC_ORCHESTRATOR,
        )
    assert (
        missing_dependency.value.receipt.reason
        is GovernanceRejectionReason.DEPENDENCY_ID_REQUIRED
    )
    snapshot = wrapper.admit_tool(
        task,
        governance,
        snapshot_decision,
        snapshot_proposal,
        snapshot_capability,
        ToolAuthorityClass.SNAPSHOT_READ,
        dependency_state_id=snapshot_dependency,
        requester=PrincipalAuthority.DETERMINISTIC_ORCHESTRATOR,
    )
    assert snapshot.cache_reuse_permitted is True
    (
        missing_occurrence_decision,
        missing_occurrence_proposal,
        volatile_capability,
        volatile_dependency,
    ) = _tool_bundle(
        "read.volatile",
        ToolAuthorityClass.VOLATILE_READ,
        {},
        label="volatile-missing-occurrence",
    )
    with pytest.raises(GovernanceRejected) as missing_occurrence:
        wrapper.admit_tool(
            task,
            governance,
            missing_occurrence_decision,
            missing_occurrence_proposal,
            volatile_capability,
            ToolAuthorityClass.VOLATILE_READ,
            dependency_state_id=volatile_dependency,
            requester=PrincipalAuthority.DETERMINISTIC_ORCHESTRATOR,
        )
    assert (
        missing_occurrence.value.receipt.reason
        is GovernanceRejectionReason.OCCURRENCE_ID_REQUIRED
    )
    volatile_decision, volatile_proposal, volatile_capability, volatile_dependency = (
        _tool_bundle(
            "read.volatile",
            ToolAuthorityClass.VOLATILE_READ,
            {},
            label="volatile-read",
            occurrence_key="volatile.occurrence",
        )
    )
    volatile = wrapper.admit_tool(
        task,
        governance,
        volatile_decision,
        volatile_proposal,
        volatile_capability,
        ToolAuthorityClass.VOLATILE_READ,
        dependency_state_id=volatile_dependency,
        requester=PrincipalAuthority.DETERMINISTIC_ORCHESTRATOR,
    )
    assert volatile.cache_reuse_permitted is False


@pytest.mark.parametrize(
    "tool_name,authority_class",
    [
        ("mutate.idempotent", ToolAuthorityClass.IDEMPOTENT_MUTATION),
        (
            "mutate.non_idempotent",
            ToolAuthorityClass.NON_IDEMPOTENT_MUTATION,
        ),
    ],
)
def test_every_mutation_requires_occurrence_identity_and_never_collapses(
    tool_name: str,
    authority_class: ToolAuthorityClass,
):
    _, wrapper, task, governance, *_ = _context()
    missing_decision, missing_proposal, missing_capability, missing_dependency = (
        _tool_bundle(
            tool_name,
            authority_class,
            {"same": "payload"},
            label=f"{tool_name}-missing-occurrence",
        )
    )
    with pytest.raises(GovernanceRejected) as missing:
        wrapper.admit_tool(
            task,
            governance,
            missing_decision,
            missing_proposal,
            missing_capability,
            authority_class,
            dependency_state_id=missing_dependency,
            requester=PrincipalAuthority.DETERMINISTIC_ORCHESTRATOR,
        )
    assert missing.value.receipt.reason is GovernanceRejectionReason.OCCURRENCE_ID_REQUIRED

    first_decision, first_proposal, first_capability, first_dependency = _tool_bundle(
        tool_name,
        authority_class,
        {"same": "payload"},
        label=f"{tool_name}-occurrence-one",
        occurrence_key="occurrence.one",
    )
    first = wrapper.admit_tool(
        task,
        governance,
        first_decision,
        first_proposal,
        first_capability,
        authority_class,
        dependency_state_id=first_dependency,
        requester=PrincipalAuthority.DETERMINISTIC_ORCHESTRATOR,
    )
    second_decision, second_proposal, second_capability, second_dependency = (
        _tool_bundle(
            tool_name,
            authority_class,
            {"same": "payload"},
            label=f"{tool_name}-occurrence-two",
            occurrence_key="occurrence.two",
        )
    )
    second = wrapper.admit_tool(
        task,
        governance,
        second_decision,
        second_proposal,
        second_capability,
        authority_class,
        dependency_state_id=second_dependency,
        requester=PrincipalAuthority.DETERMINISTIC_ORCHESTRATOR,
    )
    assert first.action_id != second.action_id
    assert first.governed_action_id != second.governed_action_id


def test_unspecified_or_mismatched_mutation_permission_fails_closed():
    _, wrapper, task, governance, *_ = _context()
    denied_decision, denied_proposal, denied_capability, denied_dependency = (
        _tool_bundle(
            "mutate.denied",
            ToolAuthorityClass.IDEMPOTENT_MUTATION,
            {},
            label="denied-mutation",
            occurrence_key="occurrence.denied",
        )
    )
    with pytest.raises(GovernanceRejected) as denied:
        wrapper.admit_tool(
            task,
            governance,
            denied_decision,
            denied_proposal,
            denied_capability,
            ToolAuthorityClass.IDEMPOTENT_MUTATION,
            dependency_state_id=denied_dependency,
            requester=PrincipalAuthority.DETERMINISTIC_ORCHESTRATOR,
        )
    assert denied.value.receipt.reason is GovernanceRejectionReason.MUTATION_NOT_PERMITTED
    mismatch_decision, mismatch_proposal, mismatch_capability, mismatch_dependency = (
        _tool_bundle(
            "read.pure",
            ToolAuthorityClass.PURE_READ,
            {},
            label="mismatched-mutation",
        )
    )
    with pytest.raises(GovernanceRejected) as mismatch:
        wrapper.admit_tool(
            task,
            governance,
            mismatch_decision,
            mismatch_proposal,
            mismatch_capability,
            ToolAuthorityClass.NON_IDEMPOTENT_MUTATION,
            dependency_state_id=mismatch_dependency,
            requester=PrincipalAuthority.DETERMINISTIC_ORCHESTRATOR,
        )
    assert mismatch.value.receipt.reason is GovernanceRejectionReason.TOOL_CLASS_MISMATCH


def test_noncanonical_tool_input_and_read_occurrence_fail_closed():
    _, wrapper, task, governance, _, orchestration, *_ = _context()
    bound = orchestration.tool_admissions[0]
    with pytest.raises(GovernanceRejected) as malformed:
        wrapper.admit_tool(
            task,
            governance,
            bound.admission_decision,
            None,
            bound.capability,
            ToolAuthorityClass.PURE_READ,
            dependency_state_id=bound.dependency_fingerprint,
            requester=PrincipalAuthority.DETERMINISTIC_ORCHESTRATOR,
        )
    assert malformed.value.receipt.reason is GovernanceRejectionReason.MALFORMED_ACTION
    occurrence_decision, occurrence_proposal, occurrence_capability, occurrence_dependency = (
        _tool_bundle(
            "read.pure",
            ToolAuthorityClass.PURE_READ,
            {},
            label="read-with-occurrence",
            occurrence_key="occurrence.invalid",
        )
    )
    with pytest.raises(GovernanceRejected) as occurrence:
        wrapper.admit_tool(
            task,
            governance,
            occurrence_decision,
            occurrence_proposal,
            occurrence_capability,
            ToolAuthorityClass.PURE_READ,
            dependency_state_id=occurrence_dependency,
            requester=PrincipalAuthority.DETERMINISTIC_ORCHESTRATOR,
        )
    assert occurrence.value.receipt.reason is GovernanceRejectionReason.OCCURRENCE_ID_FORBIDDEN


def test_tool_admission_recomputes_the_typed_v02_action_and_rejects_effect_relabeling():
    _, wrapper, task, governance, _, orchestration, *_ = _context()
    bound = orchestration.tool_admissions[0]

    forged_action = replace(
        bound.admission_decision,
        action_id=_id("forged-v0.2-action"),
    )
    with pytest.raises(GovernanceRejected) as action_rejected:
        wrapper.admit_tool(
            task,
            governance,
            forged_action,
            bound.proposal,
            bound.capability,
            ToolAuthorityClass.PURE_READ,
            dependency_state_id=bound.dependency_fingerprint,
            requester=PrincipalAuthority.DETERMINISTIC_ORCHESTRATOR,
        )
    assert (
        action_rejected.value.receipt.reason
        is GovernanceRejectionReason.MALFORMED_ACTION
    )

    effect_decision, effect_proposal, _, effect_dependency = _tool_bundle(
        "mutate.idempotent",
        ToolAuthorityClass.IDEMPOTENT_MUTATION,
        bound.arguments,
        label="effect-relabel",
        occurrence_key="effect.relabel.occurrence",
        dependency_state_id=bound.dependency_fingerprint,
    )
    with pytest.raises(GovernanceRejected) as relabel_rejected:
        wrapper.admit_tool(
            task,
            governance,
            effect_decision,
            effect_proposal,
            bound.capability,
            ToolAuthorityClass.PURE_READ,
            dependency_state_id=effect_dependency,
            requester=PrincipalAuthority.DETERMINISTIC_ORCHESTRATOR,
        )
    assert (
        relabel_rejected.value.receipt.reason
        is GovernanceRejectionReason.OCCURRENCE_ID_FORBIDDEN
    )

    wrong_layer = replace(
        bound.admission_decision,
        authority_layer=AuthorityLayer.EXECUTION,
    )
    with pytest.raises(GovernanceRejected) as layer_rejected:
        wrapper.admit_tool(
            task,
            governance,
            wrong_layer,
            bound.proposal,
            bound.capability,
            ToolAuthorityClass.PURE_READ,
            dependency_state_id=bound.dependency_fingerprint,
            requester=PrincipalAuthority.DETERMINISTIC_ORCHESTRATOR,
        )
    assert (
        layer_rejected.value.receipt.reason
        is GovernanceRejectionReason.MALFORMED_ACTION
    )

    blocked = replace(
        bound.admission_decision,
        blocking_obligation_ids=(_id("impossible-admitted-blocker"),),
    )
    with pytest.raises(GovernanceRejected) as blocker_rejected:
        wrapper.admit_tool(
            task,
            governance,
            blocked,
            bound.proposal,
            bound.capability,
            ToolAuthorityClass.PURE_READ,
            dependency_state_id=bound.dependency_fingerprint,
            requester=PrincipalAuthority.DETERMINISTIC_ORCHESTRATOR,
        )
    assert (
        blocker_rejected.value.receipt.reason
        is GovernanceRejectionReason.MALFORMED_ACTION
    )


def test_identity_domains_cannot_alias_equal_payloads():
    payload = {"same": "payload"}
    identities = {
        domain_fingerprint(domain, payload)
        for domain in (
            TASK_ID_DOMAIN,
            GOVERNANCE_ID_DOMAIN,
            ORCHESTRATION_ID_DOMAIN,
            EXECUTION_ID_DOMAIN,
            EXECUTION_PLAN_ID_DOMAIN,
            BENCHMARK_ID_DOMAIN,
            FINAL_ACCEPTANCE_ID_DOMAIN,
        )
    }
    assert len(identities) == 7


def test_receipt_validators_recompute_identity_and_reject_unknown_fields():
    policy, wrapper, task, governance, admission, orchestration, runtime, execution = _context()
    assert ReceiptValidator.validate_policy(policy.canonical_record()) == policy
    assert ReceiptValidator.validate_task(task.canonical_record()) == task
    assert ReceiptValidator.validate_governance(
        governance.canonical_record(), policy=policy, task=task
    ) == governance
    assert ReceiptValidator.validate_orchestration(
        orchestration.canonical_record(),
        policy=policy,
        task=task,
        governance=governance,
        admission_receipt=admission,
        tool_admissions=orchestration.tool_admissions,
    ) == orchestration
    assert ReceiptValidator.validate_execution(
        execution.canonical_record(),
        policy=policy,
        task=task,
        governance=governance,
        orchestration=orchestration,
        initial_runtime_receipt=runtime,
        final_runtime_receipt=runtime,
    ) == execution

    forged = governance.canonical_record()
    forged["policy_version"] = 999
    with pytest.raises(ValueError, match="bound authority"):
        ReceiptValidator.validate_governance(forged, policy=policy, task=task)
    unknown = task.canonical_record()
    unknown["wall_clock"] = 1.25
    with pytest.raises(ValueError, match="v1 schema"):
        ReceiptValidator.validate_task(unknown)


def test_orchestration_requires_an_exact_bounded_tool_authorization_manifest():
    policy, wrapper, task, governance, admission, orchestration, runtime, _ = _context()
    tool_admission = orchestration.tool_admissions[0]
    assert tool_admission.action_id == admission.decisions[0].action_id
    assert tool_admission.governed_action_id != tool_admission.action_id
    assert orchestration.authorization_manifest_count == 1
    assert orchestration.authorization_manifest == (
        {
            "action_id": tool_admission.action_id,
            "arguments_id": tool_admission.arguments_id,
            "authority_class": ToolAuthorityClass.PURE_READ.name,
            "cache_reuse_permitted": True,
            "dependency_fingerprint": tool_admission.dependency_fingerprint,
            "tool_admission_receipt_id": tool_admission.receipt_id,
            "tool_name": tool_admission.tool_name,
        },
    )
    assert (
        authorization_manifest_identity(orchestration.authorization_manifest)
        == orchestration.authorization_manifest_id
    )
    assert runtime.canonical_record()["admission_id"] == tool_admission.action_id

    with pytest.raises(GovernanceRejected) as missing:
        wrapper.bind_orchestration(task, governance, admission, ())
    assert missing.value.receipt.reason is GovernanceRejectionReason.INVALID_BOUND_RECEIPT

    unrelated_decision, unrelated_proposal, unrelated_capability, unrelated_dependency = (
        _tool_bundle(
            "read.pure",
            ToolAuthorityClass.PURE_READ,
            tool_admission.arguments,
            label="unrelated-v0.2-action",
            dependency_state_id=tool_admission.dependency_fingerprint,
        )
    )
    unrelated = wrapper.admit_tool(
        task,
        governance,
        unrelated_decision,
        unrelated_proposal,
        unrelated_capability,
        ToolAuthorityClass.PURE_READ,
        dependency_state_id=unrelated_dependency,
        requester=PrincipalAuthority.DETERMINISTIC_ORCHESTRATOR,
    )
    with pytest.raises(GovernanceRejected) as unrelated_binding:
        wrapper.bind_orchestration(task, governance, admission, (unrelated,))
    assert (
        unrelated_binding.value.receipt.reason
        is GovernanceRejectionReason.INVALID_BOUND_RECEIPT
    )

    with pytest.raises(GovernanceRejected) as duplicate:
        wrapper.bind_orchestration(
            task,
            governance,
            admission,
            (tool_admission, tool_admission),
        )
    assert duplicate.value.receipt.reason is GovernanceRejectionReason.INVALID_BOUND_RECEIPT


def test_orchestration_rejects_deduplication_without_an_earlier_admitted_source():
    _, wrapper, task, governance, _, orchestration, _, _ = _context()
    tool_admission = orchestration.tool_admissions[0]
    orphan = AdmissionDecision(
        proposal_id=_id("orphan-deduplicated-proposal"),
        proposal_key="proposal.orphan",
        status=DecisionStatus.DEDUPLICATED,
        logical_tick=1,
        action_id=tool_admission.action_id,
        equivalent_proposal_id=_id("missing-admitted-proposal"),
    )
    forged_admission = AdmissionReceipt(
        batch_id=_id("orphan-deduplicated-batch"),
        strategy_id=_id("strategy"),
        prior_state_id=_id("orchestration-prior"),
        next_state_id=_id("orchestration-next"),
        status=BatchStatus.PROCESSED,
        proposal_ordering=ProposalOrdering.CANONICAL_INDEPENDENT,
        logical_tick_start=0,
        logical_tick_end=1,
        decisions=(orphan,),
    )
    with pytest.raises(GovernanceRejected) as rejected:
        wrapper.bind_orchestration(
            task,
            governance,
            forged_admission,
            (tool_admission,),
        )
    assert rejected.value.receipt.reason is GovernanceRejectionReason.INVALID_BOUND_RECEIPT


def test_orchestration_rejects_duplicate_admitted_proposal_identity():
    policy, _, task, governance, admission, orchestration, *_ = _context()
    admitted = admission.decisions[0]
    duplicate = AdmissionDecision(
        proposal_id=admitted.proposal_id,
        proposal_key=admitted.proposal_key,
        status=DecisionStatus.DEDUPLICATED,
        logical_tick=2,
        action_id=admitted.action_id,
        equivalent_proposal_id=admitted.proposal_id,
        dependency_state_keys=admitted.dependency_state_keys,
    )
    duplicate_receipt = replace(
        admission,
        logical_tick_end=2,
        decisions=(admitted, duplicate),
    )
    with pytest.raises(ValueError, match="one proposal identity"):
        type(orchestration)(
            policy,
            task,
            governance,
            duplicate_receipt,
            orchestration.tool_admissions,
        )

    duplicate_key = replace(
        duplicate,
        proposal_id=_id("distinct-proposal-with-duplicate-key"),
    )
    duplicate_key_receipt = replace(
        admission,
        proposal_ordering=ProposalOrdering.DECLARED_SEQUENCE,
        logical_tick_end=2,
        decisions=(admitted, duplicate_key),
    )
    with pytest.raises(ValueError, match="one proposal key"):
        type(orchestration)(
            policy,
            task,
            governance,
            duplicate_key_receipt,
            orchestration.tool_admissions,
        )


def test_occurrence_sensitive_governance_requires_declared_sequence_admission():
    _, wrapper, task, governance, *_ = _context()
    decision, proposal, capability, dependency_state_id = _tool_bundle(
        "read.volatile",
        ToolAuthorityClass.VOLATILE_READ,
        {},
        label="ordering-contract",
        occurrence_key="ordering.contract.occurrence",
    )
    tool_admission = wrapper.admit_tool(
        task,
        governance,
        decision,
        proposal,
        capability,
        ToolAuthorityClass.VOLATILE_READ,
        dependency_state_id=dependency_state_id,
        requester=PrincipalAuthority.DETERMINISTIC_ORCHESTRATOR,
    )
    with pytest.raises(GovernanceRejected) as rejected:
        wrapper.bind_orchestration(
            task,
            governance,
            _admission_receipt(decision=decision),
            (tool_admission,),
        )
    assert (
        rejected.value.receipt.reason
        is GovernanceRejectionReason.INVALID_BOUND_RECEIPT
    )


def test_distinct_governed_actions_cannot_alias_one_runtime_cache_key():
    _, wrapper, task, governance, *_ = _context()
    first_decision, first_proposal, first_capability, dependency_state_id = (
        _tool_bundle(
            "read.pure",
            ToolAuthorityClass.PURE_READ,
            {"key": "value"},
            label="cache-key-first",
        )
    )
    second_capability = replace(first_capability, contract_version=2)
    second_proposal = ActionProposal(
        "proposal.cache-key-second",
        second_capability.name,
        first_proposal.arguments,
        target_obligation_ids=(_id("cache-key-second-obligation"),),
    )
    second_action_id = domain_fingerprint(
        ACTION_ID_DOMAIN,
        {
            "arguments": second_capability.normalize_arguments(
                second_proposal.arguments
            ),
            "capability_id": second_capability.capability_id,
            "dependency_state_id": dependency_state_id,
        },
    )
    second_decision = AdmissionDecision(
        proposal_id=second_proposal.proposal_id,
        proposal_key=second_proposal.proposal_key,
        status=DecisionStatus.ADMITTED,
        logical_tick=2,
        action_id=second_action_id,
    )
    first_tool = wrapper.admit_tool(
        task,
        governance,
        first_decision,
        first_proposal,
        first_capability,
        ToolAuthorityClass.PURE_READ,
        dependency_state_id=dependency_state_id,
        requester=PrincipalAuthority.DETERMINISTIC_ORCHESTRATOR,
    )
    second_tool = wrapper.admit_tool(
        task,
        governance,
        second_decision,
        second_proposal,
        second_capability,
        ToolAuthorityClass.PURE_READ,
        dependency_state_id=dependency_state_id,
        requester=PrincipalAuthority.DETERMINISTIC_ORCHESTRATOR,
    )
    admission = AdmissionReceipt(
        batch_id=_id("cache-key-collision-batch"),
        strategy_id=_id("strategy"),
        prior_state_id=_id("cache-key-collision-prior"),
        next_state_id=_id("cache-key-collision-next"),
        status=BatchStatus.PROCESSED,
        proposal_ordering=ProposalOrdering.DECLARED_SEQUENCE,
        logical_tick_start=0,
        logical_tick_end=2,
        decisions=(first_decision, second_decision),
    )
    with pytest.raises(GovernanceRejected) as rejected:
        wrapper.bind_orchestration(
            task,
            governance,
            admission,
            (first_tool, second_tool),
        )
    assert (
        rejected.value.receipt.reason
        is GovernanceRejectionReason.INVALID_BOUND_RECEIPT
    )


@pytest.mark.parametrize(
    "tool_name,authority_class,occurrence_key",
    [
        (
            "read.volatile",
            ToolAuthorityClass.VOLATILE_READ,
            "volatile.occurrence",
        ),
        (
            "mutate.idempotent",
            ToolAuthorityClass.IDEMPOTENT_MUTATION,
            "mutation.occurrence",
        ),
    ],
)
def test_effectful_admissions_are_governable_but_not_read_runtime_finalizable(
    tool_name: str,
    authority_class: ToolAuthorityClass,
    occurrence_key: str,
):
    _, wrapper, task, governance, *_ = _context()
    decision, proposal, capability, dependency_state_id = _tool_bundle(
        tool_name,
        authority_class,
        {"value": 1},
        label=f"{tool_name}-governed-action",
        occurrence_key=occurrence_key,
        dependency_state_id=_id("effect-dependency"),
    )
    tool_admission = wrapper.admit_tool(
        task,
        governance,
        decision,
        proposal,
        capability,
        authority_class,
        dependency_state_id=dependency_state_id,
        requester=PrincipalAuthority.DETERMINISTIC_ORCHESTRATOR,
    )
    orchestration = wrapper.bind_orchestration(
        task,
        governance,
        _admission_receipt(
            decision=decision,
            ordering=ProposalOrdering.DECLARED_SEQUENCE,
        ),
        (tool_admission,),
    )
    assert orchestration.authorization_manifest_count == 1
    with pytest.raises(ValueError, match="runtime-finalizable"):
        authorization_manifest_identity(orchestration.authorization_manifest)


def test_tool_receipt_validator_binds_live_policy_permission():
    policy, wrapper, task, governance, *_ = _context()
    decision, proposal, capability, dependency_state_id = _tool_bundle(
        "read.snapshot",
        ToolAuthorityClass.SNAPSHOT_READ,
        {"path": "README.md"},
        label="validated-tool-action",
        dependency_state_id=_id("tree"),
    )
    receipt = wrapper.admit_tool(
        task,
        governance,
        decision,
        proposal,
        capability,
        ToolAuthorityClass.SNAPSHOT_READ,
        dependency_state_id=dependency_state_id,
        requester=PrincipalAuthority.DETERMINISTIC_ORCHESTRATOR,
    )
    validated = ReceiptValidator.validate_tool_admission(
        receipt.canonical_record(),
        policy=policy,
        task=task,
        governance=governance,
        admission_decision=decision,
        proposal=proposal,
        capability=capability,
    )
    assert validated.receipt_id == receipt.receipt_id
    forged = receipt.canonical_record()
    forged["cache_reuse_permitted"] = False
    with pytest.raises(ValueError, match="bound authority"):
        ReceiptValidator.validate_tool_admission(
            forged,
            policy=policy,
            task=task,
            governance=governance,
            admission_decision=decision,
            proposal=proposal,
            capability=capability,
        )


def test_execution_binds_a_real_accepted_runtime_receipt_and_fixed_shape_aggregate():
    policy, _, task, governance, _, orchestration, _, execution = _context()
    record = execution.canonical_record()
    assert isinstance(execution.final_runtime_receipt, RuntimeReceipt)
    assert execution.initial_runtime_receipt is execution.final_runtime_receipt
    assert "runtime_receipt_ids" not in record
    assert len(record["initial_runtime_receipt_id"]) == 64
    assert len(record["final_runtime_receipt_id"]) == 64
    assert record["transition_count"] == 1
    with pytest.raises(ValueError, match="rejected runtime"):
        type(execution)(
            policy,
            task,
            governance,
            orchestration,
            _runtime_receipt(accepted=False),
            _runtime_receipt(accepted=False),
            aggregate_admission_id=_id("admissions"),
            aggregate_input_id=_id("input"),
            aggregate_result_id=_id("result"),
            aggregate_receipt_id=_id("receipts"),
            transition_count=1,
        )
    with pytest.raises((TypeError, ValueError), match="positive integer"):
        type(execution)(
            policy,
            task,
            governance,
            orchestration,
            execution.initial_runtime_receipt,
            execution.final_runtime_receipt,
            aggregate_admission_id=execution.aggregate_admission_id,
            aggregate_input_id=execution.aggregate_input_id,
            aggregate_result_id=execution.aggregate_result_id,
            aggregate_receipt_id=execution.aggregate_receipt_id,
            transition_count=True,
        )


def test_execution_rejects_cross_session_and_wrong_single_transition_boundaries():
    policy, _, task, governance, _, orchestration, runtime, execution = _context()
    with pytest.raises(ValueError, match="one runtime session"):
        ExecutionReceipt(
            policy,
            task,
            governance,
            orchestration,
            runtime,
            _runtime_receipt(
                admission_label="other-admission",
                command_label="other-command",
                session_label="other-session",
                prior_state_label="runtime-next",
                resulting_state_label="runtime-final",
                logical_tick=6,
            ),
            aggregate_admission_id=_id("admissions"),
            aggregate_input_id=_id("input"),
            aggregate_result_id=_id("result"),
            aggregate_receipt_id=_id("receipts"),
            transition_count=2,
        )

    separately_parsed = RuntimeReceipt(runtime.canonical_record())
    reconstructed = ExecutionReceipt(
        policy,
        task,
        governance,
        orchestration,
        separately_parsed,
        execution.final_runtime_receipt,
        aggregate_admission_id=execution.aggregate_admission_id,
        aggregate_input_id=execution.aggregate_input_id,
        aggregate_result_id=execution.aggregate_result_id,
        aggregate_receipt_id=execution.aggregate_receipt_id,
        transition_count=1,
    )
    assert reconstructed.canonical_record() == execution.canonical_record()

    with pytest.raises(ValueError, match="one canonical runtime receipt"):
        ExecutionReceipt(
            policy,
            task,
            governance,
            orchestration,
            _runtime_receipt(
                admission_label="wrong-initial-admission",
                command_label="wrong-initial-command",
            ),
            execution.final_runtime_receipt,
            aggregate_admission_id=execution.aggregate_admission_id,
            aggregate_input_id=execution.aggregate_input_id,
            aggregate_result_id=execution.aggregate_result_id,
            aggregate_receipt_id=execution.aggregate_receipt_id,
            transition_count=1,
        )


def test_execution_plan_and_benchmark_are_separate_non_correctness_receipts():
    policy, _, task, governance, _, orchestration, _, execution = _context()
    first_plan = ExecutionPlanReceipt(
        policy,
        task,
        governance,
        orchestration,
        {"device": "cpu", "workers": 1},
    )
    second_plan = ExecutionPlanReceipt(
        policy,
        task,
        governance,
        orchestration,
        {"device": "candidate-gpu", "workers": 32},
    )
    first_benchmark = BenchmarkReceipt(
        task, execution, {"elapsed_ms": 999, "throughput": 1}
    )
    second_benchmark = BenchmarkReceipt(
        task, execution, {"elapsed_ms": 1, "throughput": 999}
    )
    assert first_plan.execution_plan_id != second_plan.execution_plan_id
    assert first_benchmark.benchmark_id != second_benchmark.benchmark_id
    assert first_benchmark.execution_id == second_benchmark.execution_id
    assert execution.execution_id == execution.execution_id
    assert first_plan.canonical_record()["correctness_authority"] is False
    assert first_benchmark.canonical_record()["correctness_authority"] is False
    assert ReceiptValidator.validate_execution_plan(
        first_plan.canonical_record(),
        policy=policy,
        task=task,
        governance=governance,
        orchestration=orchestration,
    ) == first_plan
    assert ReceiptValidator.validate_benchmark(
        first_benchmark.canonical_record(), task=task, execution=execution
    ) == first_benchmark


def test_missing_or_unsatisfied_gates_remain_partial_and_cannot_be_relabelled():
    _, wrapper, task, governance, _, orchestration, _, execution = _context()
    results = (
        AcceptanceGateResult(COMPACT_EVIDENCE_GATE_KEY, False, None),
        AcceptanceGateResult(
            ORCHESTRATION_RECEIPT_GATE_KEY, True, orchestration.receipt_id
        ),
        AcceptanceGateResult(EXECUTION_RECEIPT_GATE_KEY, False, None),
    )
    partial = wrapper.finalize(
        task,
        governance,
        orchestration,
        execution,
        None,
        results,
        requester=PrincipalAuthority.OPENAI_SUPERVISOR,
    )
    assert isinstance(partial, PartialReceipt)
    assert partial.status == "partial"
    assert partial.missing_gate_keys == (
        COMPACT_EVIDENCE_GATE_KEY,
        EXECUTION_RECEIPT_GATE_KEY,
    )
    forged = partial.canonical_record()
    forged["status"] = "accepted"
    with pytest.raises(ValueError, match="bound authority"):
        ReceiptValidator.validate_partial(
            forged,
            policy=_policy(),
            task=task,
            governance=governance,
            orchestration=orchestration,
            execution=execution,
        )


def test_arbitrary_self_asserted_acceptance_gate_is_rejected():
    _, wrapper, task, governance, _, orchestration, _, execution = _context()
    results = (
        AcceptanceGateResult(
            COMPACT_EVIDENCE_GATE_KEY,
            True,
            _id("claimed-compact-evidence"),
        ),
        AcceptanceGateResult(
            ORCHESTRATION_RECEIPT_GATE_KEY,
            True,
            orchestration.receipt_id,
        ),
        AcceptanceGateResult(
            EXECUTION_RECEIPT_GATE_KEY,
            True,
            execution.receipt_id,
        ),
        AcceptanceGateResult(
            "self.asserted",
            True,
            _id("self-asserted-evidence"),
        ),
    )
    with pytest.raises(GovernanceRejected) as rejected:
        wrapper.finalize(
            task,
            governance,
            orchestration,
            execution,
            None,
            results,
            requester=PrincipalAuthority.OPENAI_SUPERVISOR,
        )
    assert (
        rejected.value.receipt.reason
        is GovernanceRejectionReason.UNKNOWN_ACCEPTANCE_GATE
    )


def test_partial_receipt_parser_bounds_untrusted_gate_iterables():
    policy, wrapper, task, governance, _, orchestration, _, execution = _context()
    results = (
        AcceptanceGateResult(COMPACT_EVIDENCE_GATE_KEY, False, None),
        AcceptanceGateResult(
            ORCHESTRATION_RECEIPT_GATE_KEY,
            True,
            orchestration.receipt_id,
        ),
        AcceptanceGateResult(EXECUTION_RECEIPT_GATE_KEY, False, None),
    )
    partial = wrapper.finalize(
        task,
        governance,
        orchestration,
        execution,
        None,
        results,
        requester=PrincipalAuthority.OPENAI_SUPERVISOR,
    )
    assert isinstance(partial, PartialReceipt)
    omitted_missing = partial.canonical_record()
    omitted_missing["missing_gate_keys"] = []
    with pytest.raises(ValueError, match="exactly match"):
        ReceiptValidator.validate_partial(
            omitted_missing,
            policy=policy,
            task=task,
            governance=governance,
            orchestration=orchestration,
            execution=execution,
        )

    oversized = partial.canonical_record()
    gate_record = oversized["bound_gate_results"][0]
    oversized["bound_gate_results"] = _oversized_records(
        gate_record,
        MAX_REQUIRED_GATES,
    )
    with pytest.raises(ValueError, match="hard limit"):
        ReceiptValidator.validate_partial(
            oversized,
            policy=policy,
            task=task,
            governance=governance,
            orchestration=orchestration,
            execution=execution,
        )


def test_missing_bound_layer_receipts_produce_structural_partial_state():
    _, wrapper, task, governance, _, orchestration, *_ = _context()
    empty_results: tuple[AcceptanceGateResult, ...] = ()
    partial = wrapper.finalize(
        task,
        governance,
        None,
        None,
        None,
        empty_results,
        requester=PrincipalAuthority.OPENAI_SUPERVISOR,
    )
    assert isinstance(partial, PartialReceipt)
    assert partial.status == "partial"
    assert partial.orchestration_id is None
    assert partial.execution_id is None

    all_claimed = tuple(
        AcceptanceGateResult(gate_key, True, _id(f"unbound-{gate_key}"))
        for gate_key in sorted(SUPPORTED_REQUIRED_GATE_KEYS)
    )
    with pytest.raises(GovernanceRejected) as missing_orchestration:
        wrapper.finalize(
            task,
            governance,
            None,
            None,
            None,
            all_claimed,
            requester=PrincipalAuthority.OPENAI_SUPERVISOR,
        )
    assert (
        missing_orchestration.value.receipt.reason
        is GovernanceRejectionReason.INVALID_BOUND_RECEIPT
    )

    impossible_execution_gate = (
        AcceptanceGateResult(COMPACT_EVIDENCE_GATE_KEY, False, None),
        AcceptanceGateResult(
            ORCHESTRATION_RECEIPT_GATE_KEY,
            True,
            orchestration.receipt_id,
        ),
        AcceptanceGateResult(
            EXECUTION_RECEIPT_GATE_KEY,
            True,
            _id("missing-execution-receipt"),
        ),
    )
    with pytest.raises(GovernanceRejected) as missing_execution:
        wrapper.finalize(
            task,
            governance,
            orchestration,
            None,
            None,
            impossible_execution_gate,
            requester=PrincipalAuthority.OPENAI_SUPERVISOR,
        )
    assert (
        missing_execution.value.receipt.reason
        is GovernanceRejectionReason.INVALID_BOUND_RECEIPT
    )


@pytest.mark.parametrize(
    "requester",
    [
        PrincipalAuthority.LOCAL_CANDIDATE_WORKER,
        PrincipalAuthority.DETERMINISTIC_ORCHESTRATOR,
        PrincipalAuthority.RUST_EXECUTION_RUNTIME,
    ],
)
def test_worker_or_runtime_cannot_finalize(requester: PrincipalAuthority):
    _, wrapper, task, governance, _, orchestration, _, execution = _context()
    with pytest.raises(GovernanceRejected) as rejected:
        wrapper.finalize(
            task,
            governance,
            orchestration,
            execution,
            None,
            (),
            requester=requester,
        )
    assert rejected.value.receipt.reason is GovernanceRejectionReason.AUTHORITY_ESCALATION


def test_rejection_receipt_is_closed_canonical_and_never_accepted():
    with pytest.raises(TypeError, match="ReceiptStage"):
        RejectionReceipt(
            stage="governance",  # type: ignore[arg-type]
            reason=GovernanceRejectionReason.UNKNOWN_AUTHORITY,
            task_id=None,
            governance_id=None,
            invariant_ids=("IBAE-GOV-006",),
        )


def test_rejection_receipt_tampering_and_unknown_reasons_fail_closed():
    receipt = RejectionReceipt(
        stage=ReceiptStage.GOVERNANCE,
        reason=GovernanceRejectionReason.UNKNOWN_AUTHORITY,
        task_id=None,
        governance_id=None,
        invariant_ids=("IBAE-GOV-006",),
    )
    assert receipt.status == "rejected"
    assert ReceiptValidator.validate_rejection(receipt.canonical_record()) == receipt
    forged = receipt.canonical_record()
    forged["status"] = "accepted"
    with pytest.raises(ValueError, match="does not match"):
        ReceiptValidator.validate_rejection(forged)
    unknown = receipt.canonical_record()
    unknown["reason"] = "IBAE-REJECT-GUESSED"
    with pytest.raises(ValueError, match="unknown enum"):
        ReceiptValidator.validate_rejection(unknown)


def test_rejection_receipt_canonically_orders_bound_receipt_id_sets():
    bound_ids = {_id("bound-z"), _id("bound-a"), _id("bound-m")}
    from_set = RejectionReceipt(
        stage=ReceiptStage.GOVERNANCE,
        reason=GovernanceRejectionReason.INVALID_BOUND_RECEIPT,
        task_id=None,
        governance_id=None,
        invariant_ids=("IBAE-GOV-007",),
        bound_receipt_ids=bound_ids,
    )
    from_reverse = RejectionReceipt(
        stage=ReceiptStage.GOVERNANCE,
        reason=GovernanceRejectionReason.INVALID_BOUND_RECEIPT,
        task_id=None,
        governance_id=None,
        invariant_ids=("IBAE-GOV-007",),
        bound_receipt_ids=reversed(sorted(bound_ids)),
    )
    assert from_set.bound_receipt_ids == tuple(sorted(bound_ids))
    assert from_set.canonical_record() == from_reverse.canonical_record()


def test_cross_policy_receipts_cannot_be_rebound():
    _, _, task, governance, _, orchestration, _, execution = _context()
    other = _policy(2)
    with pytest.raises(ValueError, match="bound authority"):
        ReceiptValidator.validate_governance(
            governance.canonical_record(), policy=other, task=task
        )
    with pytest.raises(ValueError, match="governance receipt"):
        ExecutionPlanReceipt(
            other,
            task,
            governance,
            orchestration,
            {"workers": 1},
        )
    assert execution.governance_id != other.governance_id


def test_final_acceptance_binds_live_evidence_and_all_typed_layer_receipts():
    (
        policy,
        wrapper,
        task,
        governance,
        _,
        orchestration,
        _,
        execution,
        evidence,
        gates,
    ) = _live_final_context()
    final = wrapper.finalize(
        task,
        governance,
        orchestration,
        execution,
        evidence,
        gates,
        requester=PrincipalAuthority.OPENAI_SUPERVISOR,
    )
    assert final.status == "accepted"
    assert final.task_receipt_id == task.receipt_id
    assert final.governance_receipt_id == governance.receipt_id
    assert final.orchestration_receipt_id == orchestration.receipt_id
    assert final.execution_receipt_id == execution.receipt_id
    assert final.compact_evidence_receipt_id == evidence.receipt_id
    assert final.canonical_record()["producer_authentication_scope"] == (
        "not-established-by-v0.4"
    )
    assert ReceiptValidator.validate_final(
        final.canonical_record(),
        policy=policy,
        task=task,
        governance=governance,
        orchestration=orchestration,
        execution=execution,
        compact_evidence=evidence,
    ) == final


def test_execution_binding_rejects_a_live_summary_from_another_authority_context():
    policy, wrapper, task, governance, _, orchestration, *_ = _context()
    try:
        accumulator = EvidenceAccumulator(
            _id("other-task-context"),
            policy.governance_id,
            orchestration.orchestration_id,
            authorization_manifest=orchestration.authorization_manifest,
            max_cases=8,
            max_failure_details=2,
        )
    except ImportError as exc:
        pytest.skip(f"native evidence reducer is not rebuilt locally: {exc}")
    _, runtime = _execute_live_read(
        orchestration,
        "wrong-evidence-authority-context",
    )
    accumulator.record_runtime_case(runtime)
    summary = accumulator.aggregate_summary()
    with pytest.raises(GovernanceRejected) as rejected:
        wrapper.bind_execution(
            task,
            governance,
            orchestration,
            summary,
        )
    assert (
        rejected.value.receipt.reason
        is GovernanceRejectionReason.INVALID_BOUND_RECEIPT
    )


@pytest.mark.parametrize(
    "gate_key",
    [
        COMPACT_EVIDENCE_GATE_KEY,
        ORCHESTRATION_RECEIPT_GATE_KEY,
        EXECUTION_RECEIPT_GATE_KEY,
    ],
)
def test_final_gate_must_bind_its_exact_validated_receipt(gate_key: str):
    (
        _,
        wrapper,
        task,
        governance,
        _,
        orchestration,
        _,
        execution,
        evidence,
        gates,
    ) = _live_final_context()
    forged_gates = tuple(
        replace(item, evidence_receipt_id=_id(f"forged-{gate_key}"))
        if item.gate_key == gate_key
        else item
        for item in gates
    )
    with pytest.raises(GovernanceRejected) as rejected:
        wrapper.finalize(
            task,
            governance,
            orchestration,
            execution,
            evidence,
            forged_gates,
            requester=PrincipalAuthority.OPENAI_SUPERVISOR,
        )
    assert rejected.value.receipt.reason is GovernanceRejectionReason.INVALID_BOUND_RECEIPT


def test_finalization_rejects_mutated_or_subclassed_gate_records():
    _, wrapper, task, governance, _, orchestration, _, execution = _context()
    mutated = AcceptanceGateResult(COMPACT_EVIDENCE_GATE_KEY, False, None)
    object.__setattr__(mutated, "satisfied", 1)

    class _ForgedGateResult(AcceptanceGateResult):
        pass

    forged = _ForgedGateResult(COMPACT_EVIDENCE_GATE_KEY, False, None)
    for supplied in ((mutated,), (forged,)):
        with pytest.raises(GovernanceRejected) as rejected:
            wrapper.finalize(
                task,
                governance,
                orchestration,
                execution,
                None,
                supplied,
                requester=PrincipalAuthority.OPENAI_SUPERVISOR,
            )
        assert (
            rejected.value.receipt.reason
            is GovernanceRejectionReason.INVALID_BOUND_RECEIPT
        )


def test_final_receipt_parser_bounds_untrusted_gate_iterable():
    (
        policy,
        wrapper,
        task,
        governance,
        _,
        orchestration,
        _,
        execution,
        evidence,
        gates,
    ) = _live_final_context()
    final = wrapper.finalize(
        task,
        governance,
        orchestration,
        execution,
        evidence,
        gates,
        requester=PrincipalAuthority.OPENAI_SUPERVISOR,
    )
    oversized = final.canonical_record()
    gate_record = oversized["gate_results"][0]
    oversized["gate_results"] = _oversized_records(
        gate_record,
        MAX_REQUIRED_GATES,
    )
    with pytest.raises(ValueError, match="hard limit"):
        ReceiptValidator.validate_final(
            oversized,
            policy=policy,
            task=task,
            governance=governance,
            orchestration=orchestration,
            execution=execution,
            compact_evidence=evidence,
        )


def test_final_identity_is_independent_of_plan_and_benchmark_observations():
    (
        policy,
        wrapper,
        task,
        governance,
        _,
        orchestration,
        _,
        execution,
        evidence,
        gates,
    ) = _live_final_context()
    final = wrapper.finalize(
        task,
        governance,
        orchestration,
        execution,
        evidence,
        gates,
        requester=PrincipalAuthority.OPENAI_SUPERVISOR,
    )
    plan = ExecutionPlanReceipt(
        policy,
        task,
        governance,
        orchestration,
        {"device": "cpu", "worker_count": 1},
    )
    benchmark = BenchmarkReceipt(
        task,
        execution,
        {"elapsed_ms": 123_456, "throughput": 0.01},
    )
    changed_plan = ExecutionPlanReceipt(
        policy,
        task,
        governance,
        orchestration,
        {"device": "candidate", "worker_count": 999},
    )
    changed_benchmark = BenchmarkReceipt(
        task,
        execution,
        {"elapsed_ms": 1, "throughput": 999_999},
    )
    assert plan.execution_plan_id != changed_plan.execution_plan_id
    assert benchmark.benchmark_id != changed_benchmark.benchmark_id
    assert final.final_acceptance_id == final.final_acceptance_id
    assert "benchmark" not in final.canonical_record()
    assert "execution_plan" not in final.canonical_record()


def test_structurally_valid_but_source_unbound_evidence_cannot_finalize():
    (
        _,
        wrapper,
        task,
        governance,
        _,
        orchestration,
        _,
        execution,
        evidence,
        gates,
    ) = _live_final_context()
    parsed = CompactEvidenceReceipt.from_record(evidence.canonical_record())
    assert parsed.source_bound is False
    with pytest.raises(GovernanceRejected) as rejected:
        wrapper.finalize(
            task,
            governance,
            orchestration,
            execution,
            parsed,
            gates,
            requester=PrincipalAuthority.OPENAI_SUPERVISOR,
        )
    assert rejected.value.receipt.reason is GovernanceRejectionReason.INVALID_BOUND_RECEIPT


@pytest.mark.parametrize(
    "mismatch",
    ["admission", "tool", "arguments", "dependency"],
)
def test_runtime_case_cannot_bypass_governed_authorization_manifest(mismatch: str):
    policy, _, task, _, _, orchestration, _, _ = _context()
    accumulator = _live_accumulator(task, policy, orchestration)
    _, forged_runtime = _execute_live_read(
        orchestration,
        f"manifest-bypass-{mismatch}",
        admission_id=(
            _id("unadmitted-runtime-action")
            if mismatch == "admission"
            else None
        ),
        arguments=(
            {"label": "forged-runtime-arguments"}
            if mismatch == "arguments"
            else None
        ),
        dependency_fingerprint=(
            _id("forged-runtime-dependency")
            if mismatch == "dependency"
            else None
        ),
        tool_name="read.snapshot" if mismatch == "tool" else None,
    )
    with pytest.raises(ValueError, match="authorization manifest"):
        accumulator.record_runtime_case(forged_runtime)


def test_runtime_cache_hit_requires_explicit_governed_reuse_permission():
    base_policy = _policy()
    policy = replace(
        base_policy,
        tool_permissions=tuple(
            replace(permission, allow_cache_reuse=False)
            if permission.tool_name == "read.pure"
            else permission
            for permission in base_policy.tool_permissions
        ),
    )
    wrapper = GovernanceWrapper(policy)
    task, governance = wrapper.admit_task(
        "task.cache-permission",
        {"claim": "cache reuse remains explicitly governed"},
        requester=PrincipalAuthority.OPENAI_SUPERVISOR,
    )
    decision, proposal, capability, dependency_state_id = _tool_bundle(
        "read.pure",
        ToolAuthorityClass.PURE_READ,
        {"key": "value"},
        label="cache-permission",
    )
    tool_admission = wrapper.admit_tool(
        task,
        governance,
        decision,
        proposal,
        capability,
        ToolAuthorityClass.PURE_READ,
        dependency_state_id=dependency_state_id,
        requester=PrincipalAuthority.DETERMINISTIC_ORCHESTRATOR,
    )
    assert tool_admission.cache_reuse_permitted is False
    orchestration = wrapper.bind_orchestration(
        task,
        governance,
        _admission_receipt(decision=decision),
        (tool_admission,),
    )
    accumulator = _live_accumulator(task, policy, orchestration)
    runtime = RustRuntimeSession("governed-cache-permission")
    first = runtime.execute_admitted_read(
        decision,
        proposal,
        capability,
        dependency_state_id,
        lambda: {"value": 1},
    )
    second = runtime.execute_admitted_read(
        decision,
        proposal,
        capability,
        dependency_state_id,
        lambda: {"value": 2},
    )
    assert first.receipt.canonical_record()["cache_status"] == "cold_execution"
    assert second.receipt.canonical_record()["cache_status"] == "cache_hit"
    accumulator.record_runtime_case(first.receipt)
    with pytest.raises(ValueError, match="authorization manifest"):
        accumulator.record_runtime_case(second.receipt)


@pytest.mark.parametrize(
    "mismatch",
    ["result", "receipt", "count"],
)
def test_compact_aggregate_mismatch_cannot_finalize(mismatch: str):
    (
        policy,
        wrapper,
        task,
        governance,
        _,
        orchestration,
        runtime,
        execution,
        _,
        _,
    ) = _live_final_context()
    alternate = _live_accumulator(task, policy, orchestration)
    alternate_session, alternate_runtime = _execute_live_read(
        orchestration,
        (
            "governance-live-runtime"
            if mismatch == "result"
            else f"aggregate-mismatch-{mismatch}"
        ),
        result={"value": 2} if mismatch == "result" else {"value": 1},
    )
    alternate.record_runtime_case(alternate_runtime)
    if mismatch == "count":
        tool_admission = orchestration.tool_admissions[0]
        repeated = alternate_session.execute_read_transition(
            tool_admission.tool_name,
            tool_admission.arguments,
            tool_admission.dependency_fingerprint,
            lambda: {"value": 1},
            admission_id=tool_admission.action_id,
        )
        alternate.record_runtime_case(repeated.receipt)
    alternate.aggregate_summary()
    mismatched_evidence = alternate.finalize(execution.execution_id)
    gates = _satisfied_gates(
        orchestration,
        execution,
        mismatched_evidence,
    )
    with pytest.raises(GovernanceRejected) as rejected:
        wrapper.finalize(
            task,
            governance,
            orchestration,
            execution,
            mismatched_evidence,
            gates,
            requester=PrincipalAuthority.OPENAI_SUPERVISOR,
        )
    assert rejected.value.receipt.reason is GovernanceRejectionReason.INVALID_BOUND_RECEIPT


def test_hierarchical_evidence_is_not_v1_final_correctness_authority():
    (
        policy,
        wrapper,
        task,
        governance,
        _,
        orchestration,
        runtime,
        _,
        _,
        _,
    ) = _live_final_context()
    child_accumulator = _live_accumulator(task, policy, orchestration)
    child_accumulator.record_runtime_case(runtime)
    child_accumulator.aggregate_summary()
    child = child_accumulator.finalize(_id("child-execution"))

    parent = _live_accumulator(task, policy, orchestration)
    parent.ingest_child(child)
    summary = parent.aggregate_summary()
    with pytest.raises(GovernanceRejected) as bind_rejection:
        wrapper.bind_execution(task, governance, orchestration, summary)
    assert (
        bind_rejection.value.receipt.reason
        is GovernanceRejectionReason.INVALID_BOUND_RECEIPT
    )
    execution = ExecutionReceipt(
        policy,
        task,
        governance,
        orchestration,
        runtime,
        runtime,
        aggregate_admission_id=summary.aggregate_admission_identity,
        aggregate_input_id=summary.aggregate_input_identity,
        aggregate_result_id=summary.aggregate_result_identity,
        aggregate_receipt_id=summary.aggregate_receipt_identity,
        transition_count=summary.case_counts.total,
    )
    evidence = parent.finalize(execution.execution_id)
    assert evidence.child_receipt_count == 1
    gates = _satisfied_gates(orchestration, execution, evidence)
    with pytest.raises(GovernanceRejected) as rejected:
        wrapper.finalize(
            task,
            governance,
            orchestration,
            execution,
            evidence,
            gates,
            requester=PrincipalAuthority.OPENAI_SUPERVISOR,
        )
    assert rejected.value.receipt.reason is GovernanceRejectionReason.INVALID_BOUND_RECEIPT
