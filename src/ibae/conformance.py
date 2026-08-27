"""Deterministic reference fixtures for implemented IBAE contracts."""

from __future__ import annotations

from ._records import CanonicalValue
from .canonical import canonical_fingerprint, domain_fingerprint
from .continuation import (
    CHECKPOINT_PROTOCOL_VERSION,
    CONTINUATION_EVIDENCE_VERSION,
    CONTINUATION_PROTOCOL_VERSION,
    PARTIAL_CONTINUATION_VERSION,
    PROGRESS_PROTOCOL_VERSION,
    BudgetVector,
    ContinuationCheckpoint,
    ContinuationEvidenceReceipt,
    ContinuationPartialReason,
    ContinuationPartialReceipt,
    ContinuationPolicyReceipt,
    ContinuationRequest,
    ContinuationState,
    LeaseGrantReceipt,
    ProgressDimension,
    ProgressDirection,
    ProgressMeasureContract,
    ProgressSource,
    StrategyMaterialization,
    commit_lease_application,
    evaluate_continuation,
    evaluate_progress,
    evaluate_strategy_change,
    experimental_continuation_profile,
    observe_continuation_context,
)
from .continuation_benchmark import run_budget_profile_benchmark
from .epistemic import (
    EpistemicClass,
    EpistemicRecord,
    EpistemicState,
    ObservationProvenance,
)
from .evidence import (
    MAX_COMPACT_EVIDENCE_BYTES,
    EvidenceAccumulator,
    EvidenceLimits,
)
from .governance import (
    COMPACT_EVIDENCE_GATE_KEY,
    EXECUTION_RECEIPT_GATE_KEY,
    GOVERNANCE_PROTOCOL_VERSION,
    ORCHESTRATION_RECEIPT_GATE_KEY,
    AcceptanceGateResult,
    BenchmarkReceipt,
    ExecutionPlanReceipt,
    GovernancePolicy,
    GovernanceRejected,
    GovernanceWrapper,
    PrincipalAuthority,
    ProviderAuthority,
    ToolAuthorityClass,
    ToolPermission,
)
from .obligations import Obligation, ObligationStatus
from .orchestration import (
    ActionProposal,
    Capability,
    OrchestrationState,
    ProposalBatch,
    ProposalOrdering,
    ReplaySafety,
    Strategy,
    StrategyParameterSpec,
    StrategySchema,
    StrategyValueKind,
    admit_batch,
)
from .reference_executor import PythonReferenceExecutor
from .runtime import (
    RUNTIME_LEASE_APPLICATION_PROTOCOL_VERSION,
    RUNTIME_PROTOCOL_VERSION,
    RuntimeRejected,
    RustRuntimeSession,
    rust_canonical_json,
)


