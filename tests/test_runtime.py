from __future__ import annotations

import dataclasses
import time
import tomllib
from collections import OrderedDict
from pathlib import Path

import pytest

from ibae import (
    ActionProposal,
    AdmissionDecision,
    BudgetExceeded,
    BudgetLimits,
    Capability,
    DecisionStatus,
    InvariantExecutor,
    ReplaySafety,
    RuntimeLimits,
    RuntimeRejected,
    RustRuntimeSession,
    canonical_fingerprint,
    canonical_json,
    canonical_tool_key,
    domain_fingerprint,
    rust_canonical_json,
)
from ibae._records import (
    CanonicalRuntimeRecord,
    CanonicalValue,
    MAX_CANONICAL_VALUE_BYTES,
    MAX_RUNTIME_RECORD_BYTES,
)
from ibae.reference_executor import PythonReferenceExecutor
from ibae.runtime import RUNTIME_PROTOCOL_VERSION

DEP_A = canonical_fingerprint({"dependency": "a"})
DEP_B = canonical_fingerprint({"dependency": "b"})
ADMISSION = canonical_fingerprint({"admission": "test"})


def _metrics(runtime: RustRuntimeSession) -> dict[str, int]:
    snapshot = runtime.snapshot
    return {
        "cache_hits": snapshot.cache_hits,
        "executions": snapshot.executions,
        "requests": snapshot.requests,
        "retries": snapshot.retries,
    }


@pytest.mark.parametrize(
    "value",
    [
        {},
        [],
        {"z": 0, "a": {"雪": [None, True, "λ🚀"]}},
        (1 << 256) - 1,
        -((1 << 256) - 1),
        1.0,
        -0.0,
        0.0001,
        1e-5,
        1e16,
        [DEP_A, {"dependency_fingerprint": DEP_B}],
    ],
)
def test_python_and_rust_canonical_bytes_and_sha_match(value: object) -> None:
    python_bytes = CanonicalValue.from_value(value).text
    rust_bytes = rust_canonical_json(python_bytes)
    assert rust_bytes == python_bytes
    assert canonical_fingerprint(value) == canonical_fingerprint(
        CanonicalValue(rust_bytes).to_value()
    )


@pytest.mark.parametrize(
    "raw",
    [
        '{"b":1,"a":2}',
        '{"a": 1}',
        '{"a":1,"a":1}',
        "1e0",
        "-0",
        "NaN",
        "Infinity",
        "115792089237316195423570985008687907853269984665640564039457584007913129639936",
    ],
)
def test_rust_rejects_invalid_or_noncanonical_json(raw: str) -> None:
    with pytest.raises(ValueError):
        rust_canonical_json(raw)


def test_python_keeps_unsupported_mapping_keys_outside_protocol() -> None:
    with pytest.raises(TypeError):
        CanonicalValue.from_value({1: "not admitted"})


def test_rust_rejects_oversize_protocol_text() -> None:
    with pytest.raises(ValueError):
        rust_canonical_json('"' + ("x" * MAX_CANONICAL_VALUE_BYTES) + '"')


def test_repeated_immutable_read_has_exact_accounting_and_ticks() -> None:
    runtime = RustRuntimeSession("repeated")
    calls = 0
    receipts = []

    def operation() -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"value": 42}

    for _ in range(3):
        transition = runtime.execute_read_transition(
            "read", {"path": "x"}, DEP_A, operation
        )
        receipts.append(transition.receipt.canonical_record())
        assert transition.observation == {"value": 42}

    assert calls == 1
    assert _metrics(runtime) == {
        "cache_hits": 2,
        "executions": 1,
        "requests": 3,
        "retries": 0,
    }
    assert receipts[0]["cache_status"] == "cold_execution"
    assert receipts[0]["logical_tick_delta"] == 3
    assert [item["cache_status"] for item in receipts[1:]] == [
        "cache_hit",
        "cache_hit",
    ]
    assert [item["logical_tick_delta"] for item in receipts[1:]] == [2, 2]
    assert len({item["command_id"] for item in receipts}) == 3


def test_rust_matches_merged_python_reference_for_repeated_reads() -> None:
    python = PythonReferenceExecutor()
    rust = RustRuntimeSession("reference-repeated")
    python_calls = 0
    rust_calls = 0

    def python_operation() -> dict[str, int]:
        nonlocal python_calls
        python_calls += 1
        return {"value": 42}

    def rust_operation() -> dict[str, int]:
        nonlocal rust_calls
        rust_calls += 1
        return {"value": 42}

    for _ in range(3):
        assert python.execute_read("read", {"path": "x"}, DEP_A, python_operation) == (
            rust.execute_read("read", {"path": "x"}, DEP_A, rust_operation)
        )

    assert python_calls == rust_calls == 1
    assert python.metrics() == _metrics(rust)
    assert python.state.history == rust.snapshot.history


