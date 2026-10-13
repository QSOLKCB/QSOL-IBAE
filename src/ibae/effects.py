"""Default-disabled, governed synthetic effects with native-owned authority.

The profile is committed in the original task acceptance contract before a
native effect ledger can be created.  These records are inert declarations;
only the matching native supervisor capability can issue one-shot approvals.
All operations use a closed in-memory synthetic backend.  No network, file,
callback, credential, external approval or real-effect execution is provided.
Effect evidence never enters the legacy read-only finalizer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, fields
from enum import Enum
from typing import Any

from ._records import CanonicalValue, bounded_utf8_length, require_fingerprint, require_symbol
from .canonical import canonical_json, domain_fingerprint
from .governance import (
    GovernancePolicy, GovernanceReceipt, PrincipalAuthority, ProviderAuthority,
    TaskReceipt, ToolAdmissionReceipt, ToolAuthorityClass, ToolPermission,
    _require_governance_binding, _require_tool_admission_binding,
    _validated_action_proposal_copy, _validated_admission_decision_copy,
    _validated_capability_copy,
)
from .orchestration import (
    ACTION_ID_DOMAIN, ActionProposal, AdmissionDecision, AuthorityLayer,
    Capability, DecisionStatus, RecoveryAction, RejectionReason, ReplaySafety,
)
from .runtime import RustRuntimeSession

EFFECT_PROFILE_VERSION = "IBAE-EFFECT-PROFILE-V1"
EFFECT_RUNTIME_VERSION = "IBAE-EFFECT-RUNTIME-V1"
EFFECT_SNAPSHOT_VERSION = "IBAE-EFFECT-SNAPSHOT-V1"
EFFECT_PROFILE_ID_DOMAIN = "ibae.effect-profile-id.v1"
MAX_EFFECT_ENTRIES = 64
MAX_EFFECT_CELLS = 64
MAX_EFFECT_REQUESTS = 4_096
MAX_EFFECT_EXECUTIONS = 1_024
MAX_EFFECT_RETRIES = 1_024
MAX_EFFECT_RECONCILIATIONS = 1_024
MAX_EFFECT_OUTCOMES = 16
MAX_EFFECT_RECORD_BYTES = 1_048_576
_MIN_I64 = -(1 << 63)
_MAX_I64 = (1 << 63) - 1


class EffectCommand(str, Enum):
    EXECUTE = "execute_effect"
    RETRY = "retry_effect"
    RECONCILE = "reconcile_effect"
    CANCEL = "cancel_effect"


class SyntheticEffectOutcome(str, Enum):
    SUCCESS = "success"
    FAIL_BEFORE = "fail_before"
    CRASH_AFTER = "crash_after"
    CRASH_BEFORE = "crash_before"
    AMBIGUOUS_UNKNOWN = "ambiguous_unknown"


class EffectStatus(str, Enum):
    PENDING = "pending"
    NOT_APPLIED = "not_applied"
    APPLIED = "applied"
    AMBIGUOUS = "ambiguous"
    CANCELLED = "cancelled"
    RECONCILED_APPLIED = "reconciled_applied"
    RECONCILED_NOT_APPLIED = "reconciled_not_applied"


def _exact(name: str, value: Any, expected: type) -> None:
    if type(value) is not expected:
        raise TypeError(f"{name} requires exact {expected.__name__}")


def _identity(name: str, value: Any) -> None:
    _exact(name, value, str)
    require_fingerprint(name, value)


def _symbol(name: str, value: Any) -> None:
    _exact(name, value, str)
    require_symbol(name, value)


def _count(name: str, value: Any, maximum: int, *, positive: bool = False) -> None:
    _exact(name, value, int)
    if not int(positive) <= value <= maximum:
        raise ValueError(f"{name} exceeds its finite bound")


def _integer(name: str, value: Any) -> None:
    _exact(name, value, int)
    if not _MIN_I64 <= value <= _MAX_I64:
        raise ValueError(f"{name} must fit signed 64-bit synthetic cells")


def _fields(name: str, value: Any, expected: set[str]) -> dict:
    _exact(name, value, dict)
    if len(value) != len(expected) or any(type(key) is not str or key not in expected for key in value):
        raise ValueError(f"{name} does not match its versioned schema")
    return value


def _json_copy(value: Any) -> Any:
    """Bound and copy exact inert JSON before calling any serializer."""
    budget = [32_768, MAX_EFFECT_RECORD_BYTES]

    def copy(item: Any, depth: int) -> Any:
        budget[0] -= 1
        if budget[0] < 0 or depth > 24:
            raise ValueError("effect record exceeds structural bounds")
        kind = type(item)
        if kind is str:
            size = bounded_utf8_length("effect text", item, limit=MAX_EFFECT_RECORD_BYTES)
            budget[1] -= size + 2
            result = item
        elif item is None or kind is bool:
            budget[1] -= 5
            result = item
        elif kind is int:
            if item.bit_length() > 256:
                raise ValueError("effect record integer exceeds bound")
            budget[1] -= len(str(item))
            result = item
        elif kind is list:
            if len(item) > 1_024:
                raise ValueError("effect record array exceeds bound")
            budget[1] -= len(item) + 2
            result = [copy(child, depth + 1) for child in item]
        elif kind is dict:
            if len(item) > 256 or any(type(key) is not str for key in item):
                raise ValueError("effect record object exceeds bound or has invalid keys")
            budget[1] -= 2 * len(item) + 2
            result = {copy(key, depth + 1): copy(child, depth + 1) for key, child in item.items()}
        else:
            raise TypeError("effect records require exact inert JSON values")
        if budget[1] < 0:
            raise ValueError("effect record exceeds byte bound")
        return result

    result = copy(value, 0)
    bounded_utf8_length("effect record", canonical_json(result), limit=MAX_EFFECT_RECORD_BYTES)
    return result


_RECORD_TYPES = (
    CanonicalValue, Capability, ActionProposal, AdmissionDecision,
    GovernancePolicy, GovernanceReceipt, TaskReceipt, ToolAdmissionReceipt, ToolPermission,
)
_ENUM_TYPES = (
    PrincipalAuthority, ProviderAuthority, ToolAuthorityClass, AuthorityLayer,
    DecisionStatus, RecoveryAction, RejectionReason, ReplaySafety,
)


def _inert_record(value: Any) -> None:
    """Check the closed record graph before invoking its canonical methods."""
    remaining = [65_536]

    def visit(item: Any, depth: int) -> None:
        remaining[0] -= 1
        if remaining[0] < 0 or depth > 24:
            raise ValueError("effect authority graph exceeds bounds")
        kind = type(item)
        if kind in (str, int, bool, type(None)) or kind in _ENUM_TYPES:
            if kind is str:
                bounded_utf8_length("effect authority text", item, limit=MAX_EFFECT_RECORD_BYTES)
            elif kind is int and item.bit_length() > 256:
                raise ValueError("effect authority integer exceeds bound")
            return
        if kind is tuple:
            if len(item) > 1_024:
                raise ValueError("effect authority tuple exceeds bound")
            for child in item:
                visit(child, depth + 1)
            return
        if kind not in _RECORD_TYPES:
            raise TypeError("effect authority fields require exact inert record types")
        for field in fields(kind):
            visit(object.__getattribute__(item, field.name), depth + 1)

    visit(value, 0)


def _read_text(value: Any) -> dict:
    _exact("stored canonical effect text", value, str)
    bounded_utf8_length("effect record", value, limit=MAX_EFFECT_RECORD_BYTES)
    try:
        record = _json_copy(json.loads(value))
    except (RecursionError, json.JSONDecodeError) as exc:
        raise ValueError("invalid canonical effect record") from exc
    if type(record) is not dict or canonical_json(record) != value:
        raise ValueError("effect record must be canonical JSON")
    return record


@dataclass(frozen=True, slots=True)
class EffectLimits:
    max_requests: int = 64
    max_executions: int = 16
    max_retries: int = 8
    max_reconciliations: int = 16

    def __post_init__(self) -> None:
        for name, maximum in (
            ("max_requests", MAX_EFFECT_REQUESTS),
            ("max_executions", MAX_EFFECT_EXECUTIONS),
            ("max_retries", MAX_EFFECT_RETRIES),
            ("max_reconciliations", MAX_EFFECT_RECONCILIATIONS),
        ):
            _count(name, getattr(self, name), maximum, positive=name in {"max_requests", "max_executions"})

    def canonical_record(self) -> dict:
        self.__post_init__()
        return {field.name: getattr(self, field.name) for field in fields(EffectLimits)}

    @classmethod
    def from_record(cls, record: dict) -> EffectLimits:
        active = _fields("effect limits", record, {field.name for field in fields(EffectLimits)})
        return cls(**active)


@dataclass(frozen=True, slots=True, init=False)
class EffectEntry:
    """One precommitted, occurrence-sensitive synthetic action declaration."""

    _text: str

    def __init__(
        self, capability: Capability, proposal: ActionProposal,
        admission_decision: AdmissionDecision, dependency_state_id: str,
        outcomes: tuple[SyntheticEffectOutcome, ...] = (SyntheticEffectOutcome.SUCCESS,),
    ) -> None:
        for name, value, kind in (
            ("capability", capability, Capability), ("proposal", proposal, ActionProposal),
            ("admission decision", admission_decision, AdmissionDecision),
        ):
            _exact(name, value, kind)
            _inert_record(value)
        capability = _validated_capability_copy(capability)
        proposal = _validated_action_proposal_copy(proposal)
        decision = _validated_admission_decision_copy(admission_decision)
        _identity("dependency state id", dependency_state_id)
        _exact("effect outcomes", outcomes, tuple)
        if not 1 <= len(outcomes) <= MAX_EFFECT_OUTCOMES:
            raise ValueError("effect outcome sequence exceeds its finite bound")
        for outcome in outcomes:
            _exact("effect outcome", outcome, SyntheticEffectOutcome)
        if capability.name not in {"synthetic_set", "synthetic_increment"}:
            raise ValueError("only the closed synthetic effect tools are supported")
        if capability.replay_safety is not ReplaySafety.OCCURRENCE_SENSITIVE or not capability.available:
            raise ValueError("effects require available occurrence-sensitive capabilities")
        _symbol("effect occurrence key", proposal.occurrence_key)
        if proposal.capability != capability.name or decision.proposal_id != proposal.proposal_id or decision.proposal_key != proposal.proposal_key:
            raise ValueError("effect entry proposal/admission binding mismatch")
        if decision.status is not DecisionStatus.ADMITTED or decision.authority_layer is not AuthorityLayer.ORCHESTRATION:
            raise ValueError("effect entry requires an admitted orchestration decision")
        if decision.blocking_obligation_ids or decision.unresolved_state_keys:
            raise ValueError("effect admission cannot retain blocking state")
        expected_keys = tuple(sorted(set(capability.required_state_keys) | set(proposal.required_state_keys)))
        if decision.dependency_state_keys != expected_keys:
            raise ValueError("effect dependency key binding mismatch")
        arguments = capability.normalize_arguments(proposal.arguments)
        operand = "value" if capability.name == "synthetic_set" else "delta"
        if capability.semantic_argument_keys != tuple(sorted(("key", operand, "expected_value"))):
            raise ValueError("synthetic effects require the exact closed argument schema")
        _fields("synthetic effect arguments", arguments, {"key", operand, "expected_value"})
        _symbol("synthetic cell key", arguments["key"])
        _integer("synthetic operand", arguments[operand])
        _integer("synthetic precondition", arguments["expected_value"])
        expected_action = domain_fingerprint(ACTION_ID_DOMAIN, {
            "arguments": arguments, "capability_id": capability.capability_id,
            "dependency_state_id": dependency_state_id, "occurrence_key": proposal.occurrence_key,
        })
        if decision.action_id != expected_action:
            raise ValueError("effect action identity mismatch")
        record = {
            "capability": capability.canonical_record(), "proposal": proposal.canonical_record(),
            "admission_decision": decision.canonical_record(), "dependency_state_id": dependency_state_id,
            "outcomes": [outcome.value for outcome in outcomes],
        }
        object.__setattr__(self, "_text", canonical_json(_json_copy(record)))

    @property
    def action_id(self) -> str:
        return self.canonical_record()["admission_decision"]["action_id"]

    @property
    def occurrence_key(self) -> str:
        return self.canonical_record()["proposal"]["occurrence_key"]

    def canonical_record(self) -> dict:
        record = _read_text(self._text)
        _entry_from_record(record)
        return record

    @classmethod
    def from_record(cls, record: dict) -> EffectEntry:
        return _entry_from_record(_json_copy(record))


@dataclass(frozen=True, slots=True, init=False)
class EffectProfile:
    """Finite immutable task input; it never issues execution authority."""

    _text: str

    def __init__(
        self, governance_id: str, entries: tuple[EffectEntry, ...], *,
        initial_cells: dict[str, int], limits: EffectLimits | None = None,
    ) -> None:
        _identity("governance id", governance_id)
        _exact("effect entries", entries, tuple)
        if not 1 <= len(entries) <= MAX_EFFECT_ENTRIES:
            raise ValueError("effect entries exceed the finite manifest bound")
        for entry in entries:
            _exact("effect entry", entry, EffectEntry)
        _exact("initial cells", initial_cells, dict)
        if not 1 <= len(initial_cells) <= MAX_EFFECT_CELLS:
            raise ValueError("initial cells exceed the finite bound")
        for key, value in initial_cells.items():
            _symbol("initial cell key", key)
            _integer("initial cell value", value)
        active_limits = EffectLimits() if limits is None else limits
        _exact("effect limits", active_limits, EffectLimits)
        entry_records = [entry.canonical_record() for entry in entries]
        if len({entry["admission_decision"]["action_id"] for entry in entry_records}) != len(entries):
            raise ValueError("effect manifest action identities must be unique")
        if len({entry["proposal"]["occurrence_key"] for entry in entry_records}) != len(entries):
            raise ValueError("effect manifest occurrences must be uniquely owned")
        if len({entry["proposal"]["proposal_key"] for entry in entry_records}) != len(entries):
            raise ValueError("effect manifest proposal keys must be unique")
        if any(entry["proposal"]["arguments"]["key"] not in initial_cells for entry in entry_records):
            raise ValueError("effect entry requires a declared initial cell")
        record = {
            "protocol_version": EFFECT_PROFILE_VERSION, "governance_id": governance_id,
            "limits": active_limits.canonical_record(), "initial_cells": initial_cells,
            "entries": entry_records,
        }
        object.__setattr__(self, "_text", canonical_json(_json_copy(record)))

    @property
    def profile_id(self) -> str:
        return domain_fingerprint(EFFECT_PROFILE_ID_DOMAIN, self.canonical_record())

    @property
    def effect_profile_id(self) -> str:
        return self.profile_id

    def canonical_record(self) -> dict:
        record = _read_text(self._text)
        _profile_from_record(record)
        return record

    @classmethod
    def from_record(cls, record: dict) -> EffectProfile:
        return _profile_from_record(_json_copy(record))


_COMMAND_FIELDS = {"protocol_version", "command_type", "effect_session_id", "expected_state_id", "action_id", "occurrence_key"}
_COUNTER_FIELDS = {"requests", "executions", "retries", "reconciliations"}
_SNAPSHOT_FIELDS = {
    "protocol_version", "effect_session_id", "effect_profile_id", "runtime_session_id",
    "task_id", "governance_id", "authority_epoch", "revoked", "generation", "logical_tick",
    "limits", "counters", "cells", "occurrences", "state_id",
}
_RECEIPT_FIELDS = {
    "protocol_version", "effect_session_id", "effect_profile_id", "runtime_session_id",
    "task_id", "governance_id", "authority_epoch", "command_id", "command_type", "action_id",
    "occurrence_key", "tool_admission_receipt_id", "authority_class", "arguments_id", "attempt",
    "status", "ambiguous", "effect_applied", "pre_evidence", "post_evidence", "recovery_of_event_id",
    "event_id", "prior_state_id", "resulting_state_id", "counters", "logical_tick", "cancel_requested",
    "evidence_scope", "failure_reason", "receipt_id",
}
_OBSERVATION_FIELDS = {
    "protocol_version", "effect_session_id", "action_id", "occurrence_key", "attempt", "phase",
    "key", "value", "observation_id",
}


def _effect_session_identity(record: dict) -> None:
    body = {key: record[key] for key in ("effect_profile_id", "runtime_session_id", "task_id", "governance_id")}
    if record["effect_session_id"] != domain_fingerprint("ibae.effect-session-id.v1", body):
        raise ValueError("effect session identity does not match its exact source binding")


def _hashed_record(record: dict, field: str, domain: str) -> None:
    _identity(field, record[field])
    if record[field] != domain_fingerprint(domain, {key: value for key, value in record.items() if key != field}):
        raise ValueError(f"effect {field} does not match its canonical record")


def _counters(record: Any, limits: dict | None = None) -> None:
    active = _fields("effect counters", record, _COUNTER_FIELDS)
    caps = {"requests": MAX_EFFECT_REQUESTS, "executions": MAX_EFFECT_EXECUTIONS,
            "retries": MAX_EFFECT_RETRIES, "reconciliations": MAX_EFFECT_RECONCILIATIONS}
    for key, maximum in caps.items():
        _count(key, active[key], maximum if limits is None else limits["max_" + key])
    if active["executions"] + active["reconciliations"] > active["requests"] or active["retries"] > active["executions"]:
        raise ValueError("effect counters have inconsistent accounting")


def _status(value: Any) -> None:
    _exact("effect status", value, str)
    EffectStatus(value)


def _validate_snapshot(record: dict) -> None:
    _fields("effect snapshot", record, _SNAPSHOT_FIELDS)
    if record["protocol_version"] != EFFECT_SNAPSHOT_VERSION:
        raise ValueError("effect snapshot version mismatch")
    for key in ("effect_session_id", "effect_profile_id", "runtime_session_id", "task_id", "governance_id"):
        _identity(key, record[key])
    for key in ("authority_epoch", "generation", "logical_tick"):
        _count(key, record[key], (1 << 64) - 1)
    _exact("revoked", record["revoked"], bool)
    limits = EffectLimits.from_record(record["limits"]).canonical_record()
    _counters(record["counters"], limits)
    _exact("effect cells", record["cells"], dict)
    if len(record["cells"]) > MAX_EFFECT_CELLS:
        raise ValueError("effect cells exceed bound")
    for key, value in record["cells"].items():
        _symbol("cell key", key)
        _integer("cell value", value)
    _exact("effect occurrences", record["occurrences"], list)
    if not 1 <= len(record["occurrences"]) <= MAX_EFFECT_ENTRIES:
        raise ValueError("effect occurrences exceed bound")
    actions: set[str] = set()
    occurrences: set[str] = set()
    for entry in record["occurrences"]:
        _fields("effect occurrence", entry, {"action_id", "occurrence_key", "status", "attempts", "cancel_requested", "last_event_id"})
        _identity("action id", entry["action_id"])
        _symbol("occurrence key", entry["occurrence_key"])
        _status(entry["status"])
        _count("attempts", entry["attempts"], MAX_EFFECT_OUTCOMES)
        _exact("cancel requested", entry["cancel_requested"], bool)
        if entry["last_event_id"] is not None:
            _identity("last event id", entry["last_event_id"])
        if entry["action_id"] in actions or entry["occurrence_key"] in occurrences:
            raise ValueError("effect occurrence ownership is not unique")
        actions.add(entry["action_id"])
        occurrences.add(entry["occurrence_key"])
    if record["generation"] != record["logical_tick"] or record["logical_tick"] != record["counters"]["requests"]:
        raise ValueError("effect logical clock must match committed commands")
    if sum(entry["attempts"] for entry in record["occurrences"]) != record["counters"]["executions"]:
        raise ValueError("effect occurrence attempts must cover exact execution accounting")
    if record["counters"]["retries"] != record["counters"]["executions"] - sum(entry["attempts"] > 0 for entry in record["occurrences"]):
        raise ValueError("effect retry accounting must match occurrence history")
    for entry in record["occurrences"]:
        if entry["status"] == "cancelled" and not entry["cancel_requested"]:
            raise ValueError("cancelled occurrence must retain its cancellation request")
        if entry["status"] in {"pending", "applied", "not_applied"} and entry["cancel_requested"]:
            raise ValueError("effect occurrence status is inconsistent with cancellation")
        if entry["status"] == "pending":
            if entry["attempts"] != 0 or entry["last_event_id"] is not None or entry["cancel_requested"]:
                raise ValueError("pending effect occurrence cannot retain committed activity")
        elif entry["last_event_id"] is None or (entry["attempts"] == 0 and entry["status"] != "cancelled"):
            raise ValueError("committed effect occurrence requires its event and attempt")
    _effect_session_identity(record)
    _hashed_record(record, "state_id", "ibae.effect-state-id.v1")


@dataclass(frozen=True, slots=True, init=False)
class EffectSnapshot:
    """Copied diagnostic state; never a resume token or final acceptance."""

    _text: str

    def __init__(self, record: dict) -> None:
        copied = _json_copy(record)
        _validate_snapshot(copied)
        object.__setattr__(self, "_text", canonical_json(copied))

    def canonical_record(self) -> dict:
        record = _read_text(self._text)
        _validate_snapshot(record)
        return record

    @property
    def state_id(self) -> str:
        return self.canonical_record()["state_id"]

    @property
    def effect_session_id(self) -> str:
        return self.canonical_record()["effect_session_id"]

    @property
    def applied_count(self) -> int:
        return sum(item["status"] in {"applied", "reconciled_applied"} for item in self.canonical_record()["occurrences"])

    @property
    def manifest_complete(self) -> bool:
        """Every declared occurrence is proven applied; not task finalization."""
        record = self.canonical_record()
        return all(item["status"] in {"applied", "reconciled_applied"} for item in record["occurrences"])

    @property
    def partial(self) -> bool:
        return 0 < self.applied_count < len(self.canonical_record()["occurrences"])


def _observation(record: Any, receipt: dict) -> None:
    if record is None:
        return
    _fields("effect observation", record, _OBSERVATION_FIELDS)
    if record["protocol_version"] != "IBAE-EFFECT-OBSERVATION-V1":
        raise ValueError("effect observation version mismatch")
    for key in ("effect_session_id", "action_id", "occurrence_key", "attempt"):
        if record[key] != receipt[key] or type(record[key]) is not type(receipt[key]):
            raise ValueError("effect observation source binding mismatch")
    _exact("effect observation phase", record["phase"], str)
    if record["phase"] not in {"before", "after", "reconciliation"}:
        raise ValueError("unknown effect observation phase")
    _symbol("observation key", record["key"])
    _integer("observation value", record["value"])
    _hashed_record(record, "observation_id", "ibae.effect-observation-id.v1")


def _validate_receipt(record: dict) -> None:
    _fields("effect receipt", record, _RECEIPT_FIELDS)
    if record["protocol_version"] != "IBAE-EFFECT-RECEIPT-V1" or record["evidence_scope"] != "synthetic-native-in-process":
        raise ValueError("effect receipt version or evidence scope mismatch")
    for key in ("effect_session_id", "effect_profile_id", "runtime_session_id", "task_id", "governance_id", "command_id", "action_id", "tool_admission_receipt_id", "arguments_id", "event_id", "prior_state_id", "resulting_state_id"):
        _identity(key, record[key])
    _symbol("occurrence key", record["occurrence_key"])
    _exact("command type", record["command_type"], str)
    EffectCommand(record["command_type"])
    _status(record["status"])
    _exact("authority class", record["authority_class"], str)
    if record["authority_class"] not in {"idempotent_mutation", "non_idempotent_mutation"}:
        raise ValueError("effect receipt requires mutation authority")
    for key in ("authority_epoch", "logical_tick"):
        _count(key, record[key], (1 << 64) - 1)
    _count("effect attempt", record["attempt"], MAX_EFFECT_OUTCOMES)
    for key in ("ambiguous", "cancel_requested"):
        _exact(key, record[key], bool)
    if record["effect_applied"] is not None:
        _exact("effect applied", record["effect_applied"], bool)
    if record["recovery_of_event_id"] is not None:
        _identity("recovery event id", record["recovery_of_event_id"])
    reason = record["failure_reason"]
    if reason is not None:
        _exact("effect failure reason", reason, str)
        if reason not in {"synthetic_failure_before", "precondition_mismatch", "acknowledgement_lost", "reconciliation_unknown"}:
            raise ValueError("unknown effect failure reason")
    _counters(record["counters"])
    _observation(record["pre_evidence"], record)
    _observation(record["post_evidence"], record)
    if record["status"] == "ambiguous" and (record["effect_applied"] is not None or not record["ambiguous"]):
        raise ValueError("ambiguous effects must retain unknown application status")
    if record["status"] in {"applied", "reconciled_applied"} and (record["effect_applied"] is not True or record["ambiguous"]):
        raise ValueError("applied effects require unambiguous native evidence")
    if record["status"] in {"not_applied", "reconciled_not_applied", "cancelled"} and (record["effect_applied"] is not False or record["ambiguous"]):
        raise ValueError("unapplied effects require unambiguous no-effect evidence")
    if record["status"] == "pending":
        raise ValueError("a pending occurrence is not an effect receipt")
    if record["logical_tick"] != record["counters"]["requests"] or record["logical_tick"] == 0:
        raise ValueError("effect receipt logical clock must match committed commands")
    if record["prior_state_id"] == record["resulting_state_id"]:
        raise ValueError("an effect command receipt must bind a committed state transition")
    if record["attempt"] == 0 and record["status"] != "cancelled":
        raise ValueError("non-cancellation effects require an admitted attempt")
    if record["attempt"] > record["counters"]["executions"] or max(0, record["attempt"] - 1) > record["counters"]["retries"]:
        raise ValueError("effect occurrence attempt exceeds cumulative accounting")
    if record["status"] in {"applied", "not_applied"} and record["cancel_requested"]:
        raise ValueError("effect execution status cannot follow cancellation")
    command = record["command_type"]
    if command == "reconcile_effect" and record["counters"]["reconciliations"] == 0:
        raise ValueError("reconciliation receipt requires consumed reconciliation capacity")
    if command == "cancel_effect" and record["counters"]["executions"] + record["counters"]["reconciliations"] == record["counters"]["requests"]:
        raise ValueError("cancellation receipt requires its own committed request")
    before, after = record["pre_evidence"], record["post_evidence"]
    if before is not None and before["phase"] != "before":
        raise ValueError("effect pre-evidence must be a before observation")
    if after is not None and after["phase"] != ("reconciliation" if command == "reconcile_effect" else "after"):
        raise ValueError("effect post-evidence phase mismatch")
    if before is not None and after is not None and before["key"] != after["key"]:
        raise ValueError("effect pre/post evidence keys must match")
    if command in {"execute_effect", "retry_effect"}:
        if record["status"] not in {"applied", "not_applied", "ambiguous"} or before is None:
            raise ValueError("effect execution requires before evidence and an execution outcome")
        if command == "execute_effect" and (record["attempt"] != 1 or record["recovery_of_event_id"] is not None):
            raise ValueError("initial execution cannot claim a retry occurrence")
        if command == "retry_effect" and (record["attempt"] < 2 or record["recovery_of_event_id"] is None):
            raise ValueError("effect retry must bind its prior event and a later attempt")
        if record["status"] == "ambiguous":
            if after is not None or reason != "acknowledgement_lost":
                raise ValueError("ambiguous execution cannot claim post-effect evidence")
        elif after is None:
            raise ValueError("known execution outcomes require post-effect evidence")
        elif record["status"] == "not_applied":
            if reason not in {"synthetic_failure_before", "precondition_mismatch"} or before["value"] != after["value"]:
                raise ValueError("unapplied effect must preserve before/after state")
        elif reason is not None:
            raise ValueError("applied effect cannot carry a failure reason")
    elif command == "reconcile_effect":
        if before is not None or record["recovery_of_event_id"] is None:
            raise ValueError("reconciliation must bind prior evidence without a new execution")
        if record["status"] == "ambiguous":
            if after is not None or reason != "reconciliation_unknown":
                raise ValueError("unknown reconciliation must retain missing evidence")
        elif record["status"] not in {"reconciled_applied", "reconciled_not_applied"} or after is None or reason is not None:
            raise ValueError("known reconciliation requires exact journal evidence")
    elif command == "cancel_effect":
        if record["status"] not in {"cancelled", "ambiguous"} or not record["cancel_requested"] or before is not None or after is not None or reason is not None:
            raise ValueError("cancellation cannot invent a known external outcome")
    expected_command = {
        "protocol_version": EFFECT_RUNTIME_VERSION, "command_type": command,
        "effect_session_id": record["effect_session_id"], "expected_state_id": record["prior_state_id"],
        "action_id": record["action_id"], "occurrence_key": record["occurrence_key"],
    }
    if record["command_id"] != domain_fingerprint("ibae.effect-command-id.v1", expected_command):
        raise ValueError("effect command identity mismatch")
    event = {key: record[key] for key in (
        "effect_session_id", "command_id", "action_id", "occurrence_key", "attempt", "status",
        "effect_applied", "pre_evidence", "post_evidence", "failure_reason", "cancel_requested",
    )}
    event["generation"] = record["logical_tick"]
    if record["event_id"] != domain_fingerprint("ibae.effect-event-id.v1", event):
        raise ValueError("effect event identity mismatch")
    _effect_session_identity(record)
    _hashed_record(record, "receipt_id", "ibae.effect-receipt-id.v1")


@dataclass(frozen=True, slots=True, init=False)
class EffectReceipt:
    """Immutable recovery/execution evidence; deserialization loses the seal."""

    _text: str
    _seal: Any

    def __init__(self, record: dict, *, _native_seal: Any | None = None) -> None:
        copied = _json_copy(record)
        _validate_receipt(copied)
        text = canonical_json(copied)
        if _native_seal is not None:
            from ._runtime import NativeEffectReceiptSeal
            _exact("native effect receipt seal", _native_seal, NativeEffectReceiptSeal)
            if not _native_seal.validates(text):
                raise ValueError("native effect receipt seal mismatch")
        object.__setattr__(self, "_text", text)
        object.__setattr__(self, "_seal", _native_seal)

    def canonical_record(self) -> dict:
        record = _read_text(self._text)
        _validate_receipt(record)
        if self._seal is not None and not self.source_bound:
            raise ValueError("native effect receipt seal no longer matches")
        return record

    @property
    def source_bound(self) -> bool:
        from ._runtime import NativeEffectReceiptSeal
        return type(self._text) is str and type(self._seal) is NativeEffectReceiptSeal and bool(self._seal.validates(self._text))

    @property
    def receipt_id(self) -> str:
        return self.canonical_record()["receipt_id"]

    @property
    def status(self) -> str:
        return self.canonical_record()["status"]

    @property
    def ambiguous(self) -> bool:
        return self.canonical_record()["ambiguous"]

    @property
    def effect_applied(self) -> bool | None:
        return self.canonical_record()["effect_applied"]


class EffectSession:
    """Narrow facade with no automatic approvals, retries or live adapters.

    ``authorize`` is an explicit trusted-host synthetic control-plane action.
    Its capability and issuance are not evidence that a human authorized an
    external action. Real externally visible effects remain unsupported.
    """

    __slots__ = ("__native",)

    def __init__(self) -> None:
        raise TypeError("use EffectSession.create with the exact native task authority")

    @classmethod
    def create(
        cls, runtime: RustRuntimeSession, supervisor_authority: Any, *,
        profile: EffectProfile, task: TaskReceipt, governance_policy: GovernancePolicy,
        governance: GovernanceReceipt, tool_admissions: tuple[ToolAdmissionReceipt, ...],
        enabled: bool = False,
    ) -> EffectSession:
        if cls is not EffectSession:
            raise TypeError("effect sessions require exact EffectSession")
        _exact("runtime", runtime, RustRuntimeSession)
        _exact("effect profile", profile, EffectProfile)
        _exact("enabled", enabled, bool)
        for name, value, kind in (
            ("task", task, TaskReceipt), ("policy", governance_policy, GovernancePolicy),
            ("governance", governance, GovernanceReceipt),
        ):
            _exact(name, value, kind)
            _inert_record(value)
        _require_governance_binding(governance_policy, task, governance)
        active_profile = profile.canonical_record()
        if active_profile["governance_id"] != governance_policy.governance_id:
            raise ValueError("effect profile is not bound to the active governance")
        if task.acceptance_contract.get("effect_profile_id") != profile.profile_id:
            raise ValueError("original task acceptance must commit the exact effect profile")
        _exact("tool admissions", tool_admissions, tuple)
        if len(tool_admissions) != len(active_profile["entries"]):
            raise ValueError("effect manifest requires exact tool-admission coverage")
        records = []
        for entry, admission in zip(active_profile["entries"], tool_admissions):
            _exact("tool admission", admission, ToolAdmissionReceipt)
            _inert_record(admission)
            checked = _require_tool_admission_binding(governance_policy, task, governance, admission)
            if (
                checked.capability.canonical_record() != entry["capability"]
                or checked.proposal.canonical_record() != entry["proposal"]
                or checked.admission_decision.canonical_record() != entry["admission_decision"]
                or checked.dependency_fingerprint != entry["dependency_state_id"]
            ):
                raise ValueError("governed tool admission does not match the exact effect entry")
            expected_class = ToolAuthorityClass.IDEMPOTENT_MUTATION if checked.tool_name == "synthetic_set" else ToolAuthorityClass.NON_IDEMPOTENT_MUTATION
            if checked.authority_class is not expected_class:
                raise ValueError("synthetic opcode and mutation class do not match")
            records.append(checked.canonical_record())
        spec = _json_copy({
            "protocol_version": EFFECT_RUNTIME_VERSION, "profile": active_profile,
            "task_receipt": task.canonical_record(), "governance_policy": governance_policy.canonical_record(),
            "governance_receipt": governance.canonical_record(), "tool_admissions": records,
        })
        native = runtime._create_effect_session(supervisor_authority, canonical_json(spec), enabled=enabled)
        instance = object.__new__(cls)
        instance.__native = native
        return instance

    @property
    def snapshot(self) -> EffectSnapshot:
        return EffectSnapshot(_read_text(self.__native.snapshot()))

    def command(self, kind: EffectCommand, action_id: str) -> dict:
        """Prepare inert exact-state command data without issuing approval."""
        _exact("effect command", kind, EffectCommand)
        _identity("effect action id", action_id)
        snapshot = self.snapshot.canonical_record()
        occurrence = next((entry for entry in snapshot["occurrences"] if entry["action_id"] == action_id), None)
        if occurrence is None:
            raise ValueError("unknown effect action")
        return {
            "protocol_version": EFFECT_RUNTIME_VERSION, "command_type": kind.value,
            "effect_session_id": snapshot["effect_session_id"], "expected_state_id": snapshot["state_id"],
            "action_id": action_id, "occurrence_key": occurrence["occurrence_key"],
        }

    @staticmethod
    def _command_text(command: dict) -> str:
        copied = _json_copy(command)
        _fields("effect command", copied, _COMMAND_FIELDS)
        if copied["protocol_version"] != EFFECT_RUNTIME_VERSION:
            raise ValueError("effect command version mismatch")
        _exact("effect command type", copied["command_type"], str)
        EffectCommand(copied["command_type"])
        for key in ("effect_session_id", "expected_state_id", "action_id"):
            _identity(key, copied[key])
        _symbol("effect occurrence", copied["occurrence_key"])
        return canonical_json(copied)

    def authorize(self, command: dict, supervisor_authority: Any) -> Any:
        """Issue one exact synthetic command approval; never approve implicitly."""
        return self.__native.authorize(self._command_text(command), supervisor_authority)

    def dispatch(self, command: dict, approval: Any) -> EffectReceipt:
        from ._runtime import NativeEffectApprovalSeal
        _exact("effect approval", approval, NativeEffectApprovalSeal)
        text, seal = self.__native.dispatch(self._command_text(command), approval)
        return EffectReceipt(_read_text(text), _native_seal=seal)

    def validates_receipt(self, receipt: EffectReceipt) -> bool:
        """Verify exact in-process source ownership, not merely equal IDs."""
        _exact("effect receipt", receipt, EffectReceipt)
        if not receipt.source_bound:
            return False
        return bool(self.__native.validates_receipt(canonical_json(receipt.canonical_record()), receipt._seal))


def _entry_from_record(record: dict) -> EffectEntry:
    """Reconstruct every legacy record rather than trusting its serialized IDs."""
    _fields("effect entry", record, {"capability", "proposal", "admission_decision", "dependency_state_id", "outcomes"})
    cap = _fields("effect capability", record["capability"], {
        "argument_schema", "available", "capability_id", "contract_version", "description", "name",
        "replay_evidence_id", "replay_safety", "required_state_keys", "semantic_argument_keys",
    })
    prop = _fields("effect proposal", record["proposal"], {
        "arguments", "capability", "epistemic_class", "occurrence_key", "proposal_key", "required_state_keys", "target_obligation_ids",
    })
    decision = _fields("effect admission decision", record["admission_decision"], {
        "action_id", "authority_layer", "blocking_obligation_ids", "dependency_state_keys", "equivalent_proposal_id",
        "logical_tick", "invariant_ids", "proposal_id", "proposal_key", "recovery_actions", "rejection_reason", "status", "unresolved_state_keys",
    })
    for value in (cap["required_state_keys"], cap["semantic_argument_keys"], prop["required_state_keys"], prop["target_obligation_ids"],
                  decision["blocking_obligation_ids"], decision["dependency_state_keys"], decision["invariant_ids"], decision["recovery_actions"], decision["unresolved_state_keys"], record["outcomes"]):
        _exact("effect declaration array", value, list)
    capability = Capability(
        name=cap["name"], replay_safety=ReplaySafety(cap["replay_safety"]), description=cap["description"],
        available=cap["available"], contract_version=cap["contract_version"], required_state_keys=tuple(cap["required_state_keys"]),
        semantic_argument_keys=tuple(cap["semantic_argument_keys"]), replay_evidence_id=cap["replay_evidence_id"],
    )
    proposal = ActionProposal(prop["proposal_key"], prop["capability"], prop["arguments"],
        target_obligation_ids=tuple(prop["target_obligation_ids"]), required_state_keys=tuple(prop["required_state_keys"]), occurrence_key=prop["occurrence_key"])
    admitted = AdmissionDecision(
        proposal_id=decision["proposal_id"], proposal_key=decision["proposal_key"], status=DecisionStatus(decision["status"]),
        logical_tick=decision["logical_tick"], authority_layer=AuthorityLayer(decision["authority_layer"]),
        invariant_ids=tuple(decision["invariant_ids"]), action_id=decision["action_id"], equivalent_proposal_id=decision["equivalent_proposal_id"],
        rejection_reason=None if decision["rejection_reason"] is None else RejectionReason(decision["rejection_reason"]),
        recovery_actions=tuple(RecoveryAction(item) for item in decision["recovery_actions"]), blocking_obligation_ids=tuple(decision["blocking_obligation_ids"]),
        dependency_state_keys=tuple(decision["dependency_state_keys"]), unresolved_state_keys=tuple(decision["unresolved_state_keys"]),
    )
    entry = EffectEntry(capability, proposal, admitted, record["dependency_state_id"], tuple(SyntheticEffectOutcome(item) for item in record["outcomes"]))
    if _read_text(entry._text) != record:
        raise ValueError("effect entry canonical field/identity mismatch")
    return entry


def _profile_from_record(record: dict) -> EffectProfile:
    _fields("effect profile", record, {"protocol_version", "governance_id", "limits", "initial_cells", "entries"})
    if record["protocol_version"] != EFFECT_PROFILE_VERSION:
        raise ValueError("effect profile version mismatch")
    _exact("effect profile entries", record["entries"], list)
    if not 1 <= len(record["entries"]) <= MAX_EFFECT_ENTRIES:
        raise ValueError("effect entries exceed finite bound")
    profile = EffectProfile(record["governance_id"], tuple(_entry_from_record(entry) for entry in record["entries"]),
        initial_cells=record["initial_cells"], limits=EffectLimits.from_record(record["limits"]))
    if _read_text(profile._text) != record:
        raise ValueError("effect profile canonical field mismatch")
    return profile
