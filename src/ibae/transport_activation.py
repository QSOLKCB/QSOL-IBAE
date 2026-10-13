"""Opt-in Python transport controls, not native execution authority.

Only a trusted operator application may create an authorization. These controls
protect against accidental stage skipping, stale calls and unbounded transport;
they are not authentication or a defence against arbitrary Python code changes.
No canonical record can restore this controller or its outstanding reservations.
The native task's grants, epochs, accounting and finalizer remain independent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, Enum
from functools import wraps
import json
from threading import RLock
from typing import Any

from ._records import require_fingerprint, require_symbol
from .canonical import canonical_json, domain_fingerprint
from .supervisor import SupervisorContext, SupervisorProjection, _validate_projection
from .synthetic_protocol import NormalizedProposal, ProposalKind, bounded_synthetic_data

ACTIVATION_VERSION = "IBAE-TRANSPORT-ACTIVATION-V1"
STAGE_OBSERVATION_VERSION = "IBAE-TRANSPORT-STAGE-OBSERVATION-V1"
MAX_TRANSPORT_CALLS = 1_024
MAX_SELECTED_READ_TOOLS = 32
MAX_RETAINED_PROPOSALS = 16
MAX_SELECTED_READ_CAPTURES = 16
MAX_EPOCH = (1 << 64) - 1


class ActivationError(ValueError):
    """A transport control rejected a request before it could proceed."""


class ActivationStage(IntEnum):
    SYNTHETIC = 0
    OPENAI_FAKE_TOOLS = 1
    OPENAI_DETERMINISTIC_READS = 2
    OPENAI_SELECTED_READS = 3


class ToolProfile(str, Enum):
    FAKE = "fake_tools"
    DETERMINISTIC_READONLY = "deterministic_readonly_fixtures"
    SELECTED_READONLY = "selected_readonly_tools"


_PROFILES = {
    ActivationStage.SYNTHETIC: ToolProfile.FAKE,
    ActivationStage.OPENAI_FAKE_TOOLS: ToolProfile.FAKE,
    ActivationStage.OPENAI_DETERMINISTIC_READS: ToolProfile.DETERMINISTIC_READONLY,
    ActivationStage.OPENAI_SELECTED_READS: ToolProfile.SELECTED_READONLY,
}


def _exact(name: str, value: Any, kind: type) -> None:
    if type(value) is not kind:
        raise TypeError(f"{name} must have exact type {kind.__name__}")


def _identity(name: str, value: Any) -> None:
    _exact(name, value, str)
    require_fingerprint(name, value)


def _count(name: str, value: Any, limit: int, *, positive: bool = False) -> None:
    _exact(name, value, int)
    if not (1 if positive else 0) <= value <= limit:
        raise ValueError(f"{name} exceeds its finite bound")


def _tools(value: Any) -> None:
    _exact("selected read tools", value, tuple)
    if len(value) > MAX_SELECTED_READ_TOOLS:
        raise ValueError("selected read tools exceed the finite bound")
    for name in value:
        _exact("selected read tool", name, str)
        require_symbol("selected read tool", name)
    if value != tuple(sorted(set(value))):
        raise ValueError("selected read tools must be unique and canonically ordered")


def _selections(value: Any) -> None:
    _exact("selected read selection identities", value, tuple)
    if len(value) > MAX_SELECTED_READ_TOOLS:
        raise ValueError("selected read selections exceed the finite bound")
    for identity in value:
        _identity("selected read selection identity", identity)
    if value != tuple(sorted(set(value))):
        raise ValueError("selected read selections must be unique and canonically ordered")


def _locked(method):
    """Serialize short control changes, never a network call or native probe."""
    @wraps(method)
    def guarded(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return guarded


@dataclass(frozen=True, slots=True)
class OperatorStageAuthorization:
    """An explicit operator instruction, not proof or model-facing authority.

    The application must obtain operator permission outside the model/data
    plane. An operator label is not authentication. No parser promotes an
    untrusted serialized instruction into this control-plane API.
    """

    stage: ActivationStage
    task_id: str
    governance_id: str
    epoch: int
    operator_key: str
    tool_profile: ToolProfile
    selected_read_tools: tuple[str, ...] = ()
    transport_policy_id: str = field(kw_only=True)
    credential_reference_id: str = field(kw_only=True)
    selected_read_selection_ids: tuple[str, ...] = field(default=(), kw_only=True)

    def __post_init__(self) -> None:
        _exact("activation stage", self.stage, ActivationStage)
        _exact("tool profile", self.tool_profile, ToolProfile)
        _identity("task identity", self.task_id)
        _identity("governance identity", self.governance_id)
        _identity("transport policy identity", self.transport_policy_id)
        _identity("credential reference identity", self.credential_reference_id)
        _count("transport epoch", self.epoch, MAX_EPOCH)
        _exact("operator key", self.operator_key, str)
        require_symbol("operator key", self.operator_key)
        _tools(self.selected_read_tools)
        _selections(self.selected_read_selection_ids)
        if self.stage is ActivationStage.SYNTHETIC:
            raise ValueError("synthetic is the default, not a live activation")
        if self.tool_profile is not _PROFILES[self.stage]:
            raise ValueError("tool profile does not match its activation stage")
        if bool(self.selected_read_tools) != (self.stage is ActivationStage.OPENAI_SELECTED_READS):
            raise ValueError("only stage 3 requires explicitly selected read tools")
        if bool(self.selected_read_selection_ids) != (self.stage is ActivationStage.OPENAI_SELECTED_READS):
            raise ValueError("only stage 3 requires explicitly selected read resource identities")
        if len(self.selected_read_tools) * len(self.selected_read_selection_ids) > MAX_SELECTED_READ_CAPTURES:
            raise ValueError("selected tool/resource coverage exceeds the capture gate bound")

    def canonical_record(self) -> dict:
        self.__post_init__()
        return {"protocol_version": ACTIVATION_VERSION, "stage": int(self.stage),
                "task_id": self.task_id, "governance_id": self.governance_id,
                "epoch": self.epoch, "operator_key": self.operator_key,
                "transport_policy_id": self.transport_policy_id,
                "credential_reference_id": self.credential_reference_id,
                "tool_profile": self.tool_profile.value,
                "selected_read_tools": list(self.selected_read_tools),
                "selected_read_selection_ids": list(self.selected_read_selection_ids),
                "authenticated_operator": False, "grants_native_authority": False}


@dataclass(frozen=True, slots=True, init=False)
class StageObservation:
    """Immutable bounded diagnostic output; never accepted as a gate input."""

    _text: str

    def __init__(self, record: dict) -> None:
        value = bounded_synthetic_data(record, max_bytes=65_536)
        object.__setattr__(self, "_text", canonical_json(value))

    def canonical_record(self) -> dict:
        return json.loads(self._text)

    @property
    def observation_id(self) -> str:
        return domain_fingerprint("ibae.transport-stage-observation.v1", self.canonical_record())


@dataclass(frozen=True, slots=True, init=False, eq=False)
class TransportCallReservation:
    """One controller-owned pending Python call; not a native capability."""

    _owner: Any = field(repr=False)
    epoch: int
    stage: ActivationStage
    task_id: str
    governance_id: str
    transport_policy_id: str
    credential_reference_id: str
    call_index: int
    kind: str
    projection_id: str | None
    tool_name: str | None
    selection_id: str | None
    proposal_id: str | None
    dependency_fingerprint: str | None

    def __init__(self) -> None:
        raise TypeError("transport reservations are issued only by their controller")

    def __reduce__(self):
        raise TypeError("transport reservations cannot be serialized or restored")


class _TransportLedger:
    """Small ordinary Python ledger, shared by dispatch and rollback rehearsal."""

    __slots__ = ("epoch", "used", "limit", "revoked", "pending", "openai_calls", "selected_read_calls")

    def __init__(self, limit: int) -> None:
        self.epoch, self.used, self.limit, self.revoked, self.pending = 0, 0, limit, False, None
        self.openai_calls, self.selected_read_calls = 0, 0

    def reserve(self, owner, stage, task_id, governance_id, kind, projection_id=None,
                tool_name=None, transport_policy_id=None,
                credential_reference_id=None, selection_id=None, proposal_id=None,
                dependency_fingerprint=None) -> TransportCallReservation:
        if self.revoked:
            raise ActivationError("transport activation is revoked")
        if self.pending is not None:
            raise ActivationError("a transport call is already outstanding")
        if self.used >= self.limit:
            raise ActivationError("transport call budget is exhausted")
        reservation = object.__new__(TransportCallReservation)
        values = {"_owner": owner, "epoch": self.epoch, "stage": stage, "task_id": task_id,
                  "governance_id": governance_id, "call_index": self.used,
                  "transport_policy_id": transport_policy_id,
                  "credential_reference_id": credential_reference_id,
                  "kind": kind, "projection_id": projection_id, "tool_name": tool_name}
        values["selection_id"] = selection_id
        values["proposal_id"] = proposal_id
        values["dependency_fingerprint"] = dependency_fingerprint
        for name, value in values.items():
            object.__setattr__(reservation, name, value)
        self.used += 1  # Failed/ambiguous calls never refund or auto-retry.
        if kind == "openai":
            self.openai_calls += 1
        elif kind == "selected_read":
            self.selected_read_calls += 1
        self.pending = reservation
        return reservation

    def check(self, reservation, owner) -> None:
        _exact("transport reservation", reservation, TransportCallReservation)
        if (reservation._owner is not owner or self.pending is not reservation
                or reservation.epoch != self.epoch or self.revoked):
            raise ActivationError("transport reservation is foreign, retired or revoked")

    def retire_epoch(self, *, revoke: bool = False) -> None:
        if self.epoch == MAX_EPOCH:
            # Exhaustion itself must fail closed, never preserve an old permit.
            self.revoked, self.pending = True, None
            raise ActivationError("transport epoch is exhausted")
        self.epoch += 1
        self.pending = None
        self.revoked = self.revoked or revoke


def _rollback_rehearsal() -> dict:
    """Exercise local retirement, not provider cancellation or live recovery."""
    ledger = _TransportLedger(1)
    owner = object()
    reservation = ledger.reserve(owner, ActivationStage.OPENAI_FAKE_TOOLS,
                                 "0" * 64, "1" * 64, "rollback_rehearsal",
                                 transport_policy_id="2" * 64, credential_reference_id="3" * 64)
    ledger.check(reservation, owner)
    before = ledger.used
    ledger.retire_epoch()
    try:
        ledger.check(reservation, owner)
    except ActivationError:
        retired = True
    else:
        raise ActivationError("rollback failed to retire its reservation")
    try:
        ledger.reserve(owner, ActivationStage.OPENAI_FAKE_TOOLS,
                       "0" * 64, "1" * 64, "rollback_rehearsal",
                       transport_policy_id="2" * 64, credential_reference_id="3" * 64)
    except ActivationError:
        exhausted = True
    else:
        raise ActivationError("rollback incorrectly restored transport capacity")
    if ledger.used != before:
        raise ActivationError("rollback changed the consumed call count")
    return {"scope": "isolated_python_transport_ledger", "retired_reservation": retired,
            "exhaustion_preserved": exhausted, "budget_refunded": False,
            "live_recovery_verified": False, "provider_request_cancelled": False}


def _source_binding(projection: dict) -> str:
    """Identity for retained request context, never a native authority proof."""
    return domain_fingerprint("ibae.transport-live-source-binding.v1", {
        "sources": projection["sources"], "authority": projection["decision_surface"]["authority"]})


def _admit_selected_read(context: SupervisorContext, proposal: NormalizedProposal,
                         batch, dependency_fingerprint: str, occurrence_key: str):
    """Recompute existing typed orchestration/governance before any HTTP read.

    This pure helper neither dispatches transport nor marks an observation live.
    The controller separately requires its own live proposal/source lineage.
    """
    from .governance import GovernanceWrapper, PrincipalAuthority, ToolAuthorityClass
    from .obligations import canonical_obligation_id
    from .orchestration import (ActionProposal, Capability, DecisionStatus,
                                ProposalBatch, ProposalOrdering, ReplaySafety, admit_batch)

    _exact("live supervisor context", context, SupervisorContext)
    projection = SupervisorProjection(context).canonical_record()  # Native lineage revalidation.
    _exact("normalized read proposal", proposal, NormalizedProposal)
    _exact("selected read batch", batch, ProposalBatch)
    _identity("selected read dependency", dependency_fingerprint)
    if (proposal.kind is not ProposalKind.READ or len(batch.proposals) != 1
            or batch.ordering is not ProposalOrdering.DECLARED_SEQUENCE):
        raise ActivationError("capture requires one declared-sequence admitted read")
    payload, action = proposal.payload, batch.proposals[0]
    _exact("selected read action", action, ActionProposal)
    if (action.proposal_key != payload["proposal_key"] or action.capability != payload["tool_name"]
            or canonical_json(action.arguments) != canonical_json(payload["arguments"])
            or action.target_obligation_ids != tuple(sorted(canonical_obligation_id(key)
                for key in payload["target_obligation_keys"]))
            or action.occurrence_key != occurrence_key):
        raise ActivationError("capture action differs from the owned read or current occurrence")
    capability = context.orchestration_state.capability(action.capability)
    _exact("selected read capability", capability, Capability)
    if capability.replay_safety is not ReplaySafety.OCCURRENCE_SENSITIVE:
        raise ActivationError("remote HTTP capture is occurrence-sensitive, never cacheable")
    transition = admit_batch(context.orchestration_state, batch)
    decisions = transition.receipt.decisions
    if len(decisions) != 1 or decisions[0].status is not DecisionStatus.ADMITTED:
        raise ActivationError("selected read was not admitted by deterministic orchestration")
    tool_admission = GovernanceWrapper(context.governance_policy).admit_tool(
        context.task, context.governance, decisions[0], action, capability,
        ToolAuthorityClass.VOLATILE_READ, dependency_state_id=dependency_fingerprint,
        requester=PrincipalAuthority.DETERMINISTIC_ORCHESTRATOR,
    )
    return projection, transition, tool_admission


@dataclass(frozen=True, slots=True)
class SelectedReadCapture:
    """Capture and next host state; construction/serialization grants nothing.

    HTTP is accounted by the transport ledger. The returned immutable snapshot
    must receive its own governed native read before native evidence exists.
    """

    snapshot: Any
    next_orchestration_state: Any
    admission_receipt: Any
    tool_admission: Any
    selection_id: str
    proposal_id: str
    epoch: int
    transport_call_index: int
    transport_policy_id: str
    credential_reference_id: str

    def canonical_record(self) -> dict:
        return {"protocol_version": "IBAE-SELECTED-READ-CAPTURE-V1",
            "snapshot_id": self.snapshot.snapshot_id, "source_receipt_id": self.snapshot.source_receipt.receipt_id,
            "next_orchestration_state_id": self.next_orchestration_state.state_id,
            "admission_receipt_id": self.admission_receipt.receipt_id,
            "tool_admission_receipt_id": self.tool_admission.receipt_id,
            "task_id": self.tool_admission.task_id, "governance_id": self.tool_admission.governance_id,
            "tool_name": self.tool_admission.tool_name, "selection_id": self.selection_id,
            "proposal_id": self.proposal_id, "epoch": self.epoch,
            "transport_call_index": self.transport_call_index,
            "transport_policy_id": self.transport_policy_id,
            "credential_reference_id": self.credential_reference_id,
            "http_capture_native_accounted": False, "native_snapshot_read_required": True,
            "control_authority": False, "final_acceptance": False}


@dataclass(frozen=True, slots=True)
class SelectedReadAttempt:
    """Bounded successful/partial capture observation with next host state."""

    next_orchestration_state: Any
    admission_receipt: Any
    tool_admission: Any
    source_binding_id: str
    selection_id: str
    proposal_id: str
    epoch: int
    transport_call_index: int | None
    transport_policy_id: str
    credential_reference_id: str
    status: str
    reason: str
    snapshot_id: str | None

    def canonical_record(self) -> dict:
        return {"protocol_version": "IBAE-SELECTED-READ-ATTEMPT-V1",
            "next_orchestration_state_id": self.next_orchestration_state.state_id,
            "admission_receipt_id": self.admission_receipt.receipt_id,
            "tool_admission_receipt_id": self.tool_admission.receipt_id,
            "task_id": self.tool_admission.task_id, "governance_id": self.tool_admission.governance_id,
            "tool_name": self.tool_admission.tool_name, "selection_id": self.selection_id,
            "proposal_id": self.proposal_id, "source_binding_id": self.source_binding_id,
            "occurrence_key": self.tool_admission.occurrence_key, "epoch": self.epoch,
            "transport_call_index": self.transport_call_index,
            "transport_reservation_consumed": self.transport_call_index is not None,
            "transport_policy_id": self.transport_policy_id,
            "credential_reference_id": self.credential_reference_id,
            "status": self.status, "reason": self.reason, "snapshot_id": self.snapshot_id,
            "native_http_execution": False, "control_authority": False, "final_acceptance": False}


class SelectedReadCaptureError(ActivationError):
    """Fixed error carrying the preserved partial admission/next-state result."""

    def __init__(self, attempt: SelectedReadAttempt) -> None:
        self.attempt = attempt
        super().__init__("selected capture incomplete: " + attempt.reason)


@dataclass(slots=True, eq=False)
class _PendingCapture:
    source_binding: str
    tool_name: str
    selection_id: str
    proposal_id: str
    dependency_fingerprint: str
    transport_call_index: int | None = None


class ActivationController:
    """Single-task, single-outstanding-call, default-off transport control.

    A local epoch retires transport reservations only. Detached projections are
    checked structurally and for declared revocation; this class cannot prove a
    stale serialized projection is current native authority. Native admission
    must still revalidate the live task before executing any proposed action.
    """

    __slots__ = ("_task_id", "_governance_id", "_ledger", "_stage", "_authorization",
                 "_observations", "_live_proposals", "_stream_overflow",
                 "_transport_policy_id", "_credential_reference_id", "_lock",
                 "_live_source_bindings", "_captures", "_used_read_proposals", "_capture_plan",
                 "_capture_next_state_id", "_capture_attempts", "_capture_inflight")

    def __init__(self, task_id: str, governance_id: str, *, max_transport_calls: int = 16,
                 transport_policy_id: str | None = None,
                 credential_reference_id: str | None = None) -> None:
        _identity("task identity", task_id)
        _identity("governance identity", governance_id)
        _count("transport call limit", max_transport_calls, MAX_TRANSPORT_CALLS, positive=True)
        if (transport_policy_id is None) != (credential_reference_id is None):
            raise ValueError("transport configuration requires both deployment bindings")
        if transport_policy_id is not None:
            _identity("transport policy identity", transport_policy_id)
            _identity("credential reference identity", credential_reference_id)
        self._transport_policy_id = transport_policy_id
        self._credential_reference_id = credential_reference_id
        self._lock = RLock()
        self._task_id, self._governance_id = task_id, governance_id
        self._ledger = _TransportLedger(max_transport_calls)
        self._stage = ActivationStage.SYNTHETIC
        self._authorization = None
        self._observations: dict[ActivationStage, StageObservation] = {}
        self._live_proposals: tuple[NormalizedProposal, ...] = ()
        self._stream_overflow = False
        self._live_source_bindings: tuple[str, ...] = ()
        self._captures: tuple[SelectedReadCapture, ...] = ()
        self._used_read_proposals: tuple[str, ...] = ()
        self._capture_plan: _PendingCapture | None = None
        self._capture_next_state_id: str | None = None
        self._capture_attempts: tuple[SelectedReadAttempt, ...] = ()
        self._capture_inflight: tuple[_PendingCapture, ...] = ()

    def __reduce__(self):
        raise TypeError("transport activation cannot be serialized or restored")

    @property
    def task_id(self) -> str:
        return self._task_id

    @property
    def governance_id(self) -> str:
        return self._governance_id

    @property
    def transport_policy_id(self) -> str | None:
        return self._transport_policy_id

    @property
    def credential_reference_id(self) -> str | None:
        return self._credential_reference_id

    @_locked
    def configure_transport(self, *, transport_policy_id: str, credential_reference_id: str) -> None:
        """Operator configuration changes always retire old gates and permits."""
        self._active()
        _identity("transport policy identity", transport_policy_id)
        _identity("credential reference identity", credential_reference_id)
        if (transport_policy_id, credential_reference_id) == (self.transport_policy_id, self.credential_reference_id):
            return
        self.rollback()
        self._transport_policy_id, self._credential_reference_id = transport_policy_id, credential_reference_id

    @property
    def stage(self) -> ActivationStage:
        return self._stage

    @property
    def tool_profile(self) -> ToolProfile:
        return _PROFILES[self._stage]

    @property
    def selected_read_tools(self) -> tuple[str, ...]:
        return () if self._authorization is None else self._authorization.selected_read_tools

    @property
    def selected_read_selection_ids(self) -> tuple[str, ...]:
        return () if self._authorization is None else self._authorization.selected_read_selection_ids

    @property
    def epoch(self) -> int:
        return self._ledger.epoch

    @property
    def revoked(self) -> bool:
        return self._ledger.revoked

    @property
    def call_count(self) -> int:
        return self._ledger.used

    @property
    def remaining_transport_calls(self) -> int:
        return self._ledger.limit - self._ledger.used

    @property
    def capture_occurrence_key(self) -> str:
        """The current deterministic host-side occurrence, not model authority."""
        return f"capture.{self.epoch}.{self.call_count}"

    def _active(self) -> None:
        if self.revoked:
            raise ActivationError("transport activation is revoked")

    def _binding(self, task_id, governance_id) -> None:
        _identity("task identity", task_id)
        _identity("governance identity", governance_id)
        if (task_id, governance_id) != (self.task_id, self.governance_id):
            raise ActivationError("transport task or governance binding differs")

    def _deployment(self, transport_policy_id, credential_reference_id) -> None:
        _identity("transport policy identity", transport_policy_id)
        _identity("credential reference identity", credential_reference_id)
        if (transport_policy_id, credential_reference_id) != (self.transport_policy_id, self.credential_reference_id):
            raise ActivationError("transport policy or credential deployment binding differs")

    def _projection(self, projection: dict) -> dict:
        record = _validate_projection(projection)
        self._binding(record["sources"]["task_id"], record["sources"]["governance_id"])
        authority = record["decision_surface"]["authority"]
        if authority["revoked"] or not authority["supervisor_capability_present"]:
            raise ActivationError("projection declares unavailable supervisor authority")
        return record

    @_locked
    def _verification_fence(self) -> tuple:
        self._active()
        return (self.epoch, self.stage, self.transport_policy_id, self.credential_reference_id,
                self.call_count, self._ledger.pending, self._live_proposals, self._stream_overflow,
                self._live_source_bindings, self._captures, self._used_read_proposals,
                self._capture_plan, self._capture_next_state_id, self._capture_attempts, self._capture_inflight)

    def _check_verification_fence(self, fence: tuple) -> None:
        if fence != self._verification_fence():
            raise ActivationError("transport state changed during stage verification")

    def _observation(self, *, live: bool, evidence: dict) -> StageObservation:
        """Build observation data only; this helper does not pass any gate."""
        rollback = _rollback_rehearsal()
        observation = StageObservation({
            "protocol_version": STAGE_OBSERVATION_VERSION, "stage": int(self.stage),
            "task_id": self.task_id, "governance_id": self.governance_id, "epoch": self.epoch,
            "transport_policy_id": self.transport_policy_id,
            "credential_reference_id": self.credential_reference_id,
            "tool_profile": self.tool_profile.value, "verification": "passed",
            "live_transport_observed": live, "live_recovery_verified": False,
            "grants_native_authority": False, "restores_native_authority": False,
            "final_acceptance": False, "evidence": evidence, "rollback": rollback,
        })
        return observation

    def verify_synthetic_stage(self) -> StageObservation:
        """Run real offline governed controls; no caller success claims accepted."""
        self._active()
        fence = self._verification_fence()
        if self.stage is not ActivationStage.SYNTHETIC:
            raise ActivationError("synthetic verification requires stage 0")
        from .synthetic_runner import reference_synthetic_transcripts, run_synthetic_transcript
        corpus = reference_synthetic_transcripts()
        evidence = []
        for name, accepted in (("happy_path", True), ("fake_completion_claim", False),
                               ("missing_evidence", False)):
            result = run_synthetic_transcript(corpus[name])
            replay = run_synthetic_transcript(corpus[name])
            record = result.canonical_record()
            if (record != replay.canonical_record()
                    or record["summary"]["global_final_acceptance"] is not accepted
                    or record["trust_scope"]["network_used"] is not False):
                raise ActivationError("synthetic governed replay gate failed")
            evidence.append({"case": name, "report_id": result.report_id})
        with self._lock:
            self._check_verification_fence(fence)
            observation = self._observation(live=False, evidence={"scope": "offline_governed_replay", "cases": evidence})
            self._observations[ActivationStage.SYNTHETIC] = observation
        return observation

    @_locked
    def authorize(self, authorization: OperatorStageAuthorization) -> None:
        """Apply a separate explicit operator instruction after the prior gate."""
        _exact("operator authorization", authorization, OperatorStageAuthorization)
        authorization.__post_init__()
        self._active()
        self._binding(authorization.task_id, authorization.governance_id)
        self._deployment(authorization.transport_policy_id, authorization.credential_reference_id)
        if authorization.epoch != self.epoch:
            raise ActivationError("operator authorization has a stale transport epoch")
        if int(authorization.stage) != int(self.stage) + 1:
            raise ActivationError("activation stages must advance sequentially")
        if self._ledger.pending is not None:
            raise ActivationError("cannot advance with an outstanding transport call")
        observation = self._observations.get(self.stage)
        if observation is None or observation.canonical_record()["epoch"] != self.epoch:
            raise ActivationError("preceding stage evidence and rollback gate are missing")
        if self.remaining_transport_calls == 0:
            raise ActivationError("transport call budget is exhausted")
        self._ledger.retire_epoch()
        self._stage = authorization.stage
        self._authorization = authorization
        self._live_proposals, self._stream_overflow = (), False
        self._live_source_bindings, self._captures, self._used_read_proposals = (), (), ()
        self._capture_plan, self._capture_next_state_id = None, None

    @_locked
    def reserve_call(self, projection: dict, *, stage: ActivationStage,
                     tool_profile: ToolProfile,
                     transport_policy_id: str, credential_reference_id: str,
                     selected_read_tools: tuple[str, ...] = ()) -> TransportCallReservation:
        self._active()
        self._deployment(transport_policy_id, credential_reference_id)
        _exact("activation stage", stage, ActivationStage)
        _exact("tool profile", tool_profile, ToolProfile)
        _tools(selected_read_tools)
        if (stage is ActivationStage.SYNTHETIC or stage is not self.stage
                or tool_profile is not self.tool_profile
                or selected_read_tools != self.selected_read_tools):
            raise ActivationError("transport stage or read-only profile is not activated")
        record = self._projection(projection)
        projection_id = domain_fingerprint("ibae.transport-projection-binding.v1", record)
        return self._ledger.reserve(self, stage, self.task_id, self.governance_id,
                                    "openai", projection_id=projection_id,
                                    transport_policy_id=transport_policy_id,
                                    credential_reference_id=credential_reference_id)

    @_locked
    def check_reservation(self, reservation: TransportCallReservation, projection: dict, *,
                          transport_policy_id: str, credential_reference_id: str) -> None:
        self._ledger.check(reservation, self)
        self._deployment(transport_policy_id, credential_reference_id)
        record = self._projection(projection)
        if (reservation.stage is not self.stage or reservation.kind != "openai"
                or reservation.transport_policy_id != transport_policy_id
                or reservation.credential_reference_id != credential_reference_id
                or reservation.projection_id != domain_fingerprint("ibae.transport-projection-binding.v1", record)):
            raise ActivationError("reservation does not bind this projection or stage")

    @_locked
    def reserve_read(self, *, task_id: str, governance_id: str,
                     tool_name: str, selection_id: str, proposal_id: str,
                     dependency_fingerprint: str) -> TransportCallReservation:
        self._active()
        self._binding(task_id, governance_id)
        _exact("selected read tool", tool_name, str)
        require_symbol("selected read tool", tool_name)
        _identity("selected read resource identity", selection_id)
        _identity("selected read proposal identity", proposal_id)
        _identity("selected read dependency", dependency_fingerprint)
        if (self.stage is not ActivationStage.OPENAI_SELECTED_READS or tool_name not in self.selected_read_tools
                or selection_id not in self.selected_read_selection_ids):
            raise ActivationError("real read tool is not selected in active stage 3")
        self._check_capture_plan(tool_name, selection_id, proposal_id, dependency_fingerprint)
        if self._capture_plan.transport_call_index is not None:
            raise ActivationError("selected capture plan already consumed its transport reservation")
        reservation = self._ledger.reserve(self, self.stage, self.task_id, self.governance_id,
                                    "selected_read", tool_name=tool_name,
                                    transport_policy_id=self.transport_policy_id,
                                    credential_reference_id=self.credential_reference_id, selection_id=selection_id,
                                    proposal_id=proposal_id, dependency_fingerprint=dependency_fingerprint)
        self._capture_plan.transport_call_index = reservation.call_index
        return reservation

    def _check_capture_plan(self, tool_name, selection_id, proposal_id, dependency_fingerprint) -> None:
        plan = self._capture_plan
        if (plan is None or (tool_name, selection_id, proposal_id, dependency_fingerprint)
                != (plan.tool_name, plan.selection_id, plan.proposal_id, plan.dependency_fingerprint)):
            raise ActivationError("selected read has no controller-owned governed capture plan")

    @_locked
    def check_read_reservation(self, reservation: TransportCallReservation) -> None:
        self._ledger.check(reservation, self)
        if (self.stage is not ActivationStage.OPENAI_SELECTED_READS
                or reservation.stage is not self.stage or reservation.kind != "selected_read"
                or reservation.transport_policy_id != self.transport_policy_id
                or reservation.credential_reference_id != self.credential_reference_id
                or reservation.selection_id not in self.selected_read_selection_ids
                or reservation.tool_name not in self.selected_read_tools):
            raise ActivationError("read reservation is outside the selected read-only profile")
        self._check_capture_plan(reservation.tool_name, reservation.selection_id,
                                 reservation.proposal_id, reservation.dependency_fingerprint)

    @_locked
    def complete_call(self, reservation: TransportCallReservation) -> None:
        """Retire success/failure alike; completing a call never verifies a stage."""
        _exact("transport reservation", reservation, TransportCallReservation)
        if reservation._owner is not self:
            raise ActivationError("transport reservation belongs to another controller")
        if self._ledger.pending is reservation:
            self._ledger.pending = None

    def propose(self, supervisor, projection: dict, *, index: int,
                fresh_handoff: dict | None = None, previous_response_id: str | None = None) -> NormalizedProposal:
        """Own the exact official call path before retaining live gate input.

        Pure decoding, fake supervisors and caller-created proposal records never
        enter this stream. The trusted Python/official-SDK path is assumed intact;
        this is not remote attestation or protection against monkeypatching.
        """
        from .openai_transport import OpenAIResponsesSupervisor
        _exact("official supervisor", supervisor, OpenAIResponsesSupervisor)
        self._active()
        deployment = OpenAIResponsesSupervisor.deployment_record(supervisor)
        self._deployment(deployment["transport_policy_id"], deployment["credential_reference_id"])
        detached = self._projection(projection)
        source_binding = _source_binding(detached)
        epoch, stage, before = self.epoch, self.stage, self.call_count
        proposal = OpenAIResponsesSupervisor.propose(
            supervisor, detached, index=index, activation=self,
            fresh_handoff=fresh_handoff, previous_response_id=previous_response_id,
        )
        _exact("normalized live proposal", proposal, NormalizedProposal)
        with self._lock:
            if (self.revoked or self.epoch != epoch or self.stage is not stage
                    or self.call_count != before + 1 or self._ledger.pending is not None):
                raise ActivationError("official call did not preserve its transport reservation")
            if len(self._live_proposals) == MAX_RETAINED_PROPOSALS:
                self._stream_overflow = True
            else:
                self._live_proposals += (NormalizedProposal.from_record(proposal.canonical_record()),)
                self._live_source_bindings += (source_binding,)
        return proposal

    def _require_smoke_stream(self, stage: ActivationStage) -> dict:
        self._active()
        if self.stage is not stage or self._ledger.pending is not None:
            raise ActivationError("verification requires the matching idle live stage")
        from .synthetic_runner import reference_synthetic_transcripts
        transcript = reference_synthetic_transcripts()["happy_path"]
        if (self._stream_overflow or not self._live_proposals
                or [item.canonical_record() for item in self._live_proposals] != transcript["proposals"]):
            raise ActivationError("owned official proposal stream does not match the closed smoke gate")
        return transcript

    def capture_selected_read(self, adapter, proposal: NormalizedProposal,
                              dependency_fingerprint: str, *, context: SupervisorContext, batch) -> SelectedReadCapture:
        """Admit one owned live READ, capture HTTP, then freeze its observation.

        The native context is inspected only on this trusted controller side.
        The adapter receives the detached proposal/dependency and its existing
        activation checks, never the context, admission object or native seal.
        """
        from .observed_snapshots import ObservedReadSnapshot
        from .readonly_adapters import (ExternalObservationReceipt, GitHubReadAdapter,
                                        GitHubReadSelection, GitHubRequestPlan)

        _exact("selected read adapter", adapter, GitHubReadAdapter)
        _exact("normalized selected read", proposal, NormalizedProposal)
        _exact("live supervisor context", context, SupervisorContext)
        _identity("selected read dependency", dependency_fingerprint)
        GitHubReadAdapter.validate_activation(adapter, self)
        binding = GitHubReadAdapter.binding_record(adapter)
        self._binding(binding["task_id"], binding["governance_id"])
        selection = GitHubReadSelection.from_record(binding["selection"])
        request = GitHubRequestPlan(proposal, selection, dependency_fingerprint).canonical_record()
        with self._lock:
            self._active()
            if self.stage is not ActivationStage.OPENAI_SELECTED_READS:
                raise ActivationError("selected capture requires active stage 3")
            if self._capture_plan is not None or self._ledger.pending is not None:
                raise ActivationError("another transport capture or call is outstanding")
            if len(self._capture_attempts) + len(self._capture_inflight) >= MAX_SELECTED_READ_CAPTURES:
                raise ActivationError("selected capture retention bound is exhausted")
            if proposal.proposal_id in self._used_read_proposals:
                raise ActivationError("owned selected read proposal was already consumed")
            tool_name = proposal.payload["tool_name"]
            if tool_name not in self.selected_read_tools or selection.selection_id not in self.selected_read_selection_ids:
                raise ActivationError("selected capture is outside its authorized tool/resource scope")
            current = self._projection(SupervisorProjection(context).canonical_record())
            source = _source_binding(current)
            if not any(item == proposal and recorded_source == source
                       for item, recorded_source in zip(self._live_proposals, self._live_source_bindings)):
                raise ActivationError("selected read lacks an owned live proposal for the current native context")
            if (self._capture_next_state_id is not None
                    and context.orchestration_state.state_id != self._capture_next_state_id):
                raise ActivationError("host did not advance the prior capture's orchestration state")
            _, transition, tool_admission = _admit_selected_read(
                context, proposal, batch, dependency_fingerprint, self.capture_occurrence_key)
            plan = _PendingCapture(source, tool_name, selection.selection_id,
                                   proposal.proposal_id, dependency_fingerprint)
            self._capture_plan = plan
            self._used_read_proposals += (proposal.proposal_id,)
            self._capture_inflight += (plan,)
            fence = self._verification_fence()
        status, reason, capture = "failed", "capture_failed", None
        try:
            # No native witness is stored on the adapter-reachable controller.
            # Revalidation is trusted-host side; it cannot cancel an HTTP read
            # already in flight when native revocation subsequently occurs.
            current = self._projection(SupervisorProjection(context).canonical_record())
            if _source_binding(current) != source:
                raise ActivationError("selected native context changed before dispatch")
            # There is deliberately no injected transport/callback alternative.
            receipt = GitHubReadAdapter.observe(adapter, proposal, dependency_fingerprint)
            _exact("selected external observation", receipt, ExternalObservationReceipt)
            observed = receipt.canonical_record()
            if observed["request"] != request:
                status, reason = "invalid_observation", "capture_request_mismatch"
                raise ActivationError("selected read returned a different request")
            if observed["status"] != "observed":
                status, reason = "unavailable", "remote_observation_unavailable"
                raise ActivationError("selected read did not establish the exact requested observation")
            status, reason = "invalid_observation", "snapshot_content_rejected"
            snapshot = ObservedReadSnapshot.from_receipt(receipt)
            status, reason = "interrupted", "capture_context_changed"
            current = self._projection(SupervisorProjection(context).canonical_record())
            if _source_binding(current) != source:
                raise ActivationError("selected native context changed during capture")
            with self._lock:
                # Only this request's single transport reservation may advance.
                expected = list(fence)
                expected[4] += 1
                self._check_verification_fence(tuple(expected))
                self._check_capture_plan(tool_name, selection.selection_id, proposal.proposal_id,
                                         dependency_fingerprint)
                capture = SelectedReadCapture(snapshot, transition.next_state, transition.receipt,
                    tool_admission, selection.selection_id, proposal.proposal_id, self.epoch,
                    fence[4], self.transport_policy_id, self.credential_reference_id)
                self._captures += (capture,)
                self._capture_next_state_id = transition.next_state.state_id
                status, reason = "captured", "observation_captured"
        except Exception:
            capture = None
            if self.revoked or self.epoch != fence[0]:
                status, reason = "interrupted", "transport_epoch_retired"
            elif plan.transport_call_index is None:
                status, reason = "not_dispatched", "capture_not_dispatched"
        finally:
            with self._lock:
                attempt = SelectedReadAttempt(transition.next_state, transition.receipt, tool_admission,
                    source, selection.selection_id, proposal.proposal_id, fence[0], plan.transport_call_index,
                    fence[2], fence[3], status, reason, None if capture is None else capture.snapshot.snapshot_id)
                self._capture_attempts += (attempt,)
                self._capture_inflight = tuple(item for item in self._capture_inflight if item is not plan)
                if self._capture_plan is plan:
                    self._capture_plan = None
                    self._capture_next_state_id = transition.next_state.state_id
        if capture is None:
            # Raise outside the except suite: raw transport errors/bodies are
            # neither the exception context nor part of the partial observation.
            raise SelectedReadCaptureError(attempt)
        return capture

    def verify_fake_tool_stage(self) -> StageObservation:
        """Combine owned official observations with closed fake-tool replay."""
        fence = self._verification_fence()
        transcript = self._require_smoke_stream(ActivationStage.OPENAI_FAKE_TOOLS)
        from .synthetic_runner import run_synthetic_transcript
        result = run_synthetic_transcript(transcript)
        replay = run_synthetic_transcript(transcript)
        if (result.canonical_record() != replay.canonical_record()
                or result.canonical_record()["summary"]["global_final_acceptance"] is not True):
            raise ActivationError("live fake-tool admission equivalence failed")
        with self._lock:
            self._check_verification_fence(fence)
            observation = self._observation(live=True, evidence={"scope": "closed_live_stream_fake_tool_equivalence",
                "proposal_stream_id": domain_fingerprint("ibae.transport-proposal-stream.v1", transcript["proposals"]),
                "probe_report_id": result.report_id})
            self._observations[ActivationStage.OPENAI_FAKE_TOOLS] = observation
        return observation

    def verify_fixture_stage(self) -> StageObservation:
        """Combine owned official stream with the exact built-in fixture probe."""
        fence = self._verification_fence()
        transcript = self._require_smoke_stream(ActivationStage.OPENAI_DETERMINISTIC_READS)
        from .transport_conformance import verify_readonly_fixture_stage
        result = bounded_synthetic_data(verify_readonly_fixture_stage(), max_bytes=262_144)
        expected_stream = domain_fingerprint("ibae.transport-proposal-stream.v1", transcript["proposals"])
        if (type(result) is not dict or result.get("equivalent") is not True
                or result.get("live_verification") is not False
                or result.get("proposal_stream_id") != expected_stream):
            raise ActivationError("deterministic read-only fixture equivalence failed")
        _identity("fixture probe report identity", result.get("report_id"))
        with self._lock:
            self._check_verification_fence(fence)
            observation = self._observation(live=True, evidence={"scope": "closed_live_stream_readonly_fixture_equivalence",
                "proposal_stream_id": expected_stream, "probe_report_id": result["report_id"]})
            self._observations[ActivationStage.OPENAI_DETERMINISTIC_READS] = observation
        return observation

    def verify_selected_read_stage(self) -> StageObservation:
        """Verify owned HTTP captures and separately governed native consumption.

        The native proof concerns immutable captured content, not execution of
        the HTTP operation, current remote state or external source truth.
        """
        from .observed_snapshots import verify_observed_snapshot_stage

        with self._lock:
            fence = self._verification_fence()
            if (self.stage is not ActivationStage.OPENAI_SELECTED_READS
                    or self._ledger.pending is not None or self._capture_plan is not None):
                raise ActivationError("selected-read verification requires idle stage 3")
            required = {(tool, selection) for tool in self.selected_read_tools
                        for selection in self.selected_read_selection_ids}
            covered = {(capture.tool_admission.tool_name, capture.selection_id) for capture in self._captures}
            if not required or covered != required:
                raise ActivationError("owned selected captures do not cover every authorized tool/resource pair")
            snapshots = tuple(capture.snapshot for capture in self._captures)
            snapshot_ids = sorted({snapshot.snapshot_id for snapshot in snapshots})
            if len(snapshot_ids) != len(snapshots):
                raise ActivationError("selected captures contain duplicate snapshot identities")
        result = bounded_synthetic_data(verify_observed_snapshot_stage(snapshots), max_bytes=65_536)
        if (type(result) is not dict or result.get("equivalent") is not True
                or result.get("live_verification") is not False or result.get("transport_calls") != 0
                or result.get("source_snapshot_ids") != snapshot_ids
                or result.get("snapshot_count") != len(snapshots)
                or result.get("final_acceptance") is not False):
            raise ActivationError("selected immutable-snapshot native parity verification failed")
        _identity("selected snapshot proof identity", result.get("report_id"))
        with self._lock:
            self._check_verification_fence(fence)
            observation = self._observation(live=True, evidence={
                "scope": "governed_http_capture_then_separate_native_snapshot_consumption",
                "source_snapshot_ids": snapshot_ids, "http_captures": len(snapshots),
                "capture_receipts": [capture.canonical_record() for capture in self._captures],
                "capture_attempts": [attempt.canonical_record() for attempt in self._capture_attempts
                                     if attempt.epoch == self.epoch],
                "probe_report_id": result["report_id"], "native_proof": result["native_proof"],
                "fresh_native_runs": result["fresh_native_runs"],
                "native_total_counters": result["native_total_counters"],
                "native_proof_transport_calls": 0, "http_capture_native_accounted": False,
                "remote_current_state_verified": False, "external_truth_authenticated": False})
            self._observations[ActivationStage.OPENAI_SELECTED_READS] = observation
            return observation

    @_locked
    def rollback(self) -> None:
        """Return to stage 0, retire every permit/gate, and retain spent budget."""
        self._active()
        self._ledger.retire_epoch()
        self._stage, self._authorization = ActivationStage.SYNTHETIC, None
        self._observations.clear()
        self._live_proposals, self._stream_overflow = (), False
        self._live_source_bindings, self._captures, self._used_read_proposals = (), (), ()
        self._capture_plan, self._capture_next_state_id = None, None

    @_locked
    def revoke(self) -> None:
        """Terminal transport-local revocation; no reset/regrant surface exists."""
        if not self.revoked:
            self._ledger.retire_epoch(revoke=True)
            self._observations.clear()
            self._live_proposals, self._stream_overflow = (), False
            self._live_source_bindings, self._captures, self._used_read_proposals = (), (), ()
            self._capture_plan, self._capture_next_state_id = None, None

    @_locked
    def canonical_record(self) -> dict:
        """Detached observation. No from_record, restore or activation parser."""
        reserved_captures = (sum(attempt.transport_call_index is not None for attempt in self._capture_attempts)
                             + sum(plan.transport_call_index is not None for plan in self._capture_inflight))
        if reserved_captures != self._ledger.selected_read_calls:
            raise ActivationError("selected capture reservation evidence does not reconcile")
        current = self._observations.get(self.stage)
        verification = ("passed" if current is not None and current.canonical_record()["epoch"] == self.epoch else
                        "not_verified")
        return {"protocol_version": ACTIVATION_VERSION, "task_id": self.task_id,
            "governance_id": self.governance_id, "stage": int(self.stage),
            "transport_policy_id": self.transport_policy_id,
            "credential_reference_id": self.credential_reference_id,
            "tool_profile": self.tool_profile.value, "selected_read_tools": list(self.selected_read_tools),
            "selected_read_selection_ids": list(self.selected_read_selection_ids),
            "epoch": self.epoch, "epoch_scope": "python_transport_only", "revoked": self.revoked,
            "maximum_transport_calls": self._ledger.limit, "consumed_transport_calls": self.call_count,
            "openai_transport_calls": self._ledger.openai_calls,
            "selected_http_reservations": self._ledger.selected_read_calls,
            "remaining_transport_calls": self.remaining_transport_calls,
            "outstanding_call": self._ledger.pending is not None,
            "active_stage_verification": verification,
            "selected_read_stage_verifier": "owned_capture_and_native_snapshot_parity",
            "selected_capture_count": len(self._captures),
            "consumed_selected_proposals": len(self._used_read_proposals),
            "selected_capture_attempts_remaining": MAX_SELECTED_READ_CAPTURES - len(self._capture_attempts) - len(self._capture_inflight),
            "selected_capture_attempts": [attempt.canonical_record() for attempt in self._capture_attempts],
            "selected_capture_outcomes": {status: sum(attempt.status == status for attempt in self._capture_attempts)
                for status in ("captured", "failed", "unavailable", "invalid_observation", "interrupted", "not_dispatched")},
            "selected_capture_incomplete": len(self._capture_inflight),
            "stage_observations": [self._observations[stage].canonical_record() for stage in sorted(self._observations)],
            "native_authority": False, "serialized_restore_supported": False,
            "live_recovery_verified": False, "effects_supported": False}
