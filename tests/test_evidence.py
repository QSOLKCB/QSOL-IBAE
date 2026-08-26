from __future__ import annotations

import json

import pytest

from ibae._records import CanonicalValue
from ibae.canonical import canonical_fingerprint, domain_fingerprint
from ibae.evidence import (
    EVIDENCE_PROFILE,
    EVIDENCE_PROTOCOL_VERSION,
    MAX_COMPACT_EVIDENCE_BYTES,
    MAX_U64,
    CompactEvidenceReceipt,
    EvidenceAccumulator,
    EvidenceAggregateSummary,
    EvidenceCounters,
    EvidenceLimits,
    aggregate_admission_stream,
    authorization_manifest_identity,
)
from ibae.runtime import RuntimeReceipt, RustRuntimeSession


def _identity(label: object) -> str:
    return canonical_fingerprint({"identity": label})


def _accumulator(
    label: str,
    *,
    max_cases: int = 100_000,
    max_failure_details: int = 8,
    fold: bool = False,
    authorization_manifest: object = (),
) -> EvidenceAccumulator:
    return EvidenceAccumulator(
        _identity([label, "task"]),
        _identity([label, "governance"]),
        _identity([label, "orchestration"]),
        authorization_manifest=authorization_manifest,
        limits=EvidenceLimits(max_cases, max_failure_details),
        enable_fast_fold=fold,
    )


def _authorization(runtime_receipt: RuntimeReceipt) -> dict[str, object]:
    record = runtime_receipt.canonical_record()
    return {
        "action_id": record["admission_id"],
        "arguments_id": record["arguments_id"],
        "authority_class": "PURE_READ",
        "cache_reuse_permitted": True,
        "dependency_fingerprint": record["dependency_fingerprint"],
        "tool_admission_receipt_id": _identity(
            ["tool admission", record["admission_id"]]
        ),
        "tool_name": record["tool_name"],
    }


def _manifest(*runtime_receipts: RuntimeReceipt) -> tuple[dict[str, object], ...]:
    by_action = {
        receipt.canonical_record()["admission_id"]: _authorization(receipt)
        for receipt in runtime_receipts
    }
    return tuple(by_action[action] for action in sorted(by_action))


def _record(
    accumulator: EvidenceAccumulator,
    index: int,
    *,
    status: str = "passed",
    counters: EvidenceCounters | None = None,
) -> None:
    accumulator.record_case(
        case_id=_identity(["case", index]),
        input_identity=_identity(["input", index]),
        result_identity=_identity(["result", index]),
        receipt_identity=_identity(["receipt", index]),
        status=status,
        counters=counters or EvidenceCounters(requests=1, actual_executions=1),
        failure_reason=None if status == "passed" else "synthetic_failure",
        failure_detail=None if status == "passed" else {"index": index},
    )


def _seal(accumulator: EvidenceAccumulator, label: str = "execution"):
    summary = accumulator.aggregate_summary()
    execution_identity = _identity(
        {
            "aggregate_inputs": summary.aggregate_input_identity,
            "aggregate_receipts": summary.aggregate_receipt_identity,
            "aggregate_results": summary.aggregate_result_identity,
            "cases": summary.case_counts.total,
            "label": label,
        }
    )
    return summary, accumulator.finalize(execution_identity)


def test_authorization_manifest_identity_is_bounded_exact_and_set_ordered() -> None:
    base = {
        "action_id": _identity("manifest action a"),
        "arguments_id": _identity("manifest arguments a"),
        "authority_class": "PURE_READ",
        "cache_reuse_permitted": True,
        "dependency_fingerprint": _identity("manifest dependency a"),
        "tool_admission_receipt_id": _identity("manifest tool receipt a"),
        "tool_name": "read",
    }
    other = {
        **base,
        "action_id": _identity("manifest action b"),
        "arguments_id": _identity("manifest arguments b"),
        "tool_admission_receipt_id": _identity("manifest tool receipt b"),
    }
    assert authorization_manifest_identity([base, other]) == (
        authorization_manifest_identity([other, base])
    )
    assert authorization_manifest_identity([base]) != authorization_manifest_identity(
        [{**base, "cache_reuse_permitted": False}]
    )
    invalid_flag = {**base, "cache_reuse_permitted": 1}
    with pytest.raises(ValueError, match="exact boolean"):
        authorization_manifest_identity([invalid_flag])
    invalid_dependency = {**base, "dependency_fingerprint": None}
    with pytest.raises(ValueError, match="fingerprint"):
        authorization_manifest_identity([invalid_dependency])
    with pytest.raises(ValueError, match="hard bound"):
        authorization_manifest_identity(
            {**base, "action_id": _identity(["oversize", index])}
            for index in range(257)
        )


