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
from .supervisor import _validate_projection
from .synthetic_protocol import NormalizedProposal, bounded_synthetic_data

ACTIVATION_VERSION = "IBAE-TRANSPORT-ACTIVATION-V1"
STAGE_OBSERVATION_VERSION = "IBAE-TRANSPORT-STAGE-OBSERVATION-V1"
MAX_TRANSPORT_CALLS = 1_024
MAX_SELECTED_READ_TOOLS = 32
MAX_RETAINED_PROPOSALS = 16
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

    def __init__(self) -> None:
        raise TypeError("transport reservations are issued only by their controller")

    def __reduce__(self):
        raise TypeError("transport reservations cannot be serialized or restored")


class _TransportLedger:
    """Small ordinary Python ledger, shared by dispatch and rollback rehearsal."""

    __slots__ = ("epoch", "used", "limit", "revoked", "pending")

    def __init__(self, limit: int) -> None:
        self.epoch, self.used, self.limit, self.revoked, self.pending = 0, 0, limit, False, None

    def reserve(self, owner, stage, task_id, governance_id, kind, projection_id=None,
                tool_name=None, transport_policy_id=None,
                credential_reference_id=None, selection_id=None) -> TransportCallReservation:
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
        for name, value in values.items():
            object.__setattr__(reservation, name, value)
        self.used += 1  # Failed/ambiguous calls never refund or auto-retry.
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


class ActivationController:
    """Single-task, single-outstanding-call, default-off transport control.

    A local epoch retires transport reservations only. Detached projections are
    checked structurally and for declared revocation; this class cannot prove a
    stale serialized projection is current native authority. Native admission
    must still revalidate the live task before executing any proposed action.
    """

    __slots__ = ("_task_id", "_governance_id", "_ledger", "_stage", "_authorization",
                 "_observations", "_live_proposals", "_stream_overflow",
                 "_transport_policy_id", "_credential_reference_id", "_lock")

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
                self.call_count, self._ledger.pending, self._live_proposals, self._stream_overflow)

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
                     tool_name: str, selection_id: str) -> TransportCallReservation:
        self._active()
        self._binding(task_id, governance_id)
        _exact("selected read tool", tool_name, str)
        require_symbol("selected read tool", tool_name)
        _identity("selected read resource identity", selection_id)
        if (self.stage is not ActivationStage.OPENAI_SELECTED_READS or tool_name not in self.selected_read_tools
                or selection_id not in self.selected_read_selection_ids):
            raise ActivationError("real read tool is not selected in active stage 3")
        return self._ledger.reserve(self, self.stage, self.task_id, self.governance_id,
                                    "selected_read", tool_name=tool_name,
                                    transport_policy_id=self.transport_policy_id,
                                    credential_reference_id=self.credential_reference_id, selection_id=selection_id)

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
        epoch, stage, before = self.epoch, self.stage, self.call_count
        proposal = OpenAIResponsesSupervisor.propose(
            supervisor, projection, index=index, activation=self,
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
        """Fail closed until a trusted selected-read/native-task verifier exists.

        An external receipt, a successful GET or a model completion claim cannot
        stand in for this gate. No stage 4 or effect activation is supported.
        """
        self._active()
        raise ActivationError(
            "selected-read stage verification is unavailable: no trusted native selected-read task verifier")

    @_locked
    def rollback(self) -> None:
        """Return to stage 0, retire every permit/gate, and retain spent budget."""
        self._active()
        self._ledger.retire_epoch()
        self._stage, self._authorization = ActivationStage.SYNTHETIC, None
        self._observations.clear()
        self._live_proposals, self._stream_overflow = (), False

    @_locked
    def revoke(self) -> None:
        """Terminal transport-local revocation; no reset/regrant surface exists."""
        if not self.revoked:
            self._ledger.retire_epoch(revoke=True)
            self._observations.clear()
            self._live_proposals, self._stream_overflow = (), False

    @_locked
    def canonical_record(self) -> dict:
        """Detached observation. No from_record, restore or activation parser."""
        current = self._observations.get(self.stage)
        verification = ("unavailable" if self.stage is ActivationStage.OPENAI_SELECTED_READS else
                        "passed" if current is not None and current.canonical_record()["epoch"] == self.epoch else
                        "not_verified")
        return {"protocol_version": ACTIVATION_VERSION, "task_id": self.task_id,
            "governance_id": self.governance_id, "stage": int(self.stage),
            "transport_policy_id": self.transport_policy_id,
            "credential_reference_id": self.credential_reference_id,
            "tool_profile": self.tool_profile.value, "selected_read_tools": list(self.selected_read_tools),
            "selected_read_selection_ids": list(self.selected_read_selection_ids),
            "epoch": self.epoch, "epoch_scope": "python_transport_only", "revoked": self.revoked,
            "maximum_transport_calls": self._ledger.limit, "consumed_transport_calls": self.call_count,
            "remaining_transport_calls": self.remaining_transport_calls,
            "outstanding_call": self._ledger.pending is not None,
            "active_stage_verification": verification,
            "selected_read_stage_verifier": "unavailable",
            "stage_observations": [self._observations[stage].canonical_record() for stage in sorted(self._observations)],
            "native_authority": False, "serialized_restore_supported": False,
            "live_recovery_verified": False, "effects_supported": False}