def v0_2_reference_fixture() -> dict[str, object]:
    """Build the byte-stable, model-free v0.2 orchestration fixture."""

    inspect = Obligation(
        "inspect-source",
        "Inspect the canonical source state.",
        status=ObligationStatus.SATISFIED,
    )
    tests = Obligation(
        "repair-tests",
        "Repair the failing deterministic tests.",
        dependency_ids=(inspect.obligation_id,),
    )
    ci = Obligation(
        "verify-ci",
        "Verify the repaired state in continuous integration.",
        dependency_ids=(tests.obligation_id,),
    )
    review = Obligation(
        "review-gate",
        "Wait for an external review gate.",
        status=ObligationStatus.BLOCKED,
        block_reason="external review has not completed",
    )

    provenance = ObservationProvenance(
        source="github.read",
        source_identity=domain_fingerprint(
            "ibae.fixture-source.v1", {"commit": "76016db"}
        ),
        dependency_identity=domain_fingerprint(
            "ibae.fixture-dependency.v1", {"ref": "main"}
        ),
        reused=False,
    )
    epistemic_state = EpistemicState.from_iterable(
        (
            EpistemicRecord(
                "repo-head",
                EpistemicClass.OBSERVED,
                {"commit": "76016db", "tree_clean": True},
                provenance=provenance,
            ),
            EpistemicRecord(
                "failing-tests",
                EpistemicClass.DERIVED,
                2,
                dependencies=("repo-head",),
            ),
            EpistemicRecord(
                "patch-plan",
                EpistemicClass.MODEL_PROPOSED,
                {"files": ["src/ibae/orchestration.py"]},
            ),
            EpistemicRecord("review-state", EpistemicClass.UNKNOWN),
        )
    )
    strategy_schema = StrategySchema(
        "repair-reference",
        (
            StrategyParameterSpec(
                "ordering",
                StrategyValueKind.SYMBOL,
                allowed_symbols=("declared_sequence",),
            ),
            StrategyParameterSpec(
                "version",
                StrategyValueKind.BOUNDED_INTEGER,
                minimum=1,
                maximum=1,
            ),
        ),
    )
    state = OrchestrationState.create(
        (ci, review, tests, inspect),
        epistemic_state=epistemic_state,
        capabilities=(
            Capability(
                "read.file",
                ReplaySafety.CACHEABLE_READ,
                "Read a file from an admitted source revision.",
                required_state_keys=("repo-head",),
                semantic_argument_keys=("path", "ref"),
            ),
            Capability(
                "write.patch",
                ReplaySafety.OCCURRENCE_SENSITIVE,
                "Apply one occurrence-identified patch mutation.",
                required_state_keys=("failing-tests", "repo-head"),
                semantic_argument_keys=("patch",),
            ),
            Capability(
                "ci.remote",
                ReplaySafety.CACHEABLE_READ,
                "Inspect remote continuous-integration state.",
                available=False,
                required_state_keys=("repo-head",),
                semantic_argument_keys=("ref",),
            ),
        ),
        strategy_schemas=(strategy_schema,),
    )

    proposals = (
        ActionProposal(
            "read-primary",
            "read.file",
            {"path": "src/ibae/orchestration.py"},
            target_obligation_ids=(tests.obligation_id,),
            required_state_keys=("repo-head",),
        ),
        ActionProposal(
            "read-duplicate",
            "read.file",
            {"path": "src/ibae/orchestration.py"},
            target_obligation_ids=(tests.obligation_id,),
            required_state_keys=("repo-head",),
        ),
        ActionProposal(
            "patch-first",
            "write.patch",
            {"patch": "repair-a"},
            target_obligation_ids=(tests.obligation_id,),
            required_state_keys=("failing-tests", "repo-head"),
            occurrence_key="patch-occurrence-1",
        ),
        ActionProposal(
            "patch-second",
            "write.patch",
            {"patch": "repair-a"},
            target_obligation_ids=(tests.obligation_id,),
            required_state_keys=("failing-tests", "repo-head"),
            occurrence_key="patch-occurrence-2",
        ),
        ActionProposal(
            "needs-review-state",
            "read.file",
            {"path": "review.json"},
            target_obligation_ids=(tests.obligation_id,),
            required_state_keys=("review-state",),
        ),
        ActionProposal(
            "premature-ci",
            "read.file",
            {"ref": "main"},
            target_obligation_ids=(ci.obligation_id,),
        ),
        ActionProposal(
            "blocked-review",
            "read.file",
            {"path": "review.json"},
            target_obligation_ids=(review.obligation_id,),
        ),
        ActionProposal(
            "unavailable-ci",
            "ci.remote",
            {"ref": "main"},
            target_obligation_ids=(tests.obligation_id,),
        ),
        ActionProposal(
            "unknown-capability",
            "missing.tool",
            {},
            target_obligation_ids=(tests.obligation_id,),
        ),
    )
    batch = ProposalBatch(
        "reference-batch",
        Strategy(
            "repair-reference",
            {"ordering": "declared_sequence", "version": 1},
            schema=strategy_schema,
        ),
        proposals,
        ordering=ProposalOrdering.DECLARED_SEQUENCE,
    )
    transition = admit_batch(state, batch)
    return {
        "batch_id": batch.batch_id,
        "input_state_id": state.state_id,
        "next_state_projection": transition.next_state.compact_projection(),
        "ordered_proposal_ids": [
            proposal.proposal_id for proposal in batch.ordered_proposals
        ],
        "receipt": transition.receipt.canonical_record(),
        "receipt_id": transition.receipt.receipt_id,
    }


def _execution_projection(executor: object) -> dict[str, object]:
    if isinstance(executor, PythonReferenceExecutor):
        return {
            "history": list(executor.state.history),
            "metrics": executor.metrics(),
            "terminal_cycle_period": executor.terminal_cycle_period(),
        }
    if isinstance(executor, RustRuntimeSession):
        snapshot = executor.snapshot
        return {
            "history": list(snapshot.history),
            "metrics": {
                "cache_hits": snapshot.cache_hits,
                "executions": snapshot.executions,
                "requests": snapshot.requests,
                "retries": snapshot.retries,
            },
            "terminal_cycle_period": executor.terminal_cycle_period(),
        }
    raise TypeError("unsupported conformance executor")