def test_zero_case_evidence_fails_closed() -> None:
    accumulator = _accumulator("zero", max_cases=1)
    with pytest.raises(ValueError, match="at least one"):
        accumulator.aggregate_summary()
    with pytest.raises(ValueError, match="aggregate_summary"):
        accumulator.finalize(_identity("execution"))


def test_one_runtime_case_is_source_bound_and_independently_validated() -> None:
    runtime = RustRuntimeSession("evidence-runtime")
    transition = runtime.execute_read_transition(
        "read", {"path": "a"}, _identity("dependency"), lambda: {"value": 1}
    )
    manifest = _manifest(transition.receipt)
    accumulator = _accumulator(
        "runtime", max_cases=1, authorization_manifest=manifest
    )
    accumulator.record_runtime_case(transition.receipt)
    summary, receipt = _seal(accumulator)

    assert summary.source_bound
    assert receipt.source_bound
    assert receipt.verification_scope == "live_rust_reducer_ingestion_path"
    assert receipt.status == "complete_no_failures"
    assert receipt.case_counts.total == 1
    assert receipt.counter_totals.requests == 1
    assert receipt.counter_totals.actual_executions == 1
    assert receipt.case_record_count == 1
    assert receipt.child_receipt_count == 0
    assert receipt.aggregate_admission_identity == aggregate_admission_stream(
        [transition.receipt.canonical_record()["admission_id"]]
    )
    assert receipt.authorization_manifest_count == 1
    assert receipt.authorization_manifest_identity == authorization_manifest_identity(
        manifest
    )
    assert summary.first_runtime_receipt is transition.receipt
    assert summary.last_runtime_receipt is transition.receipt
    assert summary.runtime_session_id == transition.receipt.canonical_record()["session_id"]
    assert receipt.first_runtime_receipt_id == transition.receipt.receipt_id
    assert receipt.last_runtime_receipt_id == transition.receipt.receipt_id
    assert receipt.execution_identity != receipt.receipt_id
    assert len(receipt.canonical_text.encode("utf-8")) <= MAX_COMPACT_EVIDENCE_BYTES
    receipt.require_sufficient_for(
        {"declared_case_count", "ordered_result_aggregate"}
    )
    with pytest.raises(ValueError, match="insufficient"):
        receipt.require_sufficient_for({"external_truth"})

    reparsed = CompactEvidenceReceipt.from_json(receipt.canonical_text)
    assert reparsed.receipt_id == receipt.receipt_id
    assert not reparsed.source_bound
    assert reparsed.verification_scope == "structural_schema_and_identity_only"

    structural_runtime = RuntimeReceipt(transition.receipt.canonical_record())
    assert not structural_runtime.source_bound
    structural_accumulator = _accumulator(
        "runtime", max_cases=1, authorization_manifest=manifest
    )
    with pytest.raises(ValueError, match="native-bound"):
        structural_accumulator.record_runtime_case(structural_runtime)


def test_source_bound_evidence_rejects_subclass_and_slot_forgery() -> None:
    with pytest.raises(TypeError, match="cannot be subclassed"):

        class _ForgedSummary(EvidenceAggregateSummary):
            pass

    with pytest.raises(TypeError, match="cannot be subclassed"):

        class _ForgedCompactReceipt(CompactEvidenceReceipt):
            pass

    runtime = RustRuntimeSession("evidence-wrapper-tampering")
    transition = runtime.execute_read_transition(
        "read", {"path": "a"}, _identity("dependency"), lambda: 1
    )
    accumulator = _accumulator(
        "wrapper-tampering",
        max_cases=1,
        authorization_manifest=_manifest(transition.receipt),
    )
    accumulator.record_runtime_case(transition.receipt)
    summary, receipt = _seal(accumulator)

    class _FakeSeal:
        def source_bound(self) -> bool:
            return True

        def validates(self, _record: str) -> bool:
            return True

    with pytest.raises(AttributeError, match="immutable"):
        receipt._native_seal = _FakeSeal()
    object.__setattr__(receipt, "_native_seal", _FakeSeal())
    assert receipt.source_bound is False
    with pytest.raises(ValueError, match="source seal is not trusted"):
        receipt.canonical_record()

    sealed_text = summary._record.text

    class _FakeRecord:
        text = sealed_text

        def to_value(self) -> dict[str, object]:
            return {"summary_id": _identity("forged")}

    with pytest.raises(AttributeError, match="immutable"):
        summary._record = _FakeRecord()
    object.__setattr__(summary, "_record", _FakeRecord())
    assert summary.source_bound is False
    with pytest.raises(ValueError, match="canonical record is not trusted"):
        summary.canonical_record()


