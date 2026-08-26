"""Deterministic reference fixtures for implemented IBAE contracts."""

from __future__ import annotations

from ._records import CanonicalValue
from .canonical import canonical_fingerprint, domain_fingerprint
from .epistemic import (
    EpistemicClass,
    EpistemicRecord,
    EpistemicState,
    ObservationProvenance,
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
