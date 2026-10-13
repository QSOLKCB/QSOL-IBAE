"""Bounded v0.6A supervisor observations and in-process recovery classification.

Nothing serialized here grants authority or reconstructs a runtime.  All live
decisions re-enter exact source-bound native lineage verification.  The legal
surface describes *proposal classes*, not permission to execute an arbitrary
proposal, bypass governance, or accept a final result.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final

from ._records import CanonicalValue, bounded_utf8_length, require_fingerprint, require_symbol
from .assurance import CalibrationBinding
from .canonical import canonical_json, domain_fingerprint
from .continuation import (
    ContinuationPolicy, ContinuationPolicyReceipt, ContinuationState,
    CycleEvidence, LeaseDenialReason, ProgressClassification, ProgressState,
    _validate_orchestration_authority,
)
from .governance import (
    GovernancePolicy, GovernanceReceipt, PrincipalAuthority, ProviderAuthority,
    MAX_TOOL_PERMISSIONS, TaskReceipt, ToolAuthorityClass, ToolPermission, _require_governance_binding,
)
from .obligations import ObligationReadiness, ObligationStatus
from .orchestration import OrchestrationState, ReplaySafety
from .runtime import RustRuntimeSession

SUPERVISOR_PROJECTION_VERSION: Final = "IBAE-SUPERVISOR-PROJECTION-V1"
FRESH_CONTEXT_VERSION: Final = "IBAE-FRESH-CONTEXT-V1"
RECOVERY_VERSION: Final = "IBAE-RECOVERY-CLASSIFICATION-V1"
# Covers 128 compact obligations, 64 compact capabilities, 256 epistemic
# references and 16 x 4,096-byte data strings even at 6x JSON escaping. Dense
# DAG edges, semantic argument lists, full values and runtime history stay at
# the source; their identities/counts retain the relevant decision facts.
MAX_SUPERVISOR_PROJECTION_BYTES: Final = 1_048_576
MAX_FRESH_CONTEXT_BYTES: Final = MAX_SUPERVISOR_PROJECTION_BYTES + 1_024
MAX_DATA_ITEMS: Final = 16
MAX_DATA_TEXT_BYTES: Final = 4_096
_PROJECTION_DOMAIN: Final = "ibae.supervisor-projection-id.v1"
_HANDOFF_DOMAIN: Final = "ibae.fresh-context-id.v1"


def _exact(name: str, value: Any, kind: type) -> None:
    if type(value) is not kind:
        raise TypeError(f"{name} must have exact type {kind.__name__}")


def _json_copy(value: Any, *, limit: int) -> Any:
    """Copy inert JSON only, bounded before canonical serialization."""
    remaining = [65_536]
    serialized_bytes = [0]

    def charge(count: int) -> None:
        serialized_bytes[0] += count
        if serialized_bytes[0] > limit:
            raise ValueError("supervisor record exceeds aggregate serialized byte bound")

    def copy(item: Any, depth: int) -> Any:
        remaining[0] -= 1
        if remaining[0] < 0 or depth > 24:
            raise ValueError("supervisor record exceeds structural bounds")
        kind = type(item)
        if kind is str:
            charge(2)
            for character in item:
                point = ord(character)
                if 0xD800 <= point <= 0xDFFF:
                    raise ValueError("supervisor text contains an unpaired surrogate")
                if character in {'"', "\\", "\b", "\f", "\n", "\r", "\t"}:
                    charge(2)
                elif point <= 0x1F:
                    charge(6)
                else:
                    charge(1 if point <= 0x7F else 2 if point <= 0x7FF else 3 if point <= 0xFFFF else 4)
            return item
        if item is None or kind is bool:
            charge(4 if item is None or item is True else 5)
            return item
        if kind is int:
            if not 0 <= item <= (1 << 256) - 1:
                raise ValueError("supervisor integers must be bounded and nonnegative")
            charge(len(str(item)))
            return item
        if kind is list:
            if len(item) > 1_024:
                raise ValueError("supervisor array exceeds bound")
            charge(2 + max(0, len(item) - 1))
            return [copy(child, depth + 1) for child in item]
        if kind is dict:
            if len(item) > 128 or any(type(key) is not str for key in item):
                raise ValueError("supervisor object has invalid keys or size")
            charge(2 + len(item) + max(0, len(item) - 1))
            return {copy(key, depth + 1): copy(child, depth + 1) for key, child in item.items()}
        raise TypeError("supervisor records require inert exact JSON types")

    result = copy(value, 0)
    bounded_utf8_length("supervisor record", canonical_json(result), limit=limit)
    return result


def _fields(value: Any, names: set[str], label: str) -> dict:
    _exact(label, value, dict)
    if set(value) != names:
        raise ValueError(f"{label} does not match the versioned schema")
    return value


def _shape(value: Any, schema: Any, label: str = "supervisor field") -> None:
    """Validate the closed transport schema, without coercing parsed values."""
    if type(schema) is dict:
        _fields(value, set(schema), label)
        for name, rule in schema.items():
            _shape(value[name], rule, name)
    elif type(schema) is tuple:
        if schema[0] == "optional":
            if value is not None:
                _shape(value, schema[1], label)
        elif schema[0] == "array":
            _exact(label, value, list)
            if len(value) > schema[2]:
                raise ValueError(f"{label} exceeds collection bound")
            for item in value:
                _shape(item, schema[1], label)
            if len(schema) > 3:
                keys = [item[schema[3]] if schema[3] else item for item in value]
                if keys != sorted(set(keys)):
                    raise ValueError(f"{label} must be canonically ordered and unique")
        elif schema[0] == "enum":
            _exact(label, value, str)
            if value not in schema[1]:
                raise ValueError(f"{label} has unknown enum value")
    elif schema == "fingerprint":
        _exact(label, value, str)
        require_fingerprint(label, value)
    elif schema == "symbol":
        _exact(label, value, str)
        require_symbol(label, value)
    elif schema == "u64":
        _exact(label, value, int)
        if not 0 <= value <= (1 << 64) - 1:
            raise ValueError(f"{label} is outside u64")
    elif schema in (str, bool, int):
        _exact(label, value, schema)
    else:
        if type(value) is not type(schema) or value != schema:
            raise ValueError(f"{label} has invalid constant value")


class DataOrigin(str, Enum):
    MODEL_OUTPUT = "model_output"
    WEB_PAGE = "web_page"
    REPOSITORY_CONTENT = "repository_content"
    DOCUMENT = "document"
    TOOL_OUTPUT = "tool_output"
    WORKER_OUTPUT = "worker_output"
    OCR_UI_TEXT = "ocr_ui_text"
    DOWNLOAD = "download"
    BENCHMARK_REPORT = "benchmark_report"
    EXTERNAL_RECEIPT = "external_receipt"


@dataclass(frozen=True, slots=True)
class SupervisorData:
    """Hostile text is inspectable data with no control-plane authority."""

    origin: DataOrigin
    source_id: str
    text: str

    def canonical_record(self) -> dict:
        self.__post_init__()
        return {"origin": self.origin.value, "source_id": self.source_id,
                "text": self.text, "control_authority": False}

    def __post_init__(self) -> None:
        _exact("data origin", self.origin, DataOrigin)
        _exact("data source id", self.source_id, str)
        require_fingerprint("data source id", self.source_id)
        _exact("data text", self.text, str)
        bounded_utf8_length("data text", self.text, limit=MAX_DATA_TEXT_BYTES)


@dataclass(frozen=True, slots=True)
class SupervisorContext:
    """References to existing live authorities, never a serialized authority."""

    task: TaskReceipt
    governance: GovernanceReceipt
    governance_policy: GovernancePolicy
    continuation_policy: ContinuationPolicy
    continuation_state: ContinuationState
    orchestration_state: OrchestrationState
    runtime_session: RustRuntimeSession
    supervisor_authority: Any | None = None
    calibration: CalibrationBinding | None = None

    def _validate(self) -> tuple[Any, dict]:
        for name, kind in (
            ("task", TaskReceipt), ("governance", GovernanceReceipt),
            ("governance_policy", GovernancePolicy), ("continuation_policy", ContinuationPolicy),
            ("continuation_state", ContinuationState), ("orchestration_state", OrchestrationState),
            ("runtime_session", RustRuntimeSession),
        ):
            _exact(name, getattr(self, name), kind)
        policy = self.governance_policy
        for name in ("policy_key", "task_profile"):
            _exact(name, getattr(policy, name), str)
        for name in ("policy_version", "task_profile_version"):
            _exact(name, getattr(policy, name), int)
        for name in ("supervisor_authority", "worker_authority", "orchestration_authority", "runtime_authority"):
            _exact(name, getattr(policy, name), PrincipalAuthority)
        _exact("provider authority", policy.provider_authority, ProviderAuthority)
        _exact("tool permissions", policy.tool_permissions, tuple)
        if len(policy.tool_permissions) > MAX_TOOL_PERMISSIONS:
            raise ValueError("too many tool permissions")
        for permission in policy.tool_permissions:
            _exact("tool permission", permission, ToolPermission)
            _exact("tool name", permission.tool_name, str)
            _exact("tool authority class", permission.authority_class, ToolAuthorityClass)
            _exact("mutation permission", permission.allow_mutation, bool)
            _exact("reuse permission", permission.allow_cache_reuse, bool)
        for owner in (policy, self.task, self.governance):
            _exact("required gates", owner.required_gate_keys, tuple)
            if len(owner.required_gate_keys) > 64:
                raise ValueError("too many required gates")
            for key in owner.required_gate_keys:
                _exact("gate key", key, str)
        _exact("task key", self.task.task_key, str)
        _exact("contract version", self.task.contract_version, int)
        _exact("acceptance contract", self.task._acceptance_contract, CanonicalValue)
        _exact("acceptance contract text", self.task._acceptance_contract.text, str)
        for name in ("task_id", "task_receipt_id", "governance_id", "policy_key", "task_profile"):
            _exact(name, getattr(self.governance, name), str)
        for name in ("policy_version", "task_profile_version"):
            _exact(name, getattr(self.governance, name), int)
        _exact("governance requester", self.governance.requester, PrincipalAuthority)
        _exact("governance provider", self.governance.provider_authority, ProviderAuthority)
        _require_governance_binding(policy, self.task, self.governance)
        _validate_orchestration_authority(self.orchestration_state)
        state = self.continuation_state
        state._require_policy(self.continuation_policy)
        expected = ContinuationPolicyReceipt(self.continuation_policy, policy, self.governance)
        if (state.task_id != self.task.task_id or state.governance_id != policy.governance_id
                or state.governance_receipt_id != self.governance.receipt_id
                or state.continuation_policy_receipt_id != expected.receipt_id
                or state.orchestration_state_id != self.orchestration_state.state_id):
            raise ValueError("supervisor context does not bind exact live sources")
        snapshot = self.runtime_session.snapshot
        self.runtime_session._validate_continuation_checkpoint_snapshot(
            state._native_lineage_seal(), state, snapshot,
        )
        if (snapshot.session_id != state.runtime_session_id
                or snapshot.state_id != state.runtime_state_id):
            raise ValueError("supervisor runtime endpoint is stale")
        status = self.runtime_session.continuation_authority_status(self.supervisor_authority, state)
        if self.calibration is not None:
            _exact("calibration binding", self.calibration, CalibrationBinding)
            self.calibration.require_policy_binding(
                state.governance_id, state.continuation_policy_id, state.progress_contract_id,
            )
        return snapshot, status


def _projection_record(context: SupervisorContext, data: tuple[SupervisorData, ...]) -> dict:
    _exact("context", context, SupervisorContext)
    _exact("data", data, tuple)
    if len(data) > MAX_DATA_ITEMS:
        raise ValueError("too many supervisor data items")
    data_records = []
    for item in data:
        _exact("data item", item, SupervisorData)
        data_records.append(item.canonical_record())
    # Data is never read by the policy/eligibility derivation below.
    snapshot, authority = context._validate()
    state, policy, orchestration = context.continuation_state, context.continuation_policy, context.orchestration_state
    continuation = state.compact_projection(policy)
    active = context.supervisor_authority is not None and not authority["revoked"]
    cycle = CycleEvidence.from_snapshot(snapshot)
    blocked_denials = {
        LeaseDenialReason.BLOCKING_GOVERNANCE_VIOLATION, LeaseDenialReason.UNAUTHORIZED_REQUESTER,
        LeaseDenialReason.STALE_CONTINUATION_STATE, LeaseDenialReason.STALE_GOVERNANCE,
        LeaseDenialReason.STALE_ORCHESTRATION_STATE, LeaseDenialReason.STALE_RUNTIME_STATE,
        LeaseDenialReason.STALE_PROGRESS, LeaseDenialReason.LEASE_INDEX_MISMATCH,
    }
    governance_blocked = state.last_denial_reason in blocked_denials
    control = ("revoked" if authority["revoked"] else "authorization_required" if not active
               else "governance_blocked" if governance_blocked
               else "complete" if state.progress_state is ProgressState.COMPLETE
               else "cycle_blocked" if cycle is not None
               else "pending_lease" if state.has_pending_grant
               else state.progress_state.value)
    budgets = {
        "requests_remaining": snapshot.limits.max_requests - snapshot.requests,
        "executions_remaining": snapshot.limits.max_executions - snapshot.executions,
        "retries_remaining": snapshot.limits.max_retries - snapshot.retries,
        "mutations_remaining": 0,
        "history_capacity": snapshot.limits.max_history,
        "history_retained": len(snapshot.history),
        "history_unused_slots": snapshot.limits.max_history - len(snapshot.history),
        "lease_requests_remaining": continuation["lease_requests_remaining"],
        "lease_schedule_slots_remaining": continuation["lease_schedule_slots_remaining"],
        "leases_remaining": continuation["leases_remaining"],
        "progress_observations_remaining": continuation["progress_observations_remaining"],
        "strategy_recoveries_remaining": policy.max_strategy_recoveries - state.strategy_recoveries,
        "continuation_ceiling_remaining": continuation["remaining_total_continuation_ceiling"],
        "orchestration_capacity": {
            "obligations": orchestration.limits.max_obligations - len(orchestration.obligations.obligations),
            "capabilities": orchestration.limits.max_capabilities - len(orchestration.capabilities),
            "epistemic_records": orchestration.limits.max_epistemic_records - len(orchestration.epistemic_state.records),
            "occurrence_owners": orchestration.limits.max_occurrence_owners - len(orchestration.occurrence_owners),
            "strategy_schemas": orchestration.limits.max_strategy_schemas - len(orchestration.strategy_schemas),
            "max_batch_proposals": orchestration.limits.max_batch_proposals,
        },
    }
    obligations = []
    for obligation in orchestration.obligations.obligations:
        obligations.append({
            "obligation_id": obligation.obligation_id, "key": obligation.key,
            "status": obligation.status.value,
            "readiness": orchestration.obligations.readiness(obligation.obligation_id).value,
            "blocking_dependency_count": len(orchestration.obligations.blocking_dependency_ids(obligation.obligation_id)),
            "blocking_dependency_set_id": domain_fingerprint("ibae.supervisor-blocking-dependencies.v1",
                list(orchestration.obligations.blocking_dependency_ids(obligation.obligation_id))),
            "block_reason_data_id": None if obligation.block_reason is None else domain_fingerprint(
                "ibae.supervisor-blocker-data.v1", {"text": obligation.block_reason}),
        })
    ready = list(orchestration.obligations.ready_ids)
    can_propose = active and not governance_blocked and not state.has_pending_grant and state.progress_state is not ProgressState.COMPLETE
    capabilities = []
    for capability in orchestration.capabilities:
        permission = context.governance_policy.permission_for(capability.name)
        unresolved = orchestration.epistemic_state.unresolved_keys(capability.required_state_keys)
        supported = capability.replay_safety is ReplaySafety.CACHEABLE_READ and permission is not None and permission.authority_class in {
            ToolAuthorityClass.PURE_READ, ToolAuthorityClass.SNAPSHOT_READ,
        }
        capabilities.append({
            "capability_id": capability.capability_id, "name": capability.name,
            "available": capability.available, "replay_safety": capability.replay_safety.value,
            "semantic_argument_count": len(capability.semantic_argument_keys),
            "required_state_count": len(capability.required_state_keys),
            "unresolved_state_count": len(unresolved),
            "unresolved_state_set_id": domain_fingerprint("ibae.supervisor-unresolved-state.v1", list(unresolved)),
            "permission_id": None if permission is None else permission.permission_id,
            "granted_authority_class": None if permission is None else permission.authority_class.value,
            "cache_reuse_granted": permission is not None and permission.allow_cache_reuse,
            "runtime_supported": supported,
            "read_proposal_eligible": bool(can_propose and ready and capability.available and not unresolved
                and supported and budgets["requests_remaining"] > 0 and budgets["executions_remaining"] > 0),
            "cache_reuse_proposal_eligible": bool(can_propose and ready and capability.available and not unresolved
                and supported and permission.allow_cache_reuse and budgets["requests_remaining"] > 0 and snapshot.cache),
        })
    request_eligible = bool(active and not governance_blocked and not state.has_pending_grant
        and state.progress_state is not ProgressState.COMPLETE and continuation["leases_remaining"] > 0)
    lease_eligible = bool(request_eligible and cycle is None
        and state.last_progress_classification is ProgressClassification.MEASURABLE_PROGRESS
        and state.last_progress_id != state.last_consumed_progress_id)
    terminal_denial_eligible = bool(active and not governance_blocked and not state.has_pending_grant
        and state.progress_state is not ProgressState.COMPLETE and state.last_progress_id is not None
        and continuation["leases_remaining"] == 0 and state.terminal_ceiling_receipt_id is None
        and state.last_denial_reason not in {LeaseDenialReason.LEASE_CEILING_REACHED, LeaseDenialReason.LEASE_REQUEST_LIMIT})
    recovery = list(continuation["legal_recovery_actions"]) if active and not governance_blocked else []
    strategy_eligible = bool(active and continuation["material_strategy_change_admissible"])
    if cycle is not None and strategy_eligible and not state.has_pending_grant:
        recovery = ["propose_cycle_breaking_strategy"]
    actions = ["inspect_bound_evidence", "stop"]
    if not active or governance_blocked:
        actions.append("ask_human_authorization")
    if any(item["read_proposal_eligible"] for item in capabilities):
        actions.append("propose_governed_read")
    if any(item["cache_reuse_proposal_eligible"] for item in capabilities):
        actions.append("propose_cache_reuse_subject_to_exact_key_match")
    if lease_eligible:
        actions.append("request_progress_lease")
    if strategy_eligible:
        actions.append("propose_material_strategy_change")
    if active and not governance_blocked and state.has_pending_grant:
        actions.append("apply_pending_lease")
    if terminal_denial_eligible:
        actions.append("record_terminal_continuation_denial")
    complete = state.progress_state is ProgressState.COMPLETE
    if active and not governance_blocked and complete:
        actions.append("propose_completion_for_gate_validation")
    if can_propose and budgets["progress_observations_remaining"] > 0:
        actions.append("observe_bound_progress")
    sources = {
        "task_id": context.task.task_id, "task_receipt_id": context.task.receipt_id,
        "governance_id": context.governance.governance_id, "governance_receipt_id": context.governance.receipt_id,
        "orchestration_state_id": state.orchestration_state_id,
        "runtime_session_id": snapshot.session_id, "runtime_state_id": snapshot.state_id,
        "continuation_state_id": state.continuation_state_id,
        "continuation_policy_id": state.continuation_policy_id,
        "continuation_policy_receipt_id": state.continuation_policy_receipt_id,
        "progress_contract_id": state.progress_contract_id,
        "progress_evidence_id": state.last_progress_id,
        "progress_aggregate_id": state.progress_aggregate_id,
        "decision_aggregate_id": state.decision_aggregate_id,
        "strategy_material_id": state.current_strategy_material_id,
        "calibration_profile_id": None if context.calibration is None else context.calibration.profile_id,
    }
    surface = {
        "authority": {**authority, "supervisor_capability_present": context.supervisor_authority is not None,
                      "control_provenance": "exact-live-native-lineage-and-governed-policy"},
        "control_classification": control,
        "legal_next_action_classes": sorted(set(actions)),
        "ready_obligation_ids": ready,
        "blocked_obligation_ids": [item["obligation_id"] for item in obligations if item["readiness"] in {
            ObligationReadiness.EXPLICITLY_BLOCKED.value, ObligationReadiness.DEPENDENCY_BLOCKED.value}],
        "obligations": obligations, "capabilities": capabilities, "budgets": budgets,
        "completion": {"eligible_for_gate_validation": complete, "final_acceptance": False,
                       "required_gate_keys": list(context.task.required_gate_keys)},
        "continuation": {**continuation, "request_eligible": request_eligible,
                         "progress_lease_eligible": lease_eligible,
                         "terminal_denial_recording_eligible": terminal_denial_eligible,
                         "material_strategy_change_admissible": strategy_eligible,
                         "legal_recovery_actions": sorted(set(recovery)),
                         "cycle_evidence_id": None if cycle is None else cycle.cycle_evidence_id},
        "epistemic": [{"key": item.key, "epistemic_class": item.epistemic_class.value,
                       "record_id": item.record_id if item.is_resolved else None, "dependency_resolved": item.is_resolved}
                      for item in orchestration.epistemic_state.records],
        "strategy_schema_ids": sorted(item.schema_id for item in orchestration.strategy_schemas),
    }
    return {"protocol_version": SUPERVISOR_PROJECTION_VERSION, "authoritative": False,
            "trust_scope": "structural-in-process-lineage-only", "sources": sources,
            "decision_surface": surface, "data": data_records}


@dataclass(frozen=True, slots=True, init=False)
class SupervisorProjection:
    _text: str
    _source_runtime: RustRuntimeSession = field(repr=False, compare=False)
    _source_lineage: Any = field(repr=False, compare=False)

    def __init__(self, context: SupervisorContext, *, data: tuple[SupervisorData, ...] = ()) -> None:
        record = _json_copy(_projection_record(context, data), limit=MAX_SUPERVISOR_PROJECTION_BYTES)
        object.__setattr__(self, "_text", canonical_json(record))
        object.__setattr__(self, "_source_runtime", context.runtime_session)
        object.__setattr__(self, "_source_lineage", context.continuation_state._native_lineage_seal())

    def canonical_record(self) -> dict:
        _exact("projection text", self._text, str)
        bounded_utf8_length("projection", self._text, limit=MAX_SUPERVISOR_PROJECTION_BYTES)
        return _validate_projection(json.loads(self._text))

    @property
    def projection_id(self) -> str:
        return domain_fingerprint(_PROJECTION_DOMAIN, self.canonical_record())

    @property
    def decision_surface(self) -> dict:
        return self.canonical_record()["decision_surface"]


def _validate_projection(value: Any) -> dict:
    value = _json_copy(value, limit=MAX_SUPERVISOR_PROJECTION_BYTES)
    _fields(value, {"protocol_version", "authoritative", "trust_scope", "sources", "decision_surface", "data"}, "projection")
    if (value["protocol_version"] != SUPERVISOR_PROJECTION_VERSION or value["authoritative"] is not False
            or value["trust_scope"] != "structural-in-process-lineage-only"):
        raise ValueError("invalid projection version or trust claim")
    sources = _fields(value["sources"], {
        "task_id", "task_receipt_id", "governance_id", "governance_receipt_id", "orchestration_state_id",
        "runtime_session_id", "runtime_state_id", "continuation_state_id", "continuation_policy_id",
        "continuation_policy_receipt_id", "progress_contract_id", "progress_evidence_id", "progress_aggregate_id",
        "decision_aggregate_id", "strategy_material_id", "calibration_profile_id",
    }, "projection sources")
    for name, identity in sources.items():
        if identity is None and name in {"progress_evidence_id", "strategy_material_id", "calibration_profile_id"}:
            continue
        require_fingerprint(name, identity)
    surface = _fields(value["decision_surface"], {
        "authority", "control_classification", "legal_next_action_classes", "ready_obligation_ids",
        "blocked_obligation_ids", "obligations", "capabilities", "budgets", "completion", "continuation",
        "epistemic", "strategy_schema_ids",
    }, "decision surface")
    authority = _fields(surface["authority"], {
        "protocol_version", "task_id", "governance_id", "continuation_policy_id", "runtime_session_id",
        "authority_epoch", "revoked", "authority_epoch_status_id", "supervisor_capability_present", "control_provenance",
    }, "authority status")
    optional_id = ("optional", "fingerprint")
    id_set = ("array", "fingerprint", 256, "")
    symbol_set = ("array", "symbol", 64, "")
    vector = {key: "u64" for key in ("execution_delta", "history_delta", "mutation_delta", "request_delta", "retry_delta")}
    _shape(authority, {
        "protocol_version": "IBAE-AUTHORITY-EPOCH-V1", "task_id": "fingerprint", "governance_id": "fingerprint",
        "continuation_policy_id": "fingerprint", "runtime_session_id": "fingerprint", "authority_epoch": "u64",
        "revoked": bool, "authority_epoch_status_id": "fingerprint", "supervisor_capability_present": bool,
        "control_provenance": "exact-live-native-lineage-and-governed-policy",
    })
    native_status = {key: item for key, item in authority.items()
                     if key not in {"authority_epoch_status_id", "supervisor_capability_present", "control_provenance"}}
    if authority["authority_epoch_status_id"] != domain_fingerprint("ibae.authority-epoch-status-id.v1", native_status):
        raise ValueError("authority status identity mismatch")
    for name in ("task_id", "governance_id", "continuation_policy_id", "runtime_session_id"):
        if authority[name] != sources[name]:
            raise ValueError("authority status does not bind projection sources")
    _shape(surface["control_classification"], ("enum", {item.value for item in ProgressState} | {
        "revoked", "authorization_required", "governance_blocked", "pending_lease"}))
    _shape(surface["legal_next_action_classes"], ("array", ("enum", {
        "inspect_bound_evidence", "stop", "ask_human_authorization", "propose_governed_read",
        "propose_cache_reuse_subject_to_exact_key_match", "request_progress_lease", "propose_material_strategy_change",
        "apply_pending_lease", "propose_completion_for_gate_validation", "observe_bound_progress", "record_terminal_continuation_denial",
    }), 16, ""))
    for name in ("ready_obligation_ids", "blocked_obligation_ids", "strategy_schema_ids"):
        _shape(surface[name], id_set, name)
    _shape(surface["obligations"], ("array", {
        "obligation_id": "fingerprint", "key": "symbol", "status": ("enum", {item.value for item in ObligationStatus}),
        "readiness": ("enum", {item.value for item in ObligationReadiness}), "blocking_dependency_count": "u64",
        "blocking_dependency_set_id": "fingerprint", "block_reason_data_id": optional_id,
    }, 128, "obligation_id"))
    _shape(surface["capabilities"], ("array", {
        "capability_id": "fingerprint", "name": "symbol", "available": bool,
        "replay_safety": ("enum", {item.value for item in ReplaySafety}),
        "semantic_argument_count": "u64", "required_state_count": "u64", "unresolved_state_count": "u64",
        "unresolved_state_set_id": "fingerprint", "permission_id": optional_id,
        "granted_authority_class": ("optional", ("enum", {item.value for item in ToolAuthorityClass})),
        "runtime_supported": bool, "cache_reuse_granted": bool, "read_proposal_eligible": bool,
        "cache_reuse_proposal_eligible": bool,
    }, 64, "name"))
    _shape(surface["budgets"], {
        **{name: "u64" for name in (
            "requests_remaining", "executions_remaining", "retries_remaining", "history_capacity", "history_retained",
            "history_unused_slots", "lease_requests_remaining", "lease_schedule_slots_remaining", "leases_remaining",
            "progress_observations_remaining", "strategy_recoveries_remaining")},
        "mutations_remaining": 0, "continuation_ceiling_remaining": vector,
        "orchestration_capacity": {name: "u64" for name in (
            "obligations", "capabilities", "epistemic_records", "occurrence_owners", "strategy_schemas", "max_batch_proposals")},
    })
    _shape(surface["completion"], {"eligible_for_gate_validation": bool, "final_acceptance": False,
                                    "required_gate_keys": symbol_set})
    _shape(surface["continuation"], {
        "continuation_policy_id": "fingerprint", "progress_contract_id": "fingerprint", "continuation_state_id": "fingerprint",
        "current_progress_classification": ("optional", ("enum", {item.value for item in ProgressClassification})),
        "current_progress_evidence_id": optional_id, "last_denial_reason": ("optional", ("enum", {item.value for item in LeaseDenialReason})),
        "last_lease_decision": ("enum", {"none", "granted", "denied"}),
        **{name: "u64" for name in ("lease_requests_remaining", "lease_schedule_slots_remaining", "leases_remaining", "leases_used",
                                    "progress_observations_remaining")},
        "legal_recovery_actions": ("array", ("enum", {"provide_objective_progress", "propose_material_strategy_change",
            "propose_cycle_breaking_strategy", "provide_material_semantic_difference", "apply_pending_lease"}), 8, ""),
        "material_strategy_change_admissible": bool, "pending_grant_receipt_id": optional_id,
        "progress_state": ("enum", {item.value for item in ProgressState}),
        "remaining_total_continuation_ceiling": vector, "terminal_ceiling_receipt_id": optional_id,
        "request_eligible": bool, "progress_lease_eligible": bool, "terminal_denial_recording_eligible": bool,
        "cycle_evidence_id": optional_id,
    })
    _shape(surface["epistemic"], ("array", {"key": "symbol", "epistemic_class": ("enum", {
        "observed", "derived", "model_proposed", "unknown"}), "record_id": optional_id, "dependency_resolved": bool}, 256, "key"))
    for key, source_key in (("continuation_policy_id", "continuation_policy_id"), ("progress_contract_id", "progress_contract_id"),
                            ("continuation_state_id", "continuation_state_id"), ("current_progress_evidence_id", "progress_evidence_id")):
        if surface["continuation"][key] != sources[source_key]:
            raise ValueError("continuation surface does not bind projection sources")
    _exact("authority epoch", authority["authority_epoch"], int)
    if authority["authority_epoch"] > (1 << 64) - 1:
        raise ValueError("authority epoch exceeds u64")
    for name in ("revoked", "supervisor_capability_present"):
        _exact(name, authority[name], bool)
    for name in ("obligations", "capabilities", "epistemic", "legal_next_action_classes",
                 "ready_obligation_ids", "blocked_obligation_ids", "strategy_schema_ids"):
        _exact(name, surface[name], list)
    for name in ("budgets", "completion", "continuation"):
        _exact(name, surface[name], dict)
    _exact("data", value["data"], list)
    if len(value["data"]) > MAX_DATA_ITEMS:
        raise ValueError("too many data items")
    for item in value["data"]:
        _fields(item, {"origin", "source_id", "text", "control_authority"}, "data item")
        if item["control_authority"] is not False:
            raise ValueError("data cannot carry control authority")
        SupervisorData(DataOrigin(item["origin"]), item["source_id"], item["text"])
    return value


@dataclass(frozen=True, slots=True, init=False)
class FreshContextHandoff:
    """Canonical bounded observation; parsing does not validate live authority."""

    _text: str
    _source_runtime: RustRuntimeSession | None = field(repr=False, compare=False)
    _source_lineage: Any | None = field(repr=False, compare=False)

    def __init__(self, projection: SupervisorProjection) -> None:
        _exact("projection", projection, SupervisorProjection)
        record = {"protocol_version": FRESH_CONTEXT_VERSION, "projection": projection.canonical_record(),
                  "projection_id": projection.projection_id, "restores_native_authority": False}
        record["handoff_id"] = domain_fingerprint(_HANDOFF_DOMAIN, record)
        object.__setattr__(self, "_text", canonical_json(_json_copy(record, limit=MAX_FRESH_CONTEXT_BYTES)))
        object.__setattr__(self, "_source_runtime", projection._source_runtime)
        object.__setattr__(self, "_source_lineage", projection._source_lineage)

    @classmethod
    def from_record(cls, record: dict, *, source_handoff: FreshContextHandoff | None = None) -> FreshContextHandoff:
        if cls is not FreshContextHandoff:
            raise TypeError("fresh context requires the exact handoff type")
        record = _json_copy(record, limit=MAX_FRESH_CONTEXT_BYTES)
        _fields(record, {"protocol_version", "projection", "projection_id", "restores_native_authority", "handoff_id"}, "fresh context")
        if record["protocol_version"] != FRESH_CONTEXT_VERSION or record["restores_native_authority"] is not False:
            raise ValueError("invalid fresh context version or authority claim")
        projection = _validate_projection(record["projection"])
        if record["projection_id"] != domain_fingerprint(_PROJECTION_DOMAIN, projection):
            raise ValueError("fresh context projection identity mismatch")
        body = {key: value for key, value in record.items() if key != "handoff_id"}
        if record["handoff_id"] != domain_fingerprint(_HANDOFF_DOMAIN, body):
            raise ValueError("fresh context identity mismatch")
        result = object.__new__(cls)
        object.__setattr__(result, "_text", canonical_json(record))
        if source_handoff is not None:
            _exact("source handoff", source_handoff, FreshContextHandoff)
            if source_handoff.canonical_record() != record:
                raise ValueError("source handoff does not match parsed historical record")
        object.__setattr__(result, "_source_runtime", None if source_handoff is None else source_handoff._source_runtime)
        object.__setattr__(result, "_source_lineage", None if source_handoff is None else source_handoff._source_lineage)
        return result

    def canonical_record(self) -> dict:
        _exact("handoff text", self._text, str)
        bounded_utf8_length("fresh context", self._text, limit=MAX_FRESH_CONTEXT_BYTES)
        return json.loads(FreshContextHandoff.from_record(json.loads(self._text))._text)

    @property
    def handoff_id(self) -> str:
        return self.canonical_record()["handoff_id"]


def fresh_session_surface(handoff: FreshContextHandoff, context: SupervisorContext) -> dict:
    """Revalidate the exact live context; return no authority or reconstructed state."""
    _exact("handoff", handoff, FreshContextHandoff)
    _exact("context", context, SupervisorContext)
    _exact("continuation state", context.continuation_state, ContinuationState)
    if (handoff._source_runtime is not context.runtime_session
            or handoff._source_lineage is None
            or handoff._source_lineage is not context.continuation_state._native_lineage_seal()):
        raise ValueError("fresh context lacks its original in-process source witness")
    record = handoff.canonical_record()
    data = tuple(SupervisorData(DataOrigin(item["origin"]), item["source_id"], item["text"])
                 for item in record["projection"]["data"])
    current = FreshContextHandoff(SupervisorProjection(context, data=data))
    if current.canonical_record() != record:
        raise ValueError("fresh context does not match current live lineage or authority epoch")
    return current.canonical_record()["projection"]["decision_surface"]


class RecoveryClass(str, Enum):
    RESUME_VERIFIED_LIVE_TASK = "resume_verified_live_task"
    START_FRESH_AUTHORIZED_TASK = "start_fresh_authorized_task"
    ASK_HUMAN_AUTHORIZATION = "ask_human_authorization"
    STOP_UNVERIFIABLE = "stop_unverifiable"


@dataclass(frozen=True, slots=True)
class RecoveryDecision:
    classification: RecoveryClass
    reason: str
    evidence_handoff_id: str
    target_task_id: str | None = None

    def __post_init__(self) -> None:
        _exact("recovery classification", self.classification, RecoveryClass)
        _exact("recovery reason", self.reason, str)
        require_symbol("recovery reason", self.reason)
        _exact("recovery evidence", self.evidence_handoff_id, str)
        require_fingerprint("recovery evidence", self.evidence_handoff_id)
        if self.target_task_id is not None:
            _exact("recovery target task", self.target_task_id, str)
            require_fingerprint("recovery target task", self.target_task_id)
        reasons = {
            RecoveryClass.RESUME_VERIFIED_LIVE_TASK: {"exact_live_lineage_verified"},
            RecoveryClass.START_FRESH_AUTHORIZED_TASK: {"separate_authority_selects_historical_observation"},
            RecoveryClass.ASK_HUMAN_AUTHORIZATION: {"new_task_authority_unverified", "separate_bound_authority_required",
                                                   "live_task_authority_unavailable"},
            RecoveryClass.STOP_UNVERIFIABLE: {"live_source_unavailable", "source_or_lineage_unverifiable"},
        }
        if self.reason not in reasons[self.classification]:
            raise ValueError("recovery reason does not match classification")
        requires_target = self.classification in {RecoveryClass.RESUME_VERIFIED_LIVE_TASK, RecoveryClass.START_FRESH_AUTHORIZED_TASK}
        if requires_target != (self.target_task_id is not None):
            raise ValueError("recovery target does not match classification")

    def canonical_record(self) -> dict:
        self.__post_init__()
        return {"protocol_version": RECOVERY_VERSION, "classification": self.classification.value,
                "reason": self.reason, "evidence_handoff_id": self.evidence_handoff_id,
                "target_task_id": self.target_task_id, "grants_authority": False,
                "restores_native_authority": False, "final_acceptance": False}


def classify_recovery(handoff: FreshContextHandoff, *, source_context: SupervisorContext | None = None,
                      new_task_context: SupervisorContext | None = None) -> RecoveryDecision:
    """Classify only after exact source verification; never allocate a new task."""
    _exact("handoff", handoff, FreshContextHandoff)
    handoff_id = handoff.handoff_id
    if source_context is not None:
        _exact("source context", source_context, SupervisorContext)
    if new_task_context is not None:
        _exact("new task context", new_task_context, SupervisorContext)
    if new_task_context is not None:
        try:
            target = SupervisorProjection(new_task_context).canonical_record()
        except (TypeError, ValueError, RuntimeError):
            return RecoveryDecision(RecoveryClass.ASK_HUMAN_AUTHORIZATION, "new_task_authority_unverified", handoff_id)
        contract = new_task_context.task.acceptance_contract
        status = target["decision_surface"]["authority"]
        prior = handoff.canonical_record()["projection"]["sources"]
        if (not status["revoked"] and status["supervisor_capability_present"]
                and new_task_context.task.task_id != prior["task_id"]
                and target["sources"]["runtime_session_id"] != prior["runtime_session_id"]
                and contract.get("recovery_evidence_id") == handoff_id
                and contract.get("recovery_source_task_id") == prior["task_id"]):
            return RecoveryDecision(RecoveryClass.START_FRESH_AUTHORIZED_TASK, "separate_authority_selects_historical_observation",
                                    handoff_id, new_task_context.task.task_id)
        return RecoveryDecision(RecoveryClass.ASK_HUMAN_AUTHORIZATION, "separate_bound_authority_required", handoff_id)
    if source_context is None:
        return RecoveryDecision(RecoveryClass.STOP_UNVERIFIABLE, "live_source_unavailable", handoff_id)
    try:
        surface = fresh_session_surface(handoff, source_context)
    except (TypeError, ValueError, RuntimeError):
        return RecoveryDecision(RecoveryClass.STOP_UNVERIFIABLE, "source_or_lineage_unverifiable", handoff_id)
    if surface["authority"]["revoked"] or not surface["authority"]["supervisor_capability_present"]:
        return RecoveryDecision(RecoveryClass.ASK_HUMAN_AUTHORIZATION, "live_task_authority_unavailable", handoff_id)
    return RecoveryDecision(RecoveryClass.RESUME_VERIFIED_LIVE_TASK, "exact_live_lineage_verified", handoff_id,
                            source_context.task.task_id)