def test_dependency_identity_invalidates_cache() -> None:
    runtime = RustRuntimeSession("dependency")
    calls = 0

    def operation() -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"call": calls}

    assert runtime.execute_read("read", {"path": "x"}, DEP_A, operation) == {
        "call": 1
    }
    assert runtime.execute_read("read", {"path": "x"}, DEP_B, operation) == {
        "call": 2
    }
    assert calls == 2
    assert runtime.snapshot.executions == 2


def test_invalid_observation_is_rejected_before_cache_insertion() -> None:
    runtime = RustRuntimeSession("invalid-observation")
    calls = 0

    def invalid_then_valid() -> object:
        nonlocal calls
        calls += 1
        return float("nan") if calls == 1 else {"valid": True}

    with pytest.raises(RuntimeRejected) as rejected:
        runtime.execute_read("read", {"path": "x"}, DEP_A, invalid_then_valid)
    assert rejected.value.receipt.rejection_reason == (
        "IBAE-RT-REJECT-INVALID-OBSERVATION"
    )
    assert rejected.value.receipt.canonical_record()["rejection"][
        "invariant_ids"
    ] == ["IBAE-REUSE-004", "IBAE-RT-005"]
    assert runtime.snapshot.cache == ()
    assert runtime.execute_read(
        "read", {"path": "x"}, DEP_A, invalid_then_valid
    ) == {"valid": True}
    assert calls == 2
    assert runtime.snapshot.cache_hits == 0


@pytest.mark.parametrize(
    "value",
    [
        (1, 2),
        {"z": 1, "a": 2},
        OrderedDict((("a", 1),)),
    ],
    ids=("tuple", "noncanonical-dict-order", "mapping-subclass"),
)
def test_runtime_rejects_python_forms_json_cannot_round_trip_exactly(
    value: object,
) -> None:
    runtime = RustRuntimeSession("exact-json-observation")
    with pytest.raises(RuntimeRejected) as rejected:
        runtime.execute_read("read", {}, DEP_A, lambda: value)
    assert rejected.value.receipt.rejection_reason == (
        "IBAE-RT-REJECT-INVALID-OBSERVATION"
    )
    assert runtime.snapshot.cache == ()


def test_maximum_admitted_observation_fits_complete_runtime_outcome() -> None:
    runtime = RustRuntimeSession("maximum-observation-envelope")
    text = "x" * 65_500
    observation = {key: text for key in ("a", "b", "c", "d")}
    assert len(canonical_json(observation).encode("utf-8")) < (
        MAX_CANONICAL_VALUE_BYTES
    )
    transition = runtime.execute_read_transition(
        "read", {"path": "large"}, DEP_A, lambda: observation
    )
    assert transition.receipt.status == "accepted"
    assert transition.observation == observation
    assert runtime.snapshot.executions == 1


def test_maximum_admitted_depth_survives_runtime_envelope_wrapping() -> None:
    observation: object = 0
    for _ in range(32):
        observation = [observation]
    CanonicalValue.from_value(observation)
    runtime = RustRuntimeSession("maximum-observation-depth")
    transition = runtime.execute_read_transition(
        "read", {"path": "deep"}, DEP_A, lambda: observation
    )
    assert transition.receipt.status == "accepted"
    assert transition.observation == observation
    assert runtime.snapshot.executions == 1


def test_maximum_argument_profiles_survive_command_envelope_wrapping() -> None:
    deep: object = 0
    for _ in range(32):
        deep = [deep]
    text = "x" * 65_500
    near_byte_limit = {key: text for key in ("a", "b", "c", "d")}
    maximum_nodes = [
        {"a": 0, "b": 0, "c": 0} for _ in range(1_023)
    ] + [[[0]]]

    for name, arguments in (
        ("depth", deep),
        ("bytes", near_byte_limit),
        ("nodes", maximum_nodes),
    ):
        CanonicalValue.from_value(arguments)
        runtime = RustRuntimeSession(f"maximum-argument-{name}")
        transition = runtime.execute_read_transition(
            "read", arguments, DEP_A, lambda name=name: {"case": name}
        )
        assert transition.receipt.status == "accepted"
        assert transition.observation == {"case": name}
        assert runtime.snapshot.executions == 1