def v0_3_reference_fixture() -> dict[str, object]:
    """Build the byte-stable, model-free Python/Rust v0.3 fixture."""

    dependency_x = domain_fingerprint("ibae.fixture-dependency.v1", {"ref": "x"})
    dependency_y = domain_fingerprint("ibae.fixture-dependency.v1", {"ref": "y"})
    canonical_corpus = (
        ("empty-mapping", {}),
        ("empty-sequence", []),
        ("mapping-order", {"z": 0, "a": {"y": 2, "x": 1}}),
        ("nested", {"a": [None, True, {"b": [1, 2, 3]}]}),
        ("integer-positive-boundary", (1 << 256) - 1),
        ("integer-negative-boundary", -((1 << 256) - 1)),
        ("unicode", {"text": "λ雪🚀"}),
        ("float-fixed-boundary", 0.0001),
        ("float-exponent-boundary", 1e-5),
        (
            "dependency-fingerprints",
            {"current": dependency_x, "next": dependency_y},
        ),
    )
    canonical_records = []
    for name, value in canonical_corpus:
        python_bytes = CanonicalValue.from_value(value).text
        rust_bytes = rust_canonical_json(python_bytes)
        canonical_records.append(
            {
                "equivalent": python_bytes == rust_bytes,
                "name": name,
                "python_bytes": python_bytes,
                "python_sha256": canonical_fingerprint(value),
                "rust_bytes": rust_bytes,
                "rust_sha256": canonical_fingerprint(CanonicalValue(rust_bytes).to_value()),
            }
        )

    python_repeated = PythonReferenceExecutor()
    rust_repeated = RustRuntimeSession("fixture-repeated")
    python_calls = 0
    rust_calls = 0
    python_results = []
    rust_results = []
    rust_receipts = []

    def python_repeated_operation() -> dict[str, int]:
        nonlocal python_calls
        python_calls += 1
        return {"value": 42}

    def rust_repeated_operation() -> dict[str, int]:
        nonlocal rust_calls
        rust_calls += 1
        return {"value": 42}

    for _ in range(3):
        python_results.append(
            python_repeated.execute_read(
                "read", {"path": "a"}, dependency_x, python_repeated_operation
            )
        )
        transition = rust_repeated.execute_read_transition(
            "read", {"path": "a"}, dependency_x, rust_repeated_operation
        )
        rust_results.append(transition.observation)
        rust_receipts.append(transition.receipt.canonical_record())

    python_dependency = PythonReferenceExecutor()
    rust_dependency = RustRuntimeSession("fixture-dependency")
    python_dependency_calls = 0
    rust_dependency_calls = 0

    def python_dependency_operation() -> dict[str, int]:
        nonlocal python_dependency_calls
        python_dependency_calls += 1
        return {"call": python_dependency_calls}

    def rust_dependency_operation() -> dict[str, int]:
        nonlocal rust_dependency_calls
        rust_dependency_calls += 1
        return {"call": rust_dependency_calls}

    python_dependency_results = [
        python_dependency.execute_read(
            "read", {"path": "a"}, dependency, python_dependency_operation
        )
        for dependency in (dependency_x, dependency_y)
    ]
    rust_dependency_results = [
        rust_dependency.execute_read(
            "read", {"path": "a"}, dependency, rust_dependency_operation
        )
        for dependency in (dependency_x, dependency_y)
    ]

    python_cycle = PythonReferenceExecutor()
    rust_cycle = RustRuntimeSession("fixture-cycle")
    for path in ("a", "b", "a", "b"):
        python_cycle.execute_read(
            "read", {"path": path}, dependency_x, lambda path=path: {"value": path}
        )
        rust_cycle.execute_read(
            "read", {"path": path}, dependency_x, lambda path=path: {"value": path}
        )

    invalid_runtime = RustRuntimeSession("fixture-invalid")
    invalid_rejection = None
    try:
        invalid_runtime.execute_read(
            "read", {"path": "invalid"}, dependency_x, lambda: float("nan")
        )
    except RuntimeRejected as exc:
        invalid_rejection = exc.receipt.canonical_record()
    valid_after_rejection = invalid_runtime.execute_read(
        "read", {"path": "invalid"}, dependency_x, lambda: {"valid": True}
    )

    repeated_python_projection = _execution_projection(python_repeated)
    repeated_rust_projection = _execution_projection(rust_repeated)
    dependency_python_projection = _execution_projection(python_dependency)
    dependency_rust_projection = _execution_projection(rust_dependency)
    cycle_python_projection = _execution_projection(python_cycle)
    cycle_rust_projection = _execution_projection(rust_cycle)
    return {
        "canonicalization": canonical_records,
        "identity_domains": {
            "receipt_empty": domain_fingerprint("ibae.runtime-receipt-id.v1", {}),
            "state_empty": domain_fingerprint("ibae.runtime-state-id.v1", {}),
        },
        "protocol_version": RUNTIME_PROTOCOL_VERSION,
        "scenarios": {
            "cycle_equivalence": {
                "equivalent": cycle_python_projection == cycle_rust_projection,
                "python": cycle_python_projection,
                "rust": cycle_rust_projection,
            },
            "dependency_invalidation": {
                "equivalent": (
                    python_dependency_results == rust_dependency_results
                    and python_dependency_calls == rust_dependency_calls == 2
                    and dependency_python_projection == dependency_rust_projection
                ),
                "operation_calls": rust_dependency_calls,
                "python": dependency_python_projection,
                "results": rust_dependency_results,
                "rust": dependency_rust_projection,
            },
            "invalid_observation": {
                "cache_entries_after_recovery": len(invalid_runtime.snapshot.cache),
                "rejection": invalid_rejection,
                "result_after_rejection": valid_after_rejection,
            },
            "repeated_immutable_read": {
                "equivalent": (
                    python_results == rust_results
                    and python_calls == rust_calls == 1
                    and repeated_python_projection == repeated_rust_projection
                ),
                "operation_calls": rust_calls,
                "python": repeated_python_projection,
                "receipts": rust_receipts,
                "results": rust_results,
                "rust": repeated_rust_projection,
            },
        },
    }