@pytest.mark.parametrize("mismatch", ["admission", "tool", "arguments", "dependency"])
def test_native_runtime_case_must_match_the_full_authorization_manifest(
    mismatch: str,
) -> None:
    allowed_runtime = RustRuntimeSession(f"manifest-allowed-{mismatch}")
    admission = _identity(["manifest admission", mismatch])
    dependency = _identity(["manifest dependency", mismatch])
    allowed = allowed_runtime.execute_read_transition(
        "read",
        {"path": "allowed"},
        dependency,
        lambda: 1,
        admission_id=admission,
    )
    forged_runtime = RustRuntimeSession(f"manifest-forged-{mismatch}")
    forged = forged_runtime.execute_read_transition(
        "other.read" if mismatch == "tool" else "read",
        {"path": "forged"} if mismatch == "arguments" else {"path": "allowed"},
        _identity("forged dependency") if mismatch == "dependency" else dependency,
        lambda: 1,
        admission_id=(
            _identity("unmanifested admission")
            if mismatch == "admission"
            else admission
        ),
    )
    manifest = _manifest(allowed.receipt)
    guarded = _accumulator(
        f"manifest-{mismatch}", max_cases=1, authorization_manifest=manifest
    )
    with pytest.raises(ValueError, match="authorization manifest"):
        guarded.record_runtime_case(forged.receipt)
    guarded.record_runtime_case(allowed.receipt)
    _, recovered = _seal(guarded)

    clean = _accumulator(
        f"manifest-{mismatch}", max_cases=1, authorization_manifest=manifest
    )
    clean.record_runtime_case(allowed.receipt)
    _, expected = _seal(clean)
    assert recovered.canonical_text == expected.canonical_text


def test_every_authorized_action_requires_execute_read_evidence() -> None:
    runtime = RustRuntimeSession("manifest-coverage")
    first = runtime.execute_read_transition(
        "read", {"path": "first"}, _identity("manifest dependency"), lambda: 1
    )
    second = runtime.execute_read_transition(
        "read", {"path": "second"}, _identity("manifest dependency"), lambda: 2
    )
    accumulator = _accumulator(
        "manifest-coverage",
        max_cases=2,
        authorization_manifest=_manifest(first.receipt, second.receipt),
    )
    accumulator.record_runtime_case(first.receipt)
    with pytest.raises(ValueError, match="authorized runtime action"):
        accumulator.aggregate_summary()
    accumulator.record_runtime_case(second.receipt)
    summary, receipt = _seal(accumulator)
    assert summary.source_bound and receipt.source_bound


def test_cache_hit_requires_explicit_manifest_reuse_permission() -> None:
    runtime = RustRuntimeSession("manifest-cache-permission")
    admission = _identity("manifest cache action")
    dependency = _identity("manifest cache dependency")
    first = runtime.execute_read_transition(
        "read", {"path": "cached"}, dependency, lambda: 1,
        admission_id=admission,
    )
    cached = runtime.execute_read_transition(
        "read", {"path": "cached"}, dependency, lambda: 2,
        admission_id=admission,
    )
    manifest_entry = _authorization(first.receipt)
    manifest_entry["cache_reuse_permitted"] = False
    guarded = _accumulator(
        "manifest-cache-permission",
        max_cases=2,
        authorization_manifest=(manifest_entry,),
    )
    guarded.record_runtime_case(first.receipt)
    with pytest.raises(ValueError, match="authorization manifest"):
        guarded.record_runtime_case(cached.receipt)
    _, receipt = _seal(guarded)
    assert receipt.source_bound
    assert receipt.case_counts.total == 1
    assert receipt.counter_totals.cache_hits == 0