def test_runtime_output_profile_represents_full_declared_history_shape() -> None:
    record = CanonicalRuntimeRecord.from_value(
        {"history": ["a" * 64] * 4_096}
    )
    assert len(record.text.encode("utf-8")) > MAX_CANONICAL_VALUE_BYTES
    assert len(record.text.encode("utf-8")) < MAX_RUNTIME_RECORD_BYTES
    assert len(record.to_value()["history"]) == 4_096


def test_operation_failure_is_structured_and_not_identity_bearing_text() -> None:
    runtime = RustRuntimeSession("operation-failure")

    def operation() -> object:
        raise RuntimeError(f"unstable object address {object()!r}")

    with pytest.raises(RuntimeRejected) as rejected:
        runtime.execute_read("read", {}, DEP_A, operation)
    record = rejected.value.receipt.canonical_record()
    assert record["rejection"]["reason_code"] == "IBAE-RT-REJECT-OPERATION-FAILED"
    assert "unstable object address" not in canonical_json(record)
    assert runtime.snapshot.cache == ()


def test_caller_mutation_cannot_change_rust_cache() -> None:
    runtime = RustRuntimeSession("mutation")
    result = runtime.execute_read(
        "read", {"path": "x"}, DEP_A, lambda: {"items": [1, 2]}
    )
    result["items"].append(999)
    reused = runtime.execute_read(
        "read", {"path": "x"}, DEP_A, lambda: pytest.fail("must be cached")
    )
    assert reused == {"items": [1, 2]}


def test_request_budget_counts_cache_hits_and_fails_closed() -> None:
    runtime = RustRuntimeSession(
        "request-boundary", RuntimeLimits(max_requests=2, max_executions=2)
    )
    runtime.execute_read("read", {}, DEP_A, lambda: 1)
    runtime.execute_read("read", {}, DEP_A, lambda: pytest.fail("cached"))
    prior = runtime.snapshot
    with pytest.raises(RuntimeRejected) as rejected:
        runtime.execute_read("read", {}, DEP_A, lambda: pytest.fail("bounded"))
    assert rejected.value.receipt.rejection_reason == "IBAE-RT-REJECT-REQUEST-BUDGET"
    assert runtime.snapshot == prior


def test_execution_budget_rejects_before_operation_and_preserves_request() -> None:
    runtime = RustRuntimeSession(
        "execution-boundary", RuntimeLimits(max_requests=3, max_executions=1)
    )
    calls = 0

    def operation() -> int:
        nonlocal calls
        calls += 1
        return calls

    assert runtime.execute_read("read", {"path": "a"}, DEP_A, operation) == 1
    with pytest.raises(RuntimeRejected) as rejected:
        runtime.execute_read("read", {"path": "b"}, DEP_A, operation)
    assert rejected.value.receipt.rejection_reason == (
        "IBAE-RT-REJECT-EXECUTION-BUDGET"
    )
    assert calls == 1
    assert runtime.snapshot.requests == 2
    assert runtime.snapshot.executions == 1


def test_retry_budget_is_exact_and_finite() -> None:
    runtime = RustRuntimeSession("retry-boundary", RuntimeLimits(max_retries=1))
    runtime.record_retry()
    assert runtime.snapshot.retries == 1
    with pytest.raises(RuntimeRejected) as rejected:
        runtime.record_retry()
    assert rejected.value.receipt.rejection_reason == "IBAE-RT-REJECT-RETRY-BUDGET"
    assert runtime.snapshot.retries == 1


def test_history_is_deterministically_bounded() -> None:
    runtime = RustRuntimeSession("history", RuntimeLimits(max_history=2))
    for path in ("a", "b", "c"):
        runtime.execute_read("read", {"path": path}, DEP_A, lambda p=path: p)
    assert len(runtime.snapshot.history) == 2


def test_cache_and_cold_paths_have_same_transition_identity_and_cycle() -> None:
    runtime = RustRuntimeSession("cycle")
    cold = {}
    cached = {}
    for path in ("a", "b"):
        transition = runtime.execute_read_transition(
            "read", {"path": path}, DEP_A, lambda p=path: {"v": p}
        )
        cold[path] = transition.receipt.transition_id
    for path in ("a", "b"):
        transition = runtime.execute_read_transition(
            "read", {"path": path}, DEP_A, lambda: pytest.fail("cached")
        )
        cached[path] = transition.receipt.transition_id
    assert cold == cached
    assert runtime.terminal_cycle_period() == 2