def v0_4_reference_fixture() -> dict[str, object]:
    """Build the byte-stable v0.4 governance and compact-evidence fixture.

    The fixture deliberately uses the real v0.2 admission path, the real v0.3
    Rust runtime, and the opaque native v0.4 evidence reducer.  Its benchmark
    and execution-plan records are siblings of correctness identity, never
    inputs to final acceptance.
    """

    obligation = Obligation(
        "verify-governed-read",
        "Execute and verify one admitted snapshot read.",
    )
    dependency = ObservationProvenance(
        source="fixture.repository",
        source_identity=domain_fingerprint(
            "ibae.v0.4-fixture-source.v1", {"repository": "QSOL-IBAE"}
        ),
        dependency_identity=domain_fingerprint(
            "ibae.v0.4-fixture-revision.v1", {"revision": "v0.4-reference"}
        ),
        reused=False,
    )
    epistemic_state = EpistemicState.from_iterable(
        (
            EpistemicRecord(
                "repo-head",
                EpistemicClass.OBSERVED,
                {"revision": "v0.4-reference", "tree_valid": True},
                provenance=dependency,
            ),
        )
    )
    capability = Capability(
        "read.file",
        ReplaySafety.CACHEABLE_READ,
        "Read one file from an admitted repository revision.",
        required_state_keys=("repo-head",),
        semantic_argument_keys=("path",),
    )
    strategy_schema = StrategySchema("governed-reference")
    orchestration_state = OrchestrationState.create(
        (obligation,),
        epistemic_state=epistemic_state,
        capabilities=(capability,),
        strategy_schemas=(strategy_schema,),
    )
    proposal = ActionProposal(
        "read-reference",
        capability.name,
        {"path": "README.md"},
        target_obligation_ids=(obligation.obligation_id,),
        required_state_keys=("repo-head",),
    )
    batch = ProposalBatch(
        "governed-reference",
        Strategy("governed-reference", {}, schema=strategy_schema),
        (proposal,),
        ordering=ProposalOrdering.CANONICAL_INDEPENDENT,
    )
    admission = admit_batch(orchestration_state, batch)
    decision = admission.receipt.decisions[0]
    if decision.status.value != "admitted" or decision.action_id is None:
        raise AssertionError("v0.4 fixture proposal must be admitted")
    dependency_fingerprint = epistemic_state.dependency_digest(
        decision.dependency_state_keys
    )

    policy = GovernancePolicy(
        policy_key="v0.4.reference",
        policy_version=1,
        task_profile="deterministic-reference",
        task_profile_version=1,
        provider_authority=ProviderAuthority.OPENAI,
        tool_permissions=(
            ToolPermission(
                capability.name,
                ToolAuthorityClass.SNAPSHOT_READ,
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
    wrapper = GovernanceWrapper(policy)
    task, governance = wrapper.admit_task(
        "v0.4.reference-task",
        {
            "claim": "one admitted immutable read is exactly accounted",
            "expected_actual_executions": 1,
            "expected_cache_hits": 2,
            "expected_requests": 3,
        },
        requester=PrincipalAuthority.OPENAI_SUPERVISOR,
    )
    tool_admission = wrapper.admit_tool(
        task,
        governance,
        decision,
        proposal,
        capability,
        ToolAuthorityClass.SNAPSHOT_READ,
        dependency_state_id=dependency_fingerprint,
        requester=PrincipalAuthority.DETERMINISTIC_ORCHESTRATOR,
    )
    orchestration = wrapper.bind_orchestration(
        task,
        governance,
        admission.receipt,
        (tool_admission,),
    )

    runtime = RustRuntimeSession("v0.4-governed-reference")
    operation_calls = 0

    def operation() -> dict[str, object]:
        nonlocal operation_calls
        operation_calls += 1
        return {"content_id": "README.reference", "valid": True}

    accumulator = EvidenceAccumulator(
        task.task_id,
        policy.governance_id,
        orchestration.orchestration_id,
        authorization_manifest=orchestration.authorization_manifest,
        limits=EvidenceLimits(max_cases=3, max_failure_details=1),
        enable_fast_fold=True,
    )
    runtime_receipts = []
    observations = []
    for _ in range(3):
        runtime_transition = runtime.execute_admitted_read(
            decision,
            proposal,
            capability,
            dependency_fingerprint,
            operation,
        )
        accumulator.record_runtime_case(runtime_transition.receipt)
        runtime_receipts.append(runtime_transition.receipt.canonical_record())
        observations.append(runtime_transition.observation)

    evidence_summary = accumulator.aggregate_summary()
    execution = wrapper.bind_execution(
        task,
        governance,
        orchestration,
        evidence_summary,
    )
    compact_evidence = accumulator.finalize(execution.execution_id)
    gate_results = (
        AcceptanceGateResult(
            COMPACT_EVIDENCE_GATE_KEY,
            True,
            compact_evidence.receipt_id,
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
    final_acceptance = wrapper.finalize(
        task,
        governance,
        orchestration,
        execution,
        compact_evidence,
        gate_results,
        requester=PrincipalAuthority.OPENAI_SUPERVISOR,
    )
    partial = wrapper.finalize(
        task,
        governance,
        None,
        None,
        None,
        (),
        requester=PrincipalAuthority.OPENAI_SUPERVISOR,
    )
    try:
        wrapper.admit_tool(
            task,
            governance,
            decision,
            proposal,
            capability,
            ToolAuthorityClass.NON_IDEMPOTENT_MUTATION,
            dependency_state_id=dependency_fingerprint,
            requester=PrincipalAuthority.DETERMINISTIC_ORCHESTRATOR,
        )
    except GovernanceRejected as rejected:
        rejection = rejected.receipt
    else:  # pragma: no cover - this is a fail-closed fixture assertion
        raise AssertionError("mismatched fixture mutation authority must be rejected")

    execution_plan = ExecutionPlanReceipt(
        policy,
        task,
        governance,
        orchestration,
        {
            "implementation": "single_threaded_reference",
            "parallelism": 1,
            "transition_order": "declared_runtime_sequence",
        },
    )
    benchmark = BenchmarkReceipt(
        task,
        execution,
        {
            "correctness_authority": False,
            "measurement_kind": "fixture_observation",
            "observed_transition_count": 3,
        },
    )
    snapshot = runtime.snapshot
    fast_fold = accumulator.fast_regression_observation()
    actual_runtime_metrics = (
        snapshot.requests,
        snapshot.executions,
        snapshot.cache_hits,
        snapshot.retries,
        operation_calls,
    )
    if actual_runtime_metrics != (3, 1, 2, 0, 1):
        raise AssertionError("v0.4 fixture runtime accounting diverged")
    if not compact_evidence.source_bound:
        raise AssertionError("v0.4 fixture evidence must retain native source binding")
    if len(compact_evidence.canonical_text.encode("utf-8")) > (
        MAX_COMPACT_EVIDENCE_BYTES
    ):
        raise AssertionError("v0.4 fixture evidence exceeded its byte ceiling")
    return {
        "authority_receipts": {
            "governance": governance.canonical_record(),
            "policy": policy.canonical_record(),
            "task": task.canonical_record(),
            "tool_admission": tool_admission.canonical_record(),
        },
        "compact_evidence": {
            "compact_bytes": len(compact_evidence.canonical_text.encode("utf-8")),
            "receipt": compact_evidence.canonical_record(),
            "source_bound": compact_evidence.source_bound,
            "summary": evidence_summary.canonical_record(),
            "verification_scope": compact_evidence.verification_scope,
        },
        "execution": {
            "observations": observations,
            "operation_calls": operation_calls,
            "receipt": execution.canonical_record(),
            "runtime_metrics": {
                "actual_executions": snapshot.executions,
                "cache_hits": snapshot.cache_hits,
                "requests": snapshot.requests,
                "retries": snapshot.retries,
            },
            "runtime_receipts": runtime_receipts,
        },
        "finalization": {
            "acceptance": final_acceptance.canonical_record(),
            "gate_results": [item.canonical_record() for item in gate_results],
            "partial": partial.canonical_record(),
            "rejection": rejection.canonical_record(),
        },
        "non_correctness_records": {
            "benchmark": benchmark.canonical_record(),
            "execution_plan": execution_plan.canonical_record(),
            "fast_regression_observation": (
                None
                if fast_fold is None
                else {
                    "algorithm": fast_fold.algorithm,
                    "correctness_authority": fast_fold.correctness_authority,
                    "protocol_version": fast_fold.protocol_version,
                    "value": fast_fold.value,
                }
            ),
        },
        "orchestration": {
            "admission_receipt": admission.receipt.canonical_record(),
            "receipt": orchestration.canonical_record(),
        },
        "protocols": {
            "evidence": compact_evidence.canonical_record()["protocol_version"],
            "governance": GOVERNANCE_PROTOCOL_VERSION,
            "runtime": RUNTIME_PROTOCOL_VERSION,
        },
        "trust_scope": {
            "external_truth_authenticated": False,
            "performance_is_correctness_authority": False,
            "producer_authenticated": False,
        },
    }


def v0_5_reference_fixture() -> dict[str, object]:
    """Build the byte-stable v0.5 progress and continuation fixture."""

    strategy_schema = StrategySchema(
        "bounded-recovery",
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
            "Read through an alternate dependency frontier.",
        ),
        Capability(
            "read.primary",
            ReplaySafety.CACHEABLE_READ,
            "Read through the primary dependency frontier.",
        ),
    )
    obligations = tuple(
        Obligation(
            f"v0.5-obligation-{index}",
            f"Satisfy deterministic continuation obligation {index}.",
        )
        for index in range(3)
    )

    def orchestration(satisfied: int) -> OrchestrationState:
        return OrchestrationState.create(
            tuple(
                item.with_status(ObligationStatus.SATISFIED)
                if index < satisfied
                else item
                for index, item in enumerate(obligations)
            ),
            capabilities=capabilities,
            strategy_schemas=(strategy_schema,),
        )

    before = orchestration(0)
    current = orchestration(1)
    later = orchestration(2)
    target_id = obligations[1].obligation_id
    prior_strategy = StrategyMaterialization(
        Strategy("bounded-recovery", {"mode": "primary"}, schema=strategy_schema),
        capability_frontier=("read.primary",),
        target_obligation_ids=(target_id,),
        dependency_path=(target_id,),
        recovery_mode="primary",
        initial_transition_pattern=(
            domain_fingerprint("ibae.v0.5-transition.v1", {"path": "primary"}),
        ),
        description="Use the primary deterministic path.",
    )
    alternate_strategy = StrategyMaterialization(
        Strategy(
            "bounded-recovery", {"mode": "alternate"}, schema=strategy_schema
        ),
        capability_frontier=("read.alternate",),
        target_obligation_ids=(target_id,),
        dependency_path=(),
        recovery_mode="alternate",
        initial_transition_pattern=(
            domain_fingerprint("ibae.v0.5-transition.v1", {"path": "alternate"}),
        ),
        description="Use the alternate deterministic path.",
    )

    governance_policy = GovernancePolicy(
        policy_key="v0.5.reference",
        policy_version=1,
        task_profile="standard",
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
        "v0.5.reference-task",
        {"claim": "objective progress admits only finite continuation"},
        requester=PrincipalAuthority.OPENAI_SUPERVISOR,
    )
    progress_contract = ProgressMeasureContract(
        "reference.obligations",
        1,
        (
            ProgressDimension(
                "unsatisfied",
                ProgressSource.UNSATISFIED_OBLIGATION_COUNT,
                ProgressDirection.DECREASE,
            ),
        ),
    )
    continuation_policy = experimental_continuation_profile(
        "standard", progress_contract=progress_contract
    )
    continuation_policy_receipt = ContinuationPolicyReceipt(
        continuation_policy, governance_policy, governance
    )
    runtime, requester_authority = RustRuntimeSession.create_continuation(
        "v0.5-progress-continuation-reference",
        continuation_policy=continuation_policy,
        continuation_policy_receipt=continuation_policy_receipt,
    )
    first_progress = evaluate_progress(
        task_id=task.task_id,
        governance_id=governance.governance_id,
        contract=progress_contract,
        prior_state=before,
        current_state=current,
    )
    continuation_state = ContinuationState.create(
        policy=continuation_policy,
        policy_receipt=continuation_policy_receipt,
        runtime_session=runtime,
        orchestration_state=current,
        runtime_snapshot=runtime.snapshot,
        strategy=prior_strategy,
        progress=first_progress,
    )

    first_request = ContinuationRequest.from_state(
        continuation_state,
        progress=first_progress,
        requested_resources=continuation_policy.lease_schedule[0],
        requester=PrincipalAuthority.OPENAI_SUPERVISOR,
        requester_authority=requester_authority,
    )
    first_decision = evaluate_continuation(
        continuation_state,
        first_request,
        runtime_session=runtime,
        policy=continuation_policy,
        policy_receipt=continuation_policy_receipt,
        progress=first_progress,
    )
    if not isinstance(first_decision.receipt, LeaseGrantReceipt):
        raise AssertionError("measurable fixture progress must receive lease one")
    first_application = runtime.apply_lease(first_decision.receipt)
    continuation_state = commit_lease_application(
        first_decision.next_state,
        policy=continuation_policy,
        grant=first_decision.receipt,
        application=first_application,
        runtime_snapshot=runtime.snapshot,
    )

    stalled_progress = evaluate_progress(
        task_id=task.task_id,
        governance_id=governance.governance_id,
        contract=progress_contract,
        prior_state=current,
        current_state=current,
    )
    continuation_state = observe_continuation_context(
        continuation_state,
        policy=continuation_policy,
        orchestration_state=current,
        runtime_snapshot=runtime.snapshot,
        progress=stalled_progress,
    )
    stalled_request = ContinuationRequest.from_state(
        continuation_state,
        progress=stalled_progress,
        requested_resources=continuation_policy.lease_schedule[1],
        requester=PrincipalAuthority.OPENAI_SUPERVISOR,
        requester_authority=requester_authority,
    )
    stalled_decision = evaluate_continuation(
        continuation_state,
        stalled_request,
        runtime_session=runtime,
        policy=continuation_policy,
        policy_receipt=continuation_policy_receipt,
        progress=stalled_progress,
    )
    continuation_state = stalled_decision.next_state

    strategy_change = evaluate_strategy_change(
        task_id=task.task_id,
        governance_id=governance.governance_id,
        orchestration_state=current,
        prior_strategy=prior_strategy,
        proposed_strategy=alternate_strategy,
    )
    recovery_request = ContinuationRequest.from_state(
        continuation_state,
        progress=stalled_progress,
        requested_resources=continuation_policy.lease_schedule[1],
        requester=PrincipalAuthority.OPENAI_SUPERVISOR,
        requester_authority=requester_authority,
        strategy_change=strategy_change,
    )
    recovery_decision = evaluate_continuation(
        continuation_state,
        recovery_request,
        runtime_session=runtime,
        policy=continuation_policy,
        policy_receipt=continuation_policy_receipt,
        progress=stalled_progress,
        strategy_change=strategy_change,
    )
    if not isinstance(recovery_decision.receipt, LeaseGrantReceipt):
        raise AssertionError("material fixture recovery must receive lease two")
    recovery_application = runtime.apply_lease(recovery_decision.receipt)
    continuation_state = commit_lease_application(
        recovery_decision.next_state,
        policy=continuation_policy,
        grant=recovery_decision.receipt,
        application=recovery_application,
        runtime_snapshot=runtime.snapshot,
    )

    final_progress = evaluate_progress(
        task_id=task.task_id,
        governance_id=governance.governance_id,
        contract=progress_contract,
        prior_state=current,
        current_state=later,
    )
    continuation_state = observe_continuation_context(
        continuation_state,
        policy=continuation_policy,
        orchestration_state=later,
        runtime_snapshot=runtime.snapshot,
        progress=final_progress,
        strategy=alternate_strategy,
    )
    exhausted_request = ContinuationRequest.from_state(
        continuation_state,
        progress=final_progress,
        requested_resources=BudgetVector(request_delta=1),
        requester=PrincipalAuthority.OPENAI_SUPERVISOR,
        requester_authority=requester_authority,
    )
    exhausted_decision = evaluate_continuation(
        continuation_state,
        exhausted_request,
        runtime_session=runtime,
        policy=continuation_policy,
        policy_receipt=continuation_policy_receipt,
        progress=final_progress,
    )
    continuation_state = exhausted_decision.next_state
    evidence = ContinuationEvidenceReceipt(
        state=continuation_state,
        policy=continuation_policy,
        progress_records=(first_progress, stalled_progress, final_progress),
    )
    checkpoint = ContinuationCheckpoint(
        state=continuation_state,
        policy=continuation_policy,
        orchestration_state=later,
        runtime_snapshot=runtime.snapshot,
        progress=final_progress,
        strategy=alternate_strategy,
        compact_evidence_receipt_id=evidence.receipt_id,
        relevant_receipt_id=exhausted_decision.receipt.receipt_id,
        partial_reason=ContinuationPartialReason.LEASE_CEILING_EXHAUSTED,
    )
    partial = ContinuationPartialReceipt(
        state=continuation_state,
        checkpoint=checkpoint,
        reason=ContinuationPartialReason.LEASE_CEILING_EXHAUSTED,
    )
    return {
        "authority": {
            "continuation_policy": continuation_policy.canonical_record(),
            "continuation_policy_id": continuation_policy.continuation_policy_id,
            "continuation_policy_receipt": (
                continuation_policy_receipt.canonical_record()
            ),
            "governance": governance.canonical_record(),
            "governance_policy": governance_policy.canonical_record(),
            "task": task.canonical_record(),
        },
        "checkpoint": {
            "checkpoint_id": checkpoint.checkpoint_id,
            "record": checkpoint.canonical_record(),
        },
        "continuation_evidence": evidence.canonical_record(),
        "final_state": {
            "ai_projection": continuation_state.compact_projection(
                continuation_policy
            ),
            "continuation_state_id": continuation_state.continuation_state_id,
            "record": continuation_state.canonical_record(),
            "runtime_snapshot": runtime.snapshot.canonical_record(),
        },
        "lease_decisions": {
            "ceiling_denial": exhausted_decision.receipt.canonical_record(),
            "first_grant": first_decision.receipt.canonical_record(),
            "no_progress_denial": stalled_decision.receipt.canonical_record(),
            "recovery_grant": recovery_decision.receipt.canonical_record(),
        },
        "partial_finalization": {
            "partial_id": partial.partial_id,
            "record": partial.canonical_record(),
        },
        "progress": {
            "first": first_progress.canonical_record(),
            "final": final_progress.canonical_record(),
            "stalled": stalled_progress.canonical_record(),
        },
        "protocols": {
            "checkpoint": CHECKPOINT_PROTOCOL_VERSION,
            "continuation": CONTINUATION_PROTOCOL_VERSION,
            "continuation_evidence": CONTINUATION_EVIDENCE_VERSION,
            "partial": PARTIAL_CONTINUATION_VERSION,
            "progress": PROGRESS_PROTOCOL_VERSION,
            "runtime": RUNTIME_PROTOCOL_VERSION,
            "runtime_lease_application": (
                RUNTIME_LEASE_APPLICATION_PROTOCOL_VERSION
            ),
        },
        "runtime_applications": {
            "first": first_application.canonical_record(),
            "recovery": recovery_application.canonical_record(),
        },
        "strategy_change": strategy_change.canonical_record(),
        "trust_scope": {
            "benchmark_is_correctness_authority": False,
            "checkpoint_producer_authenticated": False,
            "checkpoint_scope": "structural-in-process-lineage-only",
            "cross_process_runtime_reconstruction": False,
            "live_model_provider_called": False,
        },
    }


def v0_5_budget_benchmark_fixture() -> dict[str, object]:
    """Build the byte-stable observational v0.5 budget-profile report."""

    return run_budget_profile_benchmark()