def test_cache_hit_requires_prior_cold_execution_for_same_admission() -> None:
    dependency = _identity("capability-version dependency")
    stale_runtime = RustRuntimeSession("capability-version-cache")
    stale_runtime.execute_read_transition(
        "read",
        {"path": "same"},
        dependency,
        lambda: {"contract": 1},
        admission_id=_identity("capability contract v1"),
    )
    v2_hit = stale_runtime.execute_read_transition(
        "read",
        {"path": "same"},
        dependency,
        lambda: {"contract": 2},
        admission_id=_identity("capability contract v2"),
    )
    assert v2_hit.receipt.cache_status == "cache_hit"
    manifest = _manifest(v2_hit.receipt)
    guarded = _accumulator(
        "cold-proven-admission", max_cases=1, authorization_manifest=manifest
    )
    with pytest.raises(ValueError, match="prior cold execution"):
        guarded.record_runtime_case(v2_hit.receipt)

    clean_runtime = RustRuntimeSession("capability-version-clean")
    v2_cold = clean_runtime.execute_read_transition(
        "read",
        {"path": "same"},
        dependency,
        lambda: {"contract": 2},
        admission_id=_identity("capability contract v2"),
    )
    guarded.record_runtime_case(v2_cold.receipt)
    _, recovered = _seal(guarded)
    clean = _accumulator(
        "cold-proven-admission", max_cases=1, authorization_manifest=manifest
    )
    clean.record_runtime_case(v2_cold.receipt)
    _, expected = _seal(clean)
    assert recovered.canonical_text == expected.canonical_text


def test_python_slot_mutation_cannot_change_sealed_authority_view() -> None:
    runtime = RustRuntimeSession("evidence-slot-mutation")
    transition = runtime.execute_read_transition(
        "read", {"path": "sealed"}, _identity("sealed dependency"), lambda: 1
    )
    manifest = _manifest(transition.receipt)
    accumulator = _accumulator(
        "slot-mutation", max_cases=1, authorization_manifest=manifest
    )
    accumulator.record_runtime_case(transition.receipt)
    summary, receipt = _seal(accumulator)
    expected_summary = summary.canonical_record()
    expected_receipt = receipt.canonical_record()

    # Cached Python projections are never authority: every public property is
    # re-derived from the exact native-sealed canonical record.
    object.__setattr__(summary, "_aggregates", {"inputs": _identity("forged")})
    object.__setattr__(summary, "_bound", {"task": _identity("forged")})
    object.__setattr__(summary, "_case_counts", None)
    object.__setattr__(summary, "_counters", None)
    object.__setattr__(summary, "_case_record_count", MAX_U64)
    object.__setattr__(summary, "_child_receipt_count", MAX_U64)
    object.__setattr__(summary, "_authorization_manifest_count", MAX_U64)
    object.__setattr__(summary, "_authorization_manifest_identity", _identity("forged"))
    object.__setattr__(summary, "_runtime_boundary", None)
    assert summary.aggregate_input_identity == expected_summary[
        "aggregate_identities"
    ]["inputs"]
    assert summary.task_identity == expected_summary["bound_identities"]["task"]
    assert summary.case_record_count == 1
    assert summary.child_receipt_count == 0
    assert summary.case_counts.total == 1
    assert summary.counter_totals.requests == 1
    assert summary.authorization_manifest_count == 1
    assert summary.authorization_manifest_identity == expected_summary[
        "authorization_manifest"
    ]["manifest_id"]
    assert summary.runtime_session_id == expected_summary["runtime_boundary"]["session_id"]
    assert summary.source_bound

    object.__setattr__(receipt, "_aggregates", {"inputs": _identity("forged")})
    object.__setattr__(receipt, "_bound", {"execution": _identity("forged")})
    object.__setattr__(receipt, "_case_counts", None)
    object.__setattr__(receipt, "_counters", None)
    object.__setattr__(receipt, "_case_record_count", MAX_U64)
    object.__setattr__(receipt, "_child_receipt_count", MAX_U64)
    object.__setattr__(receipt, "_authorization_manifest_count", MAX_U64)
    object.__setattr__(receipt, "_authorization_manifest_identity", _identity("forged"))
    object.__setattr__(receipt, "_runtime_boundary", None)
    assert receipt.aggregate_input_identity == expected_receipt[
        "aggregate_identities"
    ]["inputs"]
    assert receipt.execution_identity == expected_receipt["bound_identities"]["execution"]
    assert receipt.case_record_count == 1
    assert receipt.child_receipt_count == 0
    assert receipt.case_counts.total == 1
    assert receipt.counter_totals.requests == 1
    assert receipt.authorization_manifest_count == 1
    assert receipt.authorization_manifest_identity == expected_receipt[
        "authorization_manifest"
    ]["manifest_id"]
    assert receipt.runtime_session_id == expected_receipt["runtime_boundary"]["session_id"]
    assert receipt.source_bound

    structural_endpoint = RuntimeReceipt(transition.receipt.canonical_record())
    object.__setattr__(summary, "_first_runtime_receipt", structural_endpoint)
    assert not summary.source_bound
    with pytest.raises(ValueError, match="endpoint"):
        _ = summary.first_runtime_receipt

    forged_record = receipt.canonical_record()
    forged_record["bound_identities"]["execution"] = _identity(
        "forged execution"
    )
    forged_record.pop("receipt_id")
    forged_record["receipt_id"] = domain_fingerprint(
        "ibae.compact-evidence-receipt.v1", forged_record
    )
    object.__setattr__(receipt, "_record", CanonicalValue.from_value(forged_record))
    assert not receipt.source_bound
    with pytest.raises(ValueError, match="seal"):
        accumulator.finalize(expected_receipt["bound_identities"]["execution"])