def test_tool_and_transition_identities_match_python_v0_1() -> None:
    runtime = RustRuntimeSession("identity")
    transition = runtime.execute_read_transition(
        "read", {"path": "x"}, DEP_A, lambda: {"value": 42}
    )
    record = transition.receipt.canonical_record()
    tool_key = canonical_tool_key("read", {"path": "x"}, DEP_A)
    observation_id = canonical_fingerprint({"value": 42})
    transition_id = canonical_fingerprint(
        {"observation": observation_id, "tool_key": tool_key}
    )
    assert record["tool_key"] == tool_key
    assert record["observation_id"] == observation_id
    assert record["transition_id"] == transition_id


def test_unsupported_future_command_is_structured_and_state_neutral() -> None:
    runtime = RustRuntimeSession("unsupported")
    prior = runtime.snapshot
    transition = runtime.dispatch_protocol(
        {
            "admission_id": ADMISSION,
            "command_type": "request_lease",
            "protocol_version": RUNTIME_PROTOCOL_VERSION,
        }
    )
    assert transition.receipt.rejection_reason == "IBAE-RT-REJECT-UNSUPPORTED-COMMAND"
    assert runtime.snapshot == prior


def test_distinct_unsupported_commands_have_distinct_bound_receipts() -> None:
    runtime = RustRuntimeSession("unsupported-distinct")
    prior = runtime.snapshot
    records = []
    for command_type in ("request_lease", "finalize"):
        transition = runtime.dispatch_protocol(
            {
                "admission_id": ADMISSION,
                "command_type": command_type,
                "protocol_version": RUNTIME_PROTOCOL_VERSION,
            }
        )
        record = transition.receipt.canonical_record()
        assert record["command_type"] == command_type
        assert record["admission_id"] == ADMISSION
        assert record["command_id"] is not None
        records.append(record)
    assert records[0]["command_id"] != records[1]["command_id"]
    assert records[0]["receipt_id"] != records[1]["receipt_id"]
    assert runtime.snapshot == prior


def test_wrong_protocol_and_noncanonical_command_are_state_neutral() -> None:
    runtime = RustRuntimeSession("bad-protocol")
    prior = runtime.snapshot
    wrong = runtime.dispatch_protocol(
        {
            "admission_id": ADMISSION,
            "command_type": "record_retry",
            "protocol_version": "IBAE-RUNTIME-PROTOCOL-V999",
        }
    )
    assert wrong.receipt.rejection_reason == "IBAE-RT-REJECT-PROTOCOL-VERSION"
    malformed = runtime.dispatch_canonical('{"protocol_version": "bad"}')
    assert malformed.receipt.rejection_reason == (
        "IBAE-RT-REJECT-INVALID-CANONICAL-COMMAND"
    )
    assert runtime.snapshot == prior


def test_native_state_fields_and_cache_cannot_be_mutated_from_python() -> None:
    runtime = RustRuntimeSession("opaque")
    native = object.__getattribute__(runtime, "_RustRuntimeSession__native")
    for name, value in (
        ("requests", 0),
        ("logical_tick", 999),
        ("cache", {"forged": "value"}),
    ):
        with pytest.raises(AttributeError):
            setattr(native, name, value)
    snapshot = runtime.snapshot
    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.requests = 999  # type: ignore[misc]
    assert runtime.snapshot.requests == 0


