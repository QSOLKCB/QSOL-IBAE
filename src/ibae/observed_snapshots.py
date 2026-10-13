"""Immutable observed-content consumption, separate from live GET capture.

A public constructor or serialized snapshot establishes only bounded immutable
content. It cannot establish that a live source was contacted. Actual capture
provenance belongs to the activation controller's owned exact adapter operation.

``read.observed_snapshot`` reads the selected captured record, never current
remote state. Its content-bound cacheability does not make the source GET
cacheable, authenticate the remote producer, or authorize a native operation.
The closed parity probe below separately admits this exact immutable read and
uses unchanged native accounting and source-bound compact evidence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final

from ._records import bounded_utf8_length
from .canonical import canonical_json, canonical_tool_key, domain_fingerprint
from .epistemic import EpistemicClass, EpistemicRecord, EpistemicState, ObservationProvenance
from .readonly_adapters import ExternalObservationReceipt
from .synthetic_protocol import (
    AdapterInterface, FakeReadUniverse, NormalizedProposal, ProposalKind,
    SyntheticReadFixture, _copy_json, _exact, _fields, _fingerprint,
)

OBSERVED_SNAPSHOT_VERSION: Final = "IBAE-OBSERVED-SNAPSHOT-V1"
SNAPSHOT_READ_ADAPTER_VERSION: Final = "IBAE-OBSERVED-SNAPSHOT-READ-ADAPTER-V1"
SNAPSHOT_EQUIVALENCE_VERSION: Final = "IBAE-OBSERVED-SNAPSHOT-EQUIVALENCE-V1"
SNAPSHOT_TOOL_NAME: Final = "read.observed_snapshot"
MAX_OBSERVED_SNAPSHOTS: Final = 16
# Leave headroom for the existing 65,536-byte synthetic fixture envelope.
MAX_OBSERVED_SNAPSHOT_BYTES: Final = 60_000
MAX_SNAPSHOT_SET_BYTES: Final = 1_048_576
MAX_SNAPSHOT_REPORT_BYTES: Final = 8_192


def _snapshot_record(record: Any) -> dict:
    value = _copy_json(record, limit=MAX_OBSERVED_SNAPSHOT_BYTES, node_limit=16_384)
    _fields(value, {"protocol_version", "source_receipt", "source_receipt_id", "content_immutable",
        "consumption_scope", "live_capture_verified", "current_remote_state_verified",
        "remote_producer_authenticated", "native_authority"}, "observed snapshot")
    if (value["protocol_version"] != OBSERVED_SNAPSHOT_VERSION or value["content_immutable"] is not True
            or value["consumption_scope"] != "exact_retained_observation_content"
            or value["live_capture_verified"] is not False or value["current_remote_state_verified"] is not False
            or value["remote_producer_authenticated"] is not False or value["native_authority"] is not False):
        raise ValueError("invalid observed snapshot scope, version or authority")
    ExternalObservationReceipt.from_record(value["source_receipt"])
    _fingerprint("source receipt identity", value["source_receipt_id"])
    receipt_id = domain_fingerprint("ibae.external-read-observation-receipt-id.v1", value["source_receipt"])
    if value["source_receipt_id"] != receipt_id:
        raise ValueError("snapshot source receipt identity does not match its content")
    return value


@dataclass(frozen=True, slots=True, init=False)
class ObservedReadSnapshot:
    """Unverified frozen content; reconstruction never supplies live provenance."""

    _text: str

    def __init__(self, source_receipt: ExternalObservationReceipt) -> None:
        _exact("snapshot source receipt", source_receipt, ExternalObservationReceipt)
        source = source_receipt.canonical_record()
        value = _snapshot_record({"protocol_version": OBSERVED_SNAPSHOT_VERSION,
            "source_receipt": source,
            "source_receipt_id": domain_fingerprint("ibae.external-read-observation-receipt-id.v1", source),
            "content_immutable": True, "consumption_scope": "exact_retained_observation_content",
            "live_capture_verified": False, "current_remote_state_verified": False,
            "remote_producer_authenticated": False, "native_authority": False})
        object.__setattr__(self, "_text", canonical_json(value))

    @classmethod
    def from_receipt(cls, source_receipt: ExternalObservationReceipt) -> ObservedReadSnapshot:
        """Freeze supplied content without asserting that it came from a GET."""
        return cls(source_receipt)

    @classmethod
    def from_record(cls, record: dict) -> ObservedReadSnapshot:
        value = _snapshot_record(record)
        # The complete record and nested source have already been validated.
        # Freeze that detached value directly without re-parsing it as input.
        result = object.__new__(cls)
        object.__setattr__(result, "_text", canonical_json(value))
        return result

    def canonical_record(self) -> dict:
        _exact("snapshot text", self._text, str)
        bounded_utf8_length("snapshot text", self._text, limit=MAX_OBSERVED_SNAPSHOT_BYTES)
        return _snapshot_record(json.loads(self._text))

    @property
    def snapshot_id(self) -> str:
        return domain_fingerprint("ibae.observed-read-snapshot-id.v1", self.canonical_record())

    @property
    def source_receipt(self) -> ExternalObservationReceipt:
        return ExternalObservationReceipt.from_record(self.canonical_record()["source_receipt"])

    @property
    def arguments(self) -> dict:
        return {"snapshot_id": self.snapshot_id}

    @property
    def state_key(self) -> str:
        return "snapshot." + self.snapshot_id

    def epistemic_record(self) -> EpistemicRecord:
        """Observe retained local content identity, never remote current truth."""
        identity = self.snapshot_id
        content = domain_fingerprint("ibae.observed-snapshot-content-binding.v1", {"snapshot_id": identity})
        return EpistemicRecord("snapshot." + identity, EpistemicClass.OBSERVED,
            {"snapshot_id": identity, "scope": "retained_content_only"},
            provenance=ObservationProvenance(SNAPSHOT_TOOL_NAME, identity, content))

    @property
    def dependency_fingerprint(self) -> str:
        source = self.epistemic_record()
        return EpistemicState((source,)).dependency_digest((source.key,))

    @property
    def tool_key(self) -> str:
        return canonical_tool_key(SNAPSHOT_TOOL_NAME, self.arguments, self.dependency_fingerprint)


def _snapshots(values: Any, *, nonempty: bool = False) -> tuple[ObservedReadSnapshot, ...]:
    _exact("observed snapshots", values, tuple)
    if len(values) > MAX_OBSERVED_SNAPSHOTS or (nonempty and not values):
        raise ValueError("snapshot set must satisfy its finite sixteen-content bound")
    selected = []
    for item in values:
        _exact("observed snapshot", item, ObservedReadSnapshot)
        selected.append(ObservedReadSnapshot.from_record(item.canonical_record()))
    selected.sort(key=lambda item: item.snapshot_id)
    identities = [item.snapshot_id for item in selected]
    if len(identities) != len(set(identities)):
        raise ValueError("duplicate snapshot identity")
    _copy_json([item.canonical_record() for item in selected], limit=MAX_SNAPSHOT_SET_BYTES, node_limit=65_536)
    return tuple(selected)


@dataclass(frozen=True, slots=True, init=False)
class SnapshotReadAdapter:
    """Closed content-addressed reads; contains no source re-fetch operation."""

    _snapshots: tuple[ObservedReadSnapshot, ...]

    def __init__(self, snapshots: tuple[ObservedReadSnapshot, ...]) -> None:
        object.__setattr__(self, "_snapshots", _snapshots(snapshots))

    def canonical_record(self) -> dict:
        _exact("retained snapshots", self._snapshots, tuple)
        if len(self._snapshots) > MAX_OBSERVED_SNAPSHOTS:
            raise ValueError("snapshot set exceeds its sixteen-content bound")
        records, identities = [], []
        for item in self._snapshots:
            _exact("retained snapshot", item, ObservedReadSnapshot)
            record = item.canonical_record()
            records.append(record)
            identities.append(domain_fingerprint("ibae.observed-read-snapshot-id.v1", record))
        if identities != sorted(set(identities)):
            raise ValueError("snapshot set must retain unique canonical identity order")
        return _copy_json({"protocol_version": SNAPSHOT_READ_ADAPTER_VERSION,
            "snapshots": records, "network_enabled": False,
            "live_capture_verified": False, "control_authority": False},
            limit=MAX_SNAPSHOT_SET_BYTES, node_limit=65_536)

    def lookup(self, tool_name: str, arguments: dict, dependency_fingerprint: str) -> dict:
        _exact("snapshot tool name", tool_name, str)
        if tool_name != SNAPSHOT_TOOL_NAME:
            raise ValueError("only the immutable observed-snapshot read is supported")
        arguments = _copy_json(arguments, limit=1_024)
        _fields(arguments, {"snapshot_id"}, "snapshot read arguments")
        _fingerprint("snapshot identity", arguments["snapshot_id"])
        _fingerprint("snapshot read dependency", dependency_fingerprint)
        values = self.canonical_record()["snapshots"]
        for record in values:
            if domain_fingerprint("ibae.observed-read-snapshot-id.v1", record) == arguments["snapshot_id"]:
                item = ObservedReadSnapshot.from_record(record)
                if item.dependency_fingerprint != dependency_fingerprint:
                    raise LookupError("snapshot read dependency does not match the exact retained content")
                return item.canonical_record()
        raise LookupError("no exact retained observation snapshot")

    def read(self, proposal: NormalizedProposal, dependency_fingerprint: str) -> dict:
        _exact("snapshot proposal", proposal, NormalizedProposal)
        if proposal.kind is not ProposalKind.READ:
            raise ValueError("snapshot consumption requires a normalized read proposal")
        payload = proposal.payload
        return self.lookup(payload["tool_name"], payload["arguments"], dependency_fingerprint)


def _native_probe(snapshots: tuple[ObservedReadSnapshot, ...], *, retained: bool) -> dict:
    """Closed finite proof of immutable consumption, never of source freshness."""
    from .evidence import EvidenceAccumulator, EvidenceLimits
    from .governance import (
        GovernancePolicy, GovernanceWrapper, PrincipalAuthority, ProviderAuthority,
        SUPPORTED_REQUIRED_GATE_KEYS, ToolAuthorityClass, ToolPermission,
    )
    from .obligations import Obligation
    from .orchestration import (
        ActionProposal, Capability, DecisionStatus, OrchestrationState, ProposalBatch,
        ReplaySafety, Strategy, StrategySchema, admit_batch,
    )
    from .runtime import RuntimeLimits, RustRuntimeSession

    count = len(snapshots)
    if not 1 <= count <= MAX_OBSERVED_SNAPSHOTS:
        raise ValueError("native snapshot probe requires a bounded nonempty set")
    fixtures = tuple(SyntheticReadFixture(SNAPSHOT_TOOL_NAME, item.arguments,
        item.dependency_fingerprint, item.canonical_record(), interface=AdapterInterface.READ) for item in snapshots)
    adapter = SnapshotReadAdapter(snapshots) if retained else FakeReadUniverse(fixtures)
    capability = Capability(SNAPSHOT_TOOL_NAME, ReplaySafety.CACHEABLE_READ,
        "Read exact immutable retained content; do not fetch remote state.", semantic_argument_keys=("snapshot_id",))
    schema = StrategySchema("snapshot.consumption", ())
    obligations = tuple(Obligation(f"snapshot.consume.{index}", "Consume an exact captured content record.")
                        for index in range(count))
    state = OrchestrationState.create(obligations,
        epistemic_state=EpistemicState(tuple(item.epistemic_record() for item in snapshots)),
        capabilities=(capability,), strategy_schemas=(schema,))
    proposals = tuple(ActionProposal(f"snapshot.read.{index}", SNAPSHOT_TOOL_NAME, item.arguments,
        target_obligation_ids=(obligations[index].obligation_id,), required_state_keys=(item.state_key,))
        for index, item in enumerate(snapshots))
    batch = ProposalBatch("snapshot.consume", Strategy("snapshot.consumption", {}, schema=schema), proposals)
    admitted = admit_batch(state, batch)
    if len(admitted.receipt.decisions) != count or any(
            item.status is not DecisionStatus.ADMITTED for item in admitted.receipt.decisions):
        raise ValueError("snapshot-consumption admission changed")
    by_proposal = {item.proposal_id: item for item in proposals}
    by_snapshot = {item.snapshot_id: item for item in snapshots}
    policy = GovernancePolicy("snapshot.consumption", 1, "snapshot.consumption", 1,
        ProviderAuthority.OPENAI, (ToolPermission(SNAPSHOT_TOOL_NAME, ToolAuthorityClass.SNAPSHOT_READ, False, True),),
        tuple(SUPPORTED_REQUIRED_GATE_KEYS))
    wrapper = GovernanceWrapper(policy)
    task, governance = wrapper.admit_task("snapshot.consumption",
        {"source_snapshot_ids": [item.snapshot_id for item in snapshots], "scope": "exact_retained_content_only"},
        requester=PrincipalAuthority.OPENAI_SUPERVISOR)
    authorizations = tuple(wrapper.admit_tool(task, governance, decision, by_proposal[decision.proposal_id],
        capability, ToolAuthorityClass.SNAPSHOT_READ,
        dependency_state_id=by_snapshot[by_proposal[decision.proposal_id].arguments["snapshot_id"]].dependency_fingerprint,
        requester=PrincipalAuthority.DETERMINISTIC_ORCHESTRATOR) for decision in admitted.receipt.decisions)
    orchestration = wrapper.bind_orchestration(task, governance, admitted.receipt, authorizations)
    runtime = RustRuntimeSession("snapshot.consumption", RuntimeLimits(
        max_requests=count * 2, max_executions=count, max_retries=1, max_history=max(6, count * 2)))
    evidence = EvidenceAccumulator(task.task_id, governance.governance_id, orchestration.orchestration_id,
        authorization_manifest=orchestration.authorization_manifest,
        limits=EvidenceLimits(max_cases=count * 2, max_failure_details=1))
    receipts, observations = [], []
    for decision in admitted.receipt.decisions:
        proposal = by_proposal[decision.proposal_id]
        snapshot = by_snapshot[proposal.arguments["snapshot_id"]]

        def operation(proposal=proposal, snapshot=snapshot):
            return adapter.lookup(proposal.capability, proposal.arguments, snapshot.dependency_fingerprint)

        # The second request proves reuse of captured bytes, not reuse of live
        # source freshness. Both paths obtain their own native authority.
        for _ in range(2):
            result = runtime.execute_admitted_read(decision, proposal, capability,
                snapshot.dependency_fingerprint, operation)
            if result.receipt.status != "accepted" or canonical_json(result.observation) != canonical_json(snapshot.canonical_record()):
                raise ValueError("native snapshot read differs from exact retained source content")
            evidence.record_runtime_case(result.receipt)
            receipts.append(result.receipt.canonical_record())
            observations.append(domain_fingerprint("ibae.observed-snapshot-consumed-content.v1", result.observation))
    execution = wrapper.bind_execution(task, governance, orchestration, evidence.aggregate_summary())
    compact = evidence.finalize(execution.execution_id)
    if not compact.source_bound:
        raise ValueError("snapshot consumption lacks native source-bound compact evidence")
    counters = runtime.snapshot.canonical_record()["counters"]
    if counters != {"requests": count * 2, "executions": count, "cache_hits": count, "retries": 0}:
        raise ValueError("snapshot native accounting does not match the bounded cold/hit profile")
    return {"task_id": task.task_id, "governance_id": governance.governance_id,
        "admission_receipt_id": admitted.receipt.receipt_id, "orchestration_id": orchestration.orchestration_id,
        "execution_id": execution.execution_id, "native_compact_receipt_id": compact.receipt_id,
        "native_receipt_stream_id": domain_fingerprint("ibae.observed-snapshot-runtime-stream.v1", receipts),
        "native_observation_stream_id": domain_fingerprint("ibae.observed-snapshot-content-stream.v1", observations),
        "native_runtime_state_id": runtime.snapshot.state_id, "native_compact_source_bound": True,
        "counters": counters}


def verify_observed_snapshot_stage(snapshots: tuple[ObservedReadSnapshot, ...]) -> dict:
    """Prove supplied frozen-content parity. This never verifies live capture.

    Two fresh, separately governed native runs consume the same snapshots: one
    through the accepted frozen source and one through SnapshotReadAdapter.
    Only the activation controller can pair this closed result with its own
    actual captured-source provenance. This function has no transport callback.
    """
    selected = _snapshots(snapshots, nonempty=True)
    frozen = _native_probe(selected, retained=False)
    retained = _native_probe(selected, retained=True)
    if canonical_json(frozen) != canonical_json(retained):
        raise ValueError("snapshot source/native consumption parity failed")
    record = {"protocol_version": SNAPSHOT_EQUIVALENCE_VERSION,
        "source_snapshot_ids": [item.snapshot_id for item in selected],
        "snapshot_count": len(selected), "equivalent": True, "live_verification": False,
        "current_remote_state_verified": False, "remote_producer_authenticated": False,
        "final_acceptance": False, "transport_calls": 0,
        "scope": "exact_retained_content_native_consumption", "fresh_native_runs": 2,
        "native_total_counters": {key: value * 2 for key, value in retained["counters"].items()},
        "native_proof": retained}
    record["report_id"] = domain_fingerprint("ibae.observed-snapshot-equivalence-report.v1", record)
    return _copy_json(record, limit=MAX_SNAPSHOT_REPORT_BYTES)


def verify_snapshot_native_equivalence(snapshots: tuple[ObservedReadSnapshot, ...]) -> dict:
    """Compatibility spelling for the same closed, non-live parity probe."""
    return verify_observed_snapshot_stage(snapshots)