def test_large_structural_stream_has_constant_bounded_success_shape() -> None:
    small = _accumulator("same", max_cases=20_000)
    _record(small, 0)
    _, one = _seal(small)

    many = _accumulator("same", max_cases=20_000)
    for index in range(20_000):
        _record(many, index)
    summary, receipt = _seal(many)

    assert summary.case_counts.total == 20_000
    assert receipt.case_counts.passed == 20_000
    assert not receipt.source_bound  # synthetic IDs are structural evidence only
    assert len(one.canonical_text.encode("utf-8")) <= MAX_COMPACT_EVIDENCE_BYTES
    assert len(receipt.canonical_text.encode("utf-8")) <= MAX_COMPACT_EVIDENCE_BYTES
    assert "details" not in receipt.canonical_record()
    assert "timestamp" not in receipt.canonical_text
    assert receipt.canonical_record()["failure_summary"] == {
        "count": 0,
        "details_available": 0,
        "details_truncated": False,
        "first_index": None,
    }


def test_order_is_identity_bearing_for_effect_occurrences() -> None:
    left = _accumulator("ordered", max_cases=2)
    _record(left, 1)
    _record(left, 2)
    _, left_receipt = _seal(left)

    right = _accumulator("ordered", max_cases=2)
    _record(right, 2)
    _record(right, 1)
    _, right_receipt = _seal(right)

    assert (
        left_receipt.aggregate_admission_identity
        != right_receipt.aggregate_admission_identity
    )
    assert left_receipt.aggregate_input_identity != right_receipt.aggregate_input_identity
    assert left_receipt.aggregate_result_identity != right_receipt.aggregate_result_identity
    assert left_receipt.aggregate_receipt_identity != right_receipt.aggregate_receipt_identity
    assert left_receipt.receipt_id != right_receipt.receipt_id


def test_failure_tracking_and_expansion_are_exact_bounded_and_parent_bound() -> None:
    accumulator = _accumulator("failure", max_cases=8, max_failure_details=2)
    _record(accumulator, 0)
    for index in range(1, 6):
        _record(accumulator, index, status="failed")
    _, receipt = _seal(accumulator)
    summary = receipt.canonical_record()["failure_summary"]
    assert receipt.status == "complete_with_failures"
    assert receipt.failure_count == 5
    assert summary == {
        "count": 5,
        "details_available": 2,
        "details_truncated": True,
        "first_index": 1,
    }

    expansion = accumulator.expand(
        evidence_receipt_id=receipt.receipt_id,
        start_case_index=0,
        max_details=2,
    )
    assert expansion.evidence_receipt_id == receipt.receipt_id
    assert [detail["case_index"] for detail in expansion.details] == [1, 2]
    assert all(detail["status"] == "failed" for detail in expansion.details)
    assert all(detail["status"] != "passed" for detail in expansion.details)

    before = receipt.canonical_text
    with pytest.raises(ValueError, match="parent"):
        accumulator.expand(
            evidence_receipt_id=_identity("wrong parent"),
            max_details=1,
        )
    assert accumulator.finalize(receipt.execution_identity).canonical_text == before
    with pytest.raises(ValueError, match="range"):
        accumulator.expand(
            evidence_receipt_id=receipt.receipt_id,
            max_details=3,
        )


def test_counter_overflow_rejects_atomically() -> None:
    overflow = _accumulator("overflow", max_cases=2)
    _record(
        overflow,
        0,
        counters=EvidenceCounters(requests=MAX_U64),
    )
    with pytest.raises(ValueError, match="overflow"):
        _record(overflow, 1, counters=EvidenceCounters(requests=1))
    _, recovered = _seal(overflow)

    clean = _accumulator("overflow", max_cases=2)
    _record(clean, 0, counters=EvidenceCounters(requests=MAX_U64))
    _, expected = _seal(clean)
    assert recovered.canonical_text == expected.canonical_text