def test_limits_reject_boolean_negative_and_oversize_counters() -> None:
    with pytest.raises(ValueError):
        RuntimeLimits(max_requests=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        RuntimeLimits(max_executions=-1)
    with pytest.raises(ValueError):
        RuntimeLimits(max_executions=4_097)


def test_effectful_occurrence_cannot_enter_read_cache_path() -> None:
    target = canonical_fingerprint({"obligation": "target"})
    proposal = ActionProposal(
        "write-one",
        "write.patch",
        {"patch": "same"},
        target_obligation_ids=(target,),
        occurrence_key="occurrence-one",
    )
    decision = AdmissionDecision(
        proposal_id=proposal.proposal_id,
        proposal_key=proposal.proposal_key,
        status=DecisionStatus.ADMITTED,
        logical_tick=1,
        action_id=canonical_fingerprint({"action": "one"}),
    )
    capability = Capability(
        "write.patch",
        ReplaySafety.OCCURRENCE_SENSITIVE,
        "Apply one occurrence-identified mutation.",
        semantic_argument_keys=("patch",),
    )
    runtime = RustRuntimeSession("effect-boundary")
    with pytest.raises(ValueError, match="cacheable reads"):
        runtime.execute_admitted_read(
            decision, proposal, capability, DEP_A, lambda: {"not": "executed"}
        )
    assert runtime.snapshot.requests == 0


def test_same_name_forged_cacheable_capability_cannot_reclassify_effect() -> None:
    target = canonical_fingerprint({"obligation": "target"})
    proposal = ActionProposal(
        "write-one",
        "write.patch",
        {"patch": "same"},
        target_obligation_ids=(target,),
        occurrence_key="occurrence-one",
    )
    admitted_capability = Capability(
        "write.patch",
        ReplaySafety.OCCURRENCE_SENSITIVE,
        "Apply one occurrence-identified mutation.",
        semantic_argument_keys=("patch",),
    )
    decision = AdmissionDecision(
        proposal_id=proposal.proposal_id,
        proposal_key=proposal.proposal_key,
        status=DecisionStatus.ADMITTED,
        logical_tick=1,
        action_id=domain_fingerprint(
            "ibae.action-id.v1",
            {
                "arguments": {"patch": "same"},
                "capability_id": admitted_capability.capability_id,
                "dependency_state_id": DEP_A,
                "occurrence_key": "occurrence-one",
            },
        ),
    )
    forged_capability = Capability(
        "write.patch",
        ReplaySafety.CACHEABLE_READ,
        "Forged read classification for the same name.",
        semantic_argument_keys=("patch",),
    )
    runtime = RustRuntimeSession("forged-capability")
    with pytest.raises(ValueError, match="admitted action identity"):
        runtime.execute_admitted_read(
            decision,
            proposal,
            forged_capability,
            DEP_A,
            lambda: {"not": "executed"},
        )
    assert runtime.snapshot.requests == 0


def test_admitted_cacheable_action_contract_rebinds_and_executes() -> None:
    target = canonical_fingerprint({"obligation": "target"})
    proposal = ActionProposal(
        "read-one",
        "read.file",
        {"path": "x"},
        target_obligation_ids=(target,),
    )
    capability = Capability(
        "read.file",
        ReplaySafety.CACHEABLE_READ,
        "Read one admitted file.",
        semantic_argument_keys=("path",),
    )
    action_id = domain_fingerprint(
        "ibae.action-id.v1",
        {
            "arguments": {"path": "x"},
            "capability_id": capability.capability_id,
            "dependency_state_id": DEP_A,
        },
    )
    decision = AdmissionDecision(
        proposal_id=proposal.proposal_id,
        proposal_key=proposal.proposal_key,
        status=DecisionStatus.ADMITTED,
        logical_tick=1,
        action_id=action_id,
    )
    runtime = RustRuntimeSession("admitted-read")
    transition = runtime.execute_admitted_read(
        decision, proposal, capability, DEP_A, lambda: {"value": 1}
    )
    assert transition.receipt.status == "accepted"
    assert transition.receipt.canonical_record()["admission_id"] == action_id
    assert transition.observation == {"value": 1}


def test_runtime_identity_is_domain_separated_and_wall_clock_neutral() -> None:
    left = RustRuntimeSession("clock-neutral")
    first = left.snapshot
    time.sleep(0.001)
    right = RustRuntimeSession("clock-neutral")
    second = right.snapshot
    assert first.state_id == second.state_id
    record = canonical_json(first.canonical_record())
    assert "timestamp" not in record
    assert "wall_clock" not in record
    assert domain_fingerprint("ibae.runtime-state-id.v1", {}) != domain_fingerprint(
        "ibae.runtime-receipt-id.v1", {}
    )


def test_legacy_executor_api_is_now_rust_backed() -> None:
    executor = InvariantExecutor(BudgetLimits(max_requests=2, max_executions=1))
    assert executor.execute_read("read", {}, DEP_A, lambda: 1) == 1
    assert executor.execute_read("read", {}, DEP_A, lambda: 2) == 1
    assert executor.last_receipt is not None
    with pytest.raises(BudgetExceeded):
        executor.execute_read("read", {}, DEP_A, lambda: 3)


def test_rust_crate_uses_the_authoritative_repository_license() -> None:
    manifest = tomllib.loads(Path("rust/Cargo.toml").read_text(encoding="utf-8"))
    package = manifest["package"]
    assert package["license-file"] == "LICENSE"
    assert "license" not in package
    assert Path("rust/LICENSE").read_bytes() == Path("LICENSE").read_bytes()