def test_unknown_and_oversize_items_fail_closed_without_state_change() -> None:
    from ibae._runtime import NativeEvidenceAccumulator

    ids = [_identity(["native", index]) for index in range(3)]
    native = NativeEvidenceAccumulator(*ids, "[]", 1, 1, False)
    with pytest.raises(ValueError):
        native.ingest_structural('{"item_type":"unknown"}')
    oversize = json.dumps(
        {"item_type": "case", "padding": "x" * 17_000},
        sort_keys=True,
        separators=(",", ":"),
    )
    with pytest.raises(ValueError, match="byte limit"):
        native.ingest_structural(oversize)

    valid = _accumulator("native-valid", max_cases=1)
    # Compare through facade-level rejected-then-valid against a clean reducer.
    with pytest.raises(ValueError):
        valid.record_case(
            case_id=_identity("bad"),
            input_identity=_identity("bad input"),
            result_identity=_identity("bad result"),
            receipt_identity=_identity("bad receipt"),
            status="failed",
            failure_reason="oversize",
            failure_detail="x" * 5_000,
        )
    _record(valid, 0)
    _, recovered = _seal(valid)
    clean = _accumulator("native-valid", max_cases=1)
    _record(clean, 0)
    _, expected = _seal(clean)
    assert recovered.canonical_text == expected.canonical_text


def test_structural_self_consistent_receipt_cannot_bind_parent() -> None:
    child = _accumulator("child-source", max_cases=1)
    _record(child, 0)
    _, live = _seal(child)
    assert not live.source_bound
    structural = CompactEvidenceReceipt.from_record(live.canonical_record())
    assert structural.receipt_id == live.receipt_id
    assert not structural.source_bound

    parent = _accumulator("parent-source", max_cases=1)
    with pytest.raises(ValueError, match="structural-only"):
        parent.ingest_child(structural)


def test_source_bound_child_composes_but_hierarchy_stays_explicit() -> None:
    runtime = RustRuntimeSession("evidence-child-runtime")
    transition = runtime.execute_read_transition(
        "read", {"path": "child"}, _identity("dep"), lambda: 1
    )
    manifest = _manifest(transition.receipt)
    child = _accumulator(
        "bound-hierarchy", max_cases=1, authorization_manifest=manifest
    )
    child.record_runtime_case(transition.receipt)
    _, child_receipt = _seal(child, "child execution")
    assert child_receipt.source_bound

    parent = _accumulator(
        "bound-hierarchy", max_cases=1, authorization_manifest=manifest
    )
    parent.ingest_child(child_receipt)
    _, parent_receipt = _seal(parent, "parent execution")
    assert parent_receipt.source_bound
    assert parent_receipt.case_record_count == 0
    assert parent_receipt.child_receipt_count == 1
    assert parent_receipt.execution_identity != parent_receipt.receipt_id
    # v1 final governance can require child_receipt_count == 0 because ordered
    # hierarchical transport roots are grouping-sensitive.


def test_cross_context_child_rejects_without_mutating_parent() -> None:
    runtime = RustRuntimeSession("cross-context-child")
    transition = runtime.execute_read_transition(
        "read", {"path": "child"}, _identity("dep"), lambda: 1
    )
    manifest = _manifest(transition.receipt)
    child = _accumulator(
        "child-context", max_cases=1, authorization_manifest=manifest
    )
    child.record_runtime_case(transition.receipt)
    _, child_receipt = _seal(child)

    rejected_then_valid = _accumulator("parent-context", max_cases=1)
    with pytest.raises(ValueError, match="authority context"):
        rejected_then_valid.ingest_child(child_receipt)
    _record(rejected_then_valid, 0)
    _, recovered = _seal(rejected_then_valid)

    clean = _accumulator("parent-context", max_cases=1)
    _record(clean, 0)
    _, expected = _seal(clean)
    assert recovered.canonical_text == expected.canonical_text


def test_cross_manifest_child_rejects_without_mutating_parent() -> None:
    dependency = _identity("cross-manifest dependency")
    child_runtime = RustRuntimeSession("cross-manifest-child")
    child_transition = child_runtime.execute_read_transition(
        "read", {"path": "child"}, dependency, lambda: 1
    )
    child_manifest = _manifest(child_transition.receipt)
    child = _accumulator(
        "same-context", max_cases=1, authorization_manifest=child_manifest
    )
    child.record_runtime_case(child_transition.receipt)
    _, child_receipt = _seal(child)

    parent_runtime = RustRuntimeSession("cross-manifest-parent")
    parent_transition = parent_runtime.execute_read_transition(
        "read", {"path": "parent"}, dependency, lambda: 2
    )
    parent_manifest = _manifest(parent_transition.receipt)
    guarded = _accumulator(
        "same-context", max_cases=1, authorization_manifest=parent_manifest
    )
    with pytest.raises(ValueError, match="authorization manifest"):
        guarded.ingest_child(child_receipt)
    guarded.record_runtime_case(parent_transition.receipt)
    _, recovered = _seal(guarded)

    clean = _accumulator(
        "same-context", max_cases=1, authorization_manifest=parent_manifest
    )
    clean.record_runtime_case(parent_transition.receipt)
    _, expected = _seal(clean)
    assert recovered.canonical_text == expected.canonical_text


def test_runtime_source_session_and_state_continuity_fail_closed() -> None:
    dependency = _identity("continuity dependency")
    runtime = RustRuntimeSession("continuity-a")
    first = runtime.execute_read_transition(
        "read", {"path": "a"}, dependency, lambda: 1
    )
    second = runtime.execute_read_transition(
        "read", {"path": "b"}, dependency, lambda: 2
    )
    other_runtime = RustRuntimeSession("continuity-b")
    other = other_runtime.execute_read_transition(
        "read", {"path": "a"}, dependency, lambda: 1
    )

    manifest = _manifest(first.receipt, second.receipt, other.receipt)
    guarded = _accumulator(
        "continuity", max_cases=2, authorization_manifest=manifest
    )
    guarded.record_runtime_case(first.receipt)
    with pytest.raises(ValueError, match="session"):
        guarded.record_runtime_case(other.receipt)
    with pytest.raises(ValueError, match="continuity"):
        guarded.record_runtime_case(first.receipt)
    guarded.record_runtime_case(second.receipt)
    guarded_summary, guarded_receipt = _seal(guarded)

    clean = _accumulator(
        "continuity", max_cases=2, authorization_manifest=manifest
    )
    clean.record_runtime_case(first.receipt)
    clean.record_runtime_case(second.receipt)
    clean_summary, clean_receipt = _seal(clean)
    assert guarded_receipt.canonical_text == clean_receipt.canonical_text
    assert guarded_summary.first_runtime_receipt is first.receipt
    assert guarded_summary.last_runtime_receipt is second.receipt
    assert guarded_summary.initial_runtime_state_id == first.receipt.canonical_record()[
        "prior_state_id"
    ]
    assert guarded_summary.final_runtime_state_id == second.receipt.canonical_record()[
        "resulting_state_id"
    ]
    assert clean_summary.summary_id == guarded_summary.summary_id


def test_runtime_retry_is_sealed_counted_and_continuous() -> None:
    runtime = RustRuntimeSession("evidence-retry")
    dependency = _identity("retry dependency")
    admission = _identity("retry governed action")
    first = runtime.execute_read_transition(
        "read", {"path": "retry"}, dependency, lambda: {"value": 1},
        admission_id=admission,
    )
    retry = runtime.record_retry_transition(admission_id=admission)
    cached = runtime.execute_read_transition(
        "read", {"path": "retry"}, dependency, lambda: {"value": 2},
        admission_id=admission,
    )
    accumulator = _accumulator(
        "retry",
        max_cases=3,
        authorization_manifest=_manifest(first.receipt),
    )
    accumulator.record_runtime_case(first.receipt)
    accumulator.record_runtime_case(retry.receipt)
    accumulator.record_runtime_case(cached.receipt)
    summary, receipt = _seal(accumulator)

    assert summary.source_bound and receipt.source_bound
    assert receipt.case_counts.total == 3
    assert receipt.counter_totals.requests == 2
    assert receipt.counter_totals.actual_executions == 1
    assert receipt.counter_totals.cache_hits == 1
    assert receipt.counter_totals.retries == 1
    assert receipt.aggregate_admission_identity == aggregate_admission_stream(
        [admission, admission, admission]
    )
    assert summary.first_runtime_receipt is first.receipt
    assert summary.last_runtime_receipt is cached.receipt


def test_retry_alone_cannot_satisfy_manifest_coverage() -> None:
    runtime = RustRuntimeSession("retry-only")
    admission = _identity("retry-only governed action")
    read = runtime.execute_read_transition(
        "read", {"path": "retry-only"}, _identity("retry-only dependency"),
        lambda: 1, admission_id=admission,
    )
    retry = runtime.record_retry_transition(admission_id=admission)
    accumulator = _accumulator(
        "retry-only",
        max_cases=1,
        authorization_manifest=_manifest(read.receipt),
    )
    accumulator.record_runtime_case(retry.receipt)
    with pytest.raises(ValueError, match="authorized runtime action"):
        accumulator.aggregate_summary()
    with pytest.raises(ValueError, match="aggregate_summary"):
        accumulator.finalize(_identity("retry-only execution"))


def test_unknown_retry_admission_rejects_without_evidence_mutation() -> None:
    runtime = RustRuntimeSession("retry-unknown")
    admission = _identity("known retry action")
    first = runtime.execute_read_transition(
        "read", {"path": "known"}, _identity("known dependency"), lambda: 1,
        admission_id=admission,
    )
    unknown_retry = runtime.record_retry_transition(
        admission_id=_identity("unknown retry action")
    )
    manifest = _manifest(first.receipt)
    guarded = _accumulator(
        "retry-unknown", max_cases=2, authorization_manifest=manifest
    )
    guarded.record_runtime_case(first.receipt)
    with pytest.raises(ValueError, match="authorization manifest"):
        guarded.record_runtime_case(unknown_retry.receipt)
    _, guarded_receipt = _seal(guarded)

    clean = _accumulator(
        "retry-unknown", max_cases=2, authorization_manifest=manifest
    )
    clean.record_runtime_case(first.receipt)
    _, clean_receipt = _seal(clean)
    assert guarded_receipt.canonical_text == clean_receipt.canonical_text


def test_fast_fold_is_separate_observational_data_and_never_changes_receipt() -> None:
    with_fold = _accumulator("fold", max_cases=2, fold=True)
    without_fold = _accumulator("fold", max_cases=2, fold=False)
    for index in range(2):
        _record(with_fold, index)
        _record(without_fold, index)
    _, folded_receipt = _seal(with_fold)
    _, plain_receipt = _seal(without_fold)
    observation = with_fold.fast_regression_observation()

    assert folded_receipt.canonical_text == plain_receipt.canonical_text
    assert observation is not None
    assert observation.correctness_authority is False
    assert len(observation.value) == 16
    assert without_fold.fast_regression_observation() is None
    assert "fast_fold" not in folded_receipt.canonical_record()
    assert observation.value not in folded_receipt.receipt_id


def test_tampering_and_unknown_profile_fail_closed() -> None:
    accumulator = _accumulator("tamper", max_cases=1)
    _record(accumulator, 0)
    _, receipt = _seal(accumulator)
    tampered = receipt.canonical_record()
    tampered["case_counts"]["passed"] = 0
    with pytest.raises(ValueError, match="identity"):
        CompactEvidenceReceipt.from_record(tampered)
    with pytest.raises(ValueError, match="unsupported required"):
        CompactEvidenceReceipt.from_json(
            receipt.canonical_text,
            required_profile="IBAE-COMPACT-EVIDENCE-EVERYTHING-V1",
        )

    self_consistent = receipt.canonical_record()
    self_consistent["case_counts"]["passed"] = 0
    self_consistent["case_counts"]["failed"] = 1
    self_consistent["failure_summary"] = {
        "count": 1,
        "details_available": 1,
        "details_truncated": False,
        "first_index": 0,
    }
    self_consistent["status"] = "complete_with_failures"
    self_consistent.pop("receipt_id")
    self_consistent["receipt_id"] = domain_fingerprint(
        "ibae.compact-evidence-receipt.v1", self_consistent
    )
    parsed = CompactEvidenceReceipt.from_record(self_consistent)
    assert not parsed.source_bound
    assert parsed.verification_scope == "structural_schema_and_identity_only"


def test_seal_prevents_late_ingestion_and_rebinding() -> None:
    accumulator = _accumulator("seal", max_cases=2)
    _record(accumulator, 0)
    summary = accumulator.aggregate_summary()
    with pytest.raises(ValueError, match="sealed"):
        _record(accumulator, 1)
    execution = _identity(summary.summary_id)
    receipt = accumulator.finalize(execution)
    assert accumulator.finalize(execution).receipt_id == receipt.receipt_id
    with pytest.raises(ValueError, match="another execution"):
        accumulator.finalize(_identity("different execution"))
