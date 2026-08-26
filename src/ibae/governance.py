"""Deterministic v0.4 governance and cross-layer receipt contracts.

This module deliberately contains policy and receipt logic only.  It does not
call a model provider, grant continuation leases, or mutate the Rust runtime.
The validators establish canonical structural consistency; producer
authentication is intentionally outside the v0.4 claim scope.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ._records import (
    CanonicalValue,
    materialize_bounded_iterable,
    require_fingerprint,
    require_invariant_id,
    require_nonnegative_int,
    require_positive_int,
    require_symbol,
)
from .canonical import canonical_fingerprint, domain_fingerprint
from .orchestration import (
    ACTION_ID_DOMAIN,
    MAX_PROPOSALS_PER_BATCH,
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
from .runtime import RuntimeReceipt

GOVERNANCE_PROTOCOL_VERSION = "IBAE-GOVERNANCE-PROTOCOL-V1"
TASK_RECEIPT_VERSION = "IBAE-TASK-RECEIPT-V1"
GOVERNANCE_RECEIPT_VERSION = "IBAE-GOVERNANCE-RECEIPT-V1"
TOOL_ADMISSION_RECEIPT_VERSION = "IBAE-TOOL-ADMISSION-RECEIPT-V1"
ORCHESTRATION_RECEIPT_VERSION = "IBAE-ORCHESTRATION-RECEIPT-V1"
EXECUTION_RECEIPT_VERSION = "IBAE-EXECUTION-RECEIPT-V1"
EXECUTION_PLAN_RECEIPT_VERSION = "IBAE-EXECUTION-PLAN-RECEIPT-V1"
BENCHMARK_RECEIPT_VERSION = "IBAE-BENCHMARK-RECEIPT-V1"
FINAL_ACCEPTANCE_RECEIPT_VERSION = "IBAE-FINAL-ACCEPTANCE-RECEIPT-V1"
REJECTION_RECEIPT_VERSION = "IBAE-REJECTION-RECEIPT-V1"
PARTIAL_RECEIPT_VERSION = "IBAE-PARTIAL-RECEIPT-V1"

TASK_ID_DOMAIN = "ibae.task-id.v1"
TASK_RECEIPT_ID_DOMAIN = "ibae.task-receipt-id.v1"
GOVERNANCE_ID_DOMAIN = "ibae.governance-id.v1"
GOVERNANCE_RECEIPT_ID_DOMAIN = "ibae.governance-receipt-id.v1"
TOOL_PERMISSION_ID_DOMAIN = "ibae.tool-permission-id.v1"
TOOL_ACTION_ID_DOMAIN = "ibae.governed-tool-action-id.v1"
TOOL_DECISION_ID_DOMAIN = "ibae.governed-admission-decision-id.v1"
TOOL_ADMISSION_RECEIPT_ID_DOMAIN = "ibae.tool-admission-receipt-id.v1"
AUTHORIZATION_MANIFEST_ID_DOMAIN = "ibae.evidence-authorization-manifest.v1"
ORCHESTRATION_ID_DOMAIN = "ibae.governed-orchestration-id.v1"
ORCHESTRATION_RECEIPT_ID_DOMAIN = "ibae.orchestration-receipt-id.v1"
EXECUTION_ID_DOMAIN = "ibae.governed-execution-id.v1"
EXECUTION_RECEIPT_ID_DOMAIN = "ibae.execution-receipt-id.v1"
EXECUTION_PLAN_ID_DOMAIN = "ibae.execution-plan-id.v1"
EXECUTION_PLAN_RECEIPT_ID_DOMAIN = "ibae.execution-plan-receipt-id.v1"
BENCHMARK_ID_DOMAIN = "ibae.benchmark-id.v1"
BENCHMARK_RECEIPT_ID_DOMAIN = "ibae.benchmark-receipt-id.v1"
FINAL_ACCEPTANCE_ID_DOMAIN = "ibae.final-acceptance-id.v1"
FINAL_ACCEPTANCE_RECEIPT_ID_DOMAIN = "ibae.final-acceptance-receipt-id.v1"
REJECTION_RECEIPT_ID_DOMAIN = "ibae.rejection-receipt-id.v1"
PARTIAL_RECEIPT_ID_DOMAIN = "ibae.partial-receipt-id.v1"
GATE_RESULT_ID_DOMAIN = "ibae.acceptance-gate-result-id.v1"

MAX_TOOL_PERMISSIONS = 256
MAX_TOOL_ADMISSIONS = MAX_PROPOSALS_PER_BATCH
MAX_REQUIRED_GATES = 64
MAX_REJECTION_INVARIANTS = 64
MAX_BOUND_RECEIPT_IDS = 4_096

COMPACT_EVIDENCE_GATE_KEY = "compact_evidence_valid"
ORCHESTRATION_RECEIPT_GATE_KEY = "orchestration_receipt_valid"
EXECUTION_RECEIPT_GATE_KEY = "execution_receipt_valid"
SUPPORTED_REQUIRED_GATE_KEYS = frozenset(
    {
        COMPACT_EVIDENCE_GATE_KEY,
        ORCHESTRATION_RECEIPT_GATE_KEY,
        EXECUTION_RECEIPT_GATE_KEY,
    }
)

DETERMINISTIC_VERIFICATION_SCOPE = "deterministic-contract-consistency-only"
PRODUCER_AUTHENTICATION_SCOPE = "not-established-by-v0.4"


class ProviderAuthority(str, Enum):
    """Closed proprietary remote-provider authority.

    Local open-weight workers are not providers and therefore do not appear in
    this enum.
    """

    OPENAI = "openai"


class PrincipalAuthority(str, Enum):
    OPENAI_SUPERVISOR = "openai_supervisor"
    LOCAL_CANDIDATE_WORKER = "local_candidate_worker"
    DETERMINISTIC_ORCHESTRATOR = "deterministic_orchestrator"
    RUST_EXECUTION_RUNTIME = "rust_execution_runtime"


class ToolAuthorityClass(str, Enum):
    PURE_READ = "pure_read"
    SNAPSHOT_READ = "snapshot_read"
    VOLATILE_READ = "volatile_read"
    IDEMPOTENT_MUTATION = "idempotent_mutation"
    NON_IDEMPOTENT_MUTATION = "non_idempotent_mutation"

    @property
    def is_mutation(self) -> bool:
        return self in {
            ToolAuthorityClass.IDEMPOTENT_MUTATION,
            ToolAuthorityClass.NON_IDEMPOTENT_MUTATION,
        }

    @property
    def is_read(self) -> bool:
        return not self.is_mutation


class ReceiptStage(str, Enum):
    GOVERNANCE = "governance"
    ORCHESTRATION = "orchestration"
    EXECUTION = "execution"
    FINALIZATION = "finalization"


class GovernanceRejectionReason(str, Enum):
    UNKNOWN_AUTHORITY = "IBAE-REJECT-UNKNOWN-AUTHORITY"
    AUTHORITY_ESCALATION = "IBAE-REJECT-AUTHORITY-ESCALATION"
    UNKNOWN_TOOL_PERMISSION = "IBAE-REJECT-UNKNOWN-TOOL-PERMISSION"
    TOOL_CLASS_MISMATCH = "IBAE-REJECT-TOOL-CLASS-MISMATCH"
    MUTATION_NOT_PERMITTED = "IBAE-REJECT-MUTATION-NOT-PERMITTED"
    DEPENDENCY_ID_REQUIRED = "IBAE-REJECT-DEPENDENCY-ID-REQUIRED"
    OCCURRENCE_ID_REQUIRED = "IBAE-REJECT-OCCURRENCE-ID-REQUIRED"
    OCCURRENCE_ID_FORBIDDEN = "IBAE-REJECT-OCCURRENCE-ID-FORBIDDEN"
    MALFORMED_ACTION = "IBAE-REJECT-MALFORMED-ACTION"
    INVALID_BOUND_RECEIPT = "IBAE-REJECT-INVALID-BOUND-RECEIPT"
    UNKNOWN_ACCEPTANCE_GATE = "IBAE-REJECT-UNKNOWN-ACCEPTANCE-GATE"


class PartialReason(str, Enum):
    MISSING_ORCHESTRATION_RECEIPT = "IBAE-PARTIAL-MISSING-ORCHESTRATION-RECEIPT"
    MISSING_EXECUTION_RECEIPT = "IBAE-PARTIAL-MISSING-EXECUTION-RECEIPT"
    UNSATISFIED_ACCEPTANCE_GATES = "IBAE-PARTIAL-UNSATISFIED-ACCEPTANCE-GATES"


def _require_bool(name: str, value: bool) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{name} must be a boolean")
    return value


def _canonical_mapping(name: str, value: Mapping[str, Any]) -> CanonicalValue:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    return CanonicalValue.from_value(value)


def _bounded_unique_symbols(
    name: str,
    values: Iterable[str],
    *,
    limit: int,
) -> tuple[str, ...]:
    supplied = materialize_bounded_iterable(name, values, limit=limit)
    for value in supplied:
        require_symbol(name.removesuffix("s"), value)
    normalized = tuple(sorted(supplied))
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{name} must be unique")
    return normalized


def _bounded_fingerprints(
    name: str,
    values: Iterable[str],
    *,
    limit: int,
) -> tuple[str, ...]:
    supplied = materialize_bounded_iterable(name, values, limit=limit)
    for value in supplied:
        require_fingerprint(name.removesuffix("s"), value)
    if len(supplied) != len(set(supplied)):
        raise ValueError(f"{name} must be unique")
    return supplied


def _with_receipt_id(domain: str, body: Mapping[str, Any]) -> dict[str, Any]:
    canonical_body = CanonicalValue.from_value(body).to_value()
    return {
        **canonical_body,
        "receipt_id": domain_fingerprint(domain, canonical_body),
    }


def _require_exact_record(
    name: str,
    record: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> None:
    if not isinstance(record, Mapping):
        raise TypeError(f"{name} must be a mapping")
    canonical_expected = CanonicalValue.from_value(expected).to_value()
    bounded_record = _bounded_exact_mapping(
        name,
        record,
        canonical_expected,
    )
    actual = CanonicalValue.from_value(bounded_record).to_value()
    if actual != canonical_expected:
        raise ValueError(f"{name} is malformed or does not match its bound authority")


def _bounded_exact_mapping(
    name: str,
    value: Mapping[str, Any],
    fields: Iterable[str],
) -> dict[str, Any]:
    """Copy one fixed-schema record without trusting an unbounded key iterator."""

    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    expected = tuple(sorted(fields))
    try:
        keys = materialize_bounded_iterable(
            f"{name} fields",
            value,
            limit=len(expected),
        )
    except ValueError as exc:
        raise ValueError(
            f"{name} does not match the v1 schema; field count exceeds hard limit"
        ) from exc
    copied: dict[str, Any] = {}
    for key in keys:
        if not isinstance(key, str):
            raise TypeError(f"{name} field names must be strings")
        if key in copied:
            raise ValueError(f"{name} field names must be unique")
        copied[key] = value[key]
    if tuple(sorted(copied)) != expected:
        raise ValueError(f"{name} does not match the v1 schema")
    return {key: copied[key] for key in expected}


@dataclass(frozen=True, slots=True)
class ToolPermission:
    """Governance-owned permission for one named tool.

    Both booleans are mandatory.  In particular, mutation permission has no
    permissive default that could turn an omitted field into authority.
    """

    tool_name: str
    authority_class: ToolAuthorityClass
    allow_mutation: bool
    allow_cache_reuse: bool

    def __post_init__(self) -> None:
        require_symbol("tool name", self.tool_name)
        if not isinstance(self.authority_class, ToolAuthorityClass):
            raise TypeError("authority_class must be a ToolAuthorityClass")
        _require_bool("allow_mutation", self.allow_mutation)
        _require_bool("allow_cache_reuse", self.allow_cache_reuse)
        if self.authority_class.is_read and self.allow_mutation:
            raise ValueError("read tools cannot carry mutation authority")
        if self.authority_class.is_mutation and self.allow_cache_reuse:
            raise ValueError("mutations cannot enter the observation cache")
        if (
            self.authority_class is ToolAuthorityClass.VOLATILE_READ
            and self.allow_cache_reuse
        ):
            raise ValueError("volatile reads cannot be cache reusable")

    @property
    def permission_id(self) -> str:
        return domain_fingerprint(TOOL_PERMISSION_ID_DOMAIN, self.canonical_record())

    def canonical_record(self) -> dict[str, object]:
        return {
            "allow_cache_reuse": self.allow_cache_reuse,
            "allow_mutation": self.allow_mutation,
            "authority_class": self.authority_class.value,
            "tool_name": self.tool_name,
        }

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> ToolPermission:
        active = _bounded_exact_mapping(
            "tool permission",
            record,
            {
            "allow_cache_reuse",
            "allow_mutation",
            "authority_class",
            "tool_name",
            },
        )
        try:
            authority_class = ToolAuthorityClass(active["authority_class"])
        except (TypeError, ValueError) as exc:
            raise ValueError("unknown tool authority class") from exc
        permission = cls(
            tool_name=active["tool_name"],
            authority_class=authority_class,
            allow_mutation=active["allow_mutation"],
            allow_cache_reuse=active["allow_cache_reuse"],
        )
        _require_exact_record("tool permission", active, permission.canonical_record())
        return permission


@dataclass(frozen=True, slots=True)
class GovernancePolicy:
    policy_key: str
    policy_version: int
    task_profile: str
    task_profile_version: int
    provider_authority: ProviderAuthority
    tool_permissions: tuple[ToolPermission, ...]
    required_gate_keys: tuple[str, ...]
    supervisor_authority: PrincipalAuthority = PrincipalAuthority.OPENAI_SUPERVISOR
    worker_authority: PrincipalAuthority = PrincipalAuthority.LOCAL_CANDIDATE_WORKER
    orchestration_authority: PrincipalAuthority = (
        PrincipalAuthority.DETERMINISTIC_ORCHESTRATOR
    )
    runtime_authority: PrincipalAuthority = PrincipalAuthority.RUST_EXECUTION_RUNTIME

    def __post_init__(self) -> None:
        require_symbol("policy key", self.policy_key)
        require_positive_int("policy version", self.policy_version)
        require_symbol("task profile", self.task_profile)
        require_positive_int("task profile version", self.task_profile_version)
        if self.provider_authority is not ProviderAuthority.OPENAI:
            raise ValueError("remote proprietary provider authority must be openai")
        expected_authorities = (
            (
                "supervisor",
                self.supervisor_authority,
                PrincipalAuthority.OPENAI_SUPERVISOR,
            ),
            (
                "worker",
                self.worker_authority,
                PrincipalAuthority.LOCAL_CANDIDATE_WORKER,
            ),
            (
                "orchestration",
                self.orchestration_authority,
                PrincipalAuthority.DETERMINISTIC_ORCHESTRATOR,
            ),
            (
                "runtime",
                self.runtime_authority,
                PrincipalAuthority.RUST_EXECUTION_RUNTIME,
            ),
        )
        for name, actual, expected in expected_authorities:
            if not isinstance(actual, PrincipalAuthority) or actual is not expected:
                raise ValueError(f"{name} authority is fixed by the v1 contract")

        permissions = materialize_bounded_iterable(
            "tool permissions",
            self.tool_permissions,
            limit=MAX_TOOL_PERMISSIONS,
        )
        if any(not isinstance(item, ToolPermission) for item in permissions):
            raise TypeError("tool_permissions must contain ToolPermission records")
        normalized_permissions = tuple(
            sorted(permissions, key=lambda item: item.tool_name)
        )
        names = tuple(item.tool_name for item in normalized_permissions)
        if len(names) != len(set(names)):
            raise ValueError("tool permission names must be unique")
        object.__setattr__(self, "tool_permissions", normalized_permissions)
        object.__setattr__(
            self,
            "required_gate_keys",
            _bounded_unique_symbols(
                "required gate keys",
                self.required_gate_keys,
                limit=MAX_REQUIRED_GATES,
            ),
        )
        if set(self.required_gate_keys) != SUPPORTED_REQUIRED_GATE_KEYS:
            raise ValueError(
                "governance policy requires the exact closed v1 acceptance gate set"
            )

    @property
    def governance_id(self) -> str:
        return domain_fingerprint(GOVERNANCE_ID_DOMAIN, self.canonical_record())

    def permission_for(self, tool_name: str) -> ToolPermission | None:
        require_symbol("tool name", tool_name)
        return next(
            (item for item in self.tool_permissions if item.tool_name == tool_name),
            None,
        )

    def canonical_record(self) -> dict[str, object]:
        return {
            "orchestration_authority": self.orchestration_authority.value,
            "policy_key": self.policy_key,
            "policy_version": self.policy_version,
            "protocol_version": GOVERNANCE_PROTOCOL_VERSION,
            "provider_authority": self.provider_authority.value,
            "required_gate_keys": list(self.required_gate_keys),
            "runtime_authority": self.runtime_authority.value,
            "supervisor_authority": self.supervisor_authority.value,
            "task_profile": self.task_profile,
            "task_profile_version": self.task_profile_version,
            "tool_permissions": [
                item.canonical_record() for item in self.tool_permissions
            ],
            "worker_authority": self.worker_authority.value,
        }

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> GovernancePolicy:
        fields = {
            "orchestration_authority",
            "policy_key",
            "policy_version",
            "protocol_version",
            "provider_authority",
            "required_gate_keys",
            "runtime_authority",
            "supervisor_authority",
            "task_profile",
            "task_profile_version",
            "tool_permissions",
            "worker_authority",
        }
        active = _bounded_exact_mapping("governance policy", record, fields)
        try:
            provider = ProviderAuthority(active["provider_authority"])
            supervisor = PrincipalAuthority(active["supervisor_authority"])
            worker = PrincipalAuthority(active["worker_authority"])
            orchestration = PrincipalAuthority(active["orchestration_authority"])
            runtime = PrincipalAuthority(active["runtime_authority"])
        except (TypeError, ValueError) as exc:
            raise ValueError("governance policy contains unknown authority") from exc
        permission_records = materialize_bounded_iterable(
            "governance policy tool permissions",
            active["tool_permissions"],
            limit=MAX_TOOL_PERMISSIONS,
        )
        required_gate_keys = materialize_bounded_iterable(
            "governance policy required gate keys",
            active["required_gate_keys"],
            limit=MAX_REQUIRED_GATES,
        )
        policy = cls(
            policy_key=active["policy_key"],
            policy_version=active["policy_version"],
            task_profile=active["task_profile"],
            task_profile_version=active["task_profile_version"],
            provider_authority=provider,
            tool_permissions=tuple(
                ToolPermission.from_record(item) for item in permission_records
            ),
            required_gate_keys=required_gate_keys,
            supervisor_authority=supervisor,
            worker_authority=worker,
            orchestration_authority=orchestration,
            runtime_authority=runtime,
        )
        _require_exact_record("governance policy", active, policy.canonical_record())
        return policy


@dataclass(frozen=True, slots=True, init=False)
class TaskReceipt:
    task_key: str
    contract_version: int
    required_gate_keys: tuple[str, ...]
    _acceptance_contract: CanonicalValue

    def __init__(
        self,
        task_key: str,
        acceptance_contract: Mapping[str, Any],
        *,
        required_gate_keys: Iterable[str],
        contract_version: int = 1,
    ) -> None:
        require_symbol("task key", task_key)
        require_positive_int("task contract version", contract_version)
        gates = _bounded_unique_symbols(
            "required gate keys", required_gate_keys, limit=MAX_REQUIRED_GATES
        )
        if not gates:
            raise ValueError("a task requires at least one acceptance gate")
        object.__setattr__(self, "task_key", task_key)
        object.__setattr__(self, "contract_version", contract_version)
        object.__setattr__(self, "required_gate_keys", gates)
        object.__setattr__(
            self,
            "_acceptance_contract",
            _canonical_mapping("acceptance contract", acceptance_contract),
        )

    @property
    def acceptance_contract(self) -> dict[str, Any]:
        return self._acceptance_contract.to_value()

    def identity_record(self) -> dict[str, object]:
        return {
            "acceptance_contract": self.acceptance_contract,
            "contract_version": self.contract_version,
            "required_gate_keys": list(self.required_gate_keys),
            "task_key": self.task_key,
        }

    @property
    def task_id(self) -> str:
        return domain_fingerprint(TASK_ID_DOMAIN, self.identity_record())

    @property
    def receipt_id(self) -> str:
        return self.canonical_record()["receipt_id"]

    def canonical_record(self) -> dict[str, Any]:
        body = {
            **self.identity_record(),
            "authority_layer": "governance",
            "protocol_version": TASK_RECEIPT_VERSION,
            "status": "admitted",
            "task_id": self.task_id,
        }
        return _with_receipt_id(TASK_RECEIPT_ID_DOMAIN, body)

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> TaskReceipt:
        fields = {
            "acceptance_contract",
            "authority_layer",
            "contract_version",
            "protocol_version",
            "receipt_id",
            "required_gate_keys",
            "status",
            "task_id",
            "task_key",
        }
        active = _bounded_exact_mapping("task receipt", record, fields)
        receipt = cls(
            active["task_key"],
            active["acceptance_contract"],
            required_gate_keys=active["required_gate_keys"],
            contract_version=active["contract_version"],
        )
        _require_exact_record("task receipt", active, receipt.canonical_record())
        return receipt


@dataclass(frozen=True, slots=True, init=False)
class GovernanceReceipt:
    task_id: str
    task_receipt_id: str
    governance_id: str
    policy_key: str
    policy_version: int
    provider_authority: ProviderAuthority
    requester: PrincipalAuthority
    required_gate_keys: tuple[str, ...]
    task_profile: str
    task_profile_version: int

    def __init__(
        self,
        policy: GovernancePolicy,
        task: TaskReceipt,
        requester: PrincipalAuthority,
    ) -> None:
        if type(policy) is not GovernancePolicy:
            raise TypeError("policy must be a GovernancePolicy")
        if type(task) is not TaskReceipt:
            raise TypeError("task must be a TaskReceipt")
        if requester is not PrincipalAuthority.OPENAI_SUPERVISOR:
            raise ValueError("only the OpenAI supervisor may admit a governed task")
        if task.required_gate_keys != policy.required_gate_keys:
            raise ValueError("task acceptance gates must match the active policy")
        object.__setattr__(self, "task_id", task.task_id)
        object.__setattr__(self, "task_receipt_id", task.receipt_id)
        object.__setattr__(self, "governance_id", policy.governance_id)
        object.__setattr__(self, "policy_key", policy.policy_key)
        object.__setattr__(self, "policy_version", policy.policy_version)
        object.__setattr__(self, "provider_authority", policy.provider_authority)
        object.__setattr__(self, "requester", requester)
        object.__setattr__(self, "required_gate_keys", policy.required_gate_keys)
        object.__setattr__(self, "task_profile", policy.task_profile)
        object.__setattr__(self, "task_profile_version", policy.task_profile_version)

    @property
    def receipt_id(self) -> str:
        return self.canonical_record()["receipt_id"]

    def canonical_record(self) -> dict[str, Any]:
        body = {
            "authority_layer": "governance",
            "governance_id": self.governance_id,
            "policy_key": self.policy_key,
            "policy_version": self.policy_version,
            "protocol_version": GOVERNANCE_RECEIPT_VERSION,
            "provider_authority": self.provider_authority.value,
            "requester": self.requester.value,
            "required_gate_keys": list(self.required_gate_keys),
            "status": "accepted",
            "task_id": self.task_id,
            "task_profile": self.task_profile,
            "task_profile_version": self.task_profile_version,
            "task_receipt_id": self.task_receipt_id,
        }
        return _with_receipt_id(GOVERNANCE_RECEIPT_ID_DOMAIN, body)

    @classmethod
    def from_record(
        cls,
        record: Mapping[str, Any],
        *,
        policy: GovernancePolicy,
        task: TaskReceipt,
    ) -> GovernanceReceipt:
        receipt = cls(policy, task, PrincipalAuthority.OPENAI_SUPERVISOR)
        _require_exact_record("governance receipt", record, receipt.canonical_record())
        return receipt


@dataclass(frozen=True, slots=True, init=False)
class ToolAdmissionReceipt:
    task_id: str
    governance_id: str
    governance_receipt_id: str
    action_id: str
    admission_decision: AdmissionDecision
    proposal: ActionProposal
    capability: Capability
    permission_id: str
    tool_name: str
    authority_class: ToolAuthorityClass
    requester: PrincipalAuthority
    dependency_fingerprint: str
    occurrence_key: str | None
    _arguments: CanonicalValue
    cache_reuse_permitted: bool

    def __init__(
        self,
        policy: GovernancePolicy,
        task: TaskReceipt,
        governance: GovernanceReceipt,
        permission: ToolPermission,
        requester: PrincipalAuthority,
        admission_decision: AdmissionDecision,
        proposal: ActionProposal,
        capability: Capability,
        dependency_state_id: str,
    ) -> None:
        _require_governance_binding(policy, task, governance)
        if type(permission) is not ToolPermission:
            raise TypeError("permission must be a ToolPermission")
        if policy.permission_for(permission.tool_name) != permission:
            raise ValueError("tool permission is not owned by the active policy")
        if requester is not PrincipalAuthority.DETERMINISTIC_ORCHESTRATOR:
            raise ValueError("only the deterministic orchestrator may admit a tool")
        if type(admission_decision) is not AdmissionDecision:
            raise TypeError("admission_decision must be an AdmissionDecision")
        if type(proposal) is not ActionProposal:
            raise TypeError("proposal must be an ActionProposal")
        if type(capability) is not Capability:
            raise TypeError("capability must be a Capability")
        if admission_decision.status is not DecisionStatus.ADMITTED:
            raise ValueError("tool governance requires a v0.2 admitted decision")
        if admission_decision.authority_layer is not AuthorityLayer.ORCHESTRATION:
            raise ValueError("tool governance requires orchestration-layer admission")
        if (
            admission_decision.blocking_obligation_ids
            or admission_decision.unresolved_state_keys
        ):
            raise ValueError("admitted decisions cannot carry blocking state")
        if (
            admission_decision.proposal_id != proposal.proposal_id
            or admission_decision.proposal_key != proposal.proposal_key
        ):
            raise ValueError("admission decision and proposal identities do not match")
        if proposal.capability != capability.name:
            raise ValueError("proposal and capability identities do not match")
        if permission.tool_name != capability.name:
            raise ValueError("tool permission and capability names do not match")
        if not capability.available:
            raise ValueError("unavailable capabilities cannot receive tool authority")
        expected_dependency_keys = tuple(
            sorted(
                set(capability.required_state_keys)
                | set(proposal.required_state_keys)
            )
        )
        if admission_decision.dependency_state_keys != expected_dependency_keys:
            raise ValueError(
                "admission decision dependency keys do not match its proposal "
                "capability"
            )
        require_fingerprint("v0.2 dependency state id", dependency_state_id)
        semantic_arguments = capability.normalize_arguments(proposal.arguments)
        action_record: dict[str, object] = {
            "arguments": semantic_arguments,
            "capability_id": capability.capability_id,
            "dependency_state_id": dependency_state_id,
        }
        if capability.replay_safety is ReplaySafety.OCCURRENCE_SENSITIVE:
            action_record["occurrence_key"] = proposal.occurrence_key
        expected_action_id = domain_fingerprint(ACTION_ID_DOMAIN, action_record)
        if admission_decision.action_id != expected_action_id:
            raise ValueError(
                "v0.2 admitted action identity does not match the typed proposal"
            )

        authority_class = permission.authority_class
        if authority_class in {
            ToolAuthorityClass.PURE_READ,
            ToolAuthorityClass.SNAPSHOT_READ,
        }:
            if capability.replay_safety is not ReplaySafety.CACHEABLE_READ:
                raise ValueError(
                    "pure and snapshot reads require cacheable-read replay safety"
                )
            expected_read_class = (
                ToolAuthorityClass.SNAPSHOT_READ
                if expected_dependency_keys
                else ToolAuthorityClass.PURE_READ
            )
            if authority_class is not expected_read_class:
                raise ValueError(
                    "read authority class does not match declared state dependencies"
                )
        elif capability.replay_safety is not ReplaySafety.OCCURRENCE_SENSITIVE:
            raise ValueError(
                "v1 effect and volatile authority requires occurrence-sensitive "
                "replay safety"
            )

        occurrence_key = proposal.occurrence_key
        occurrence_sensitive = (
            authority_class.is_mutation
            or authority_class is ToolAuthorityClass.VOLATILE_READ
        )
        if permission.authority_class.is_mutation:
            if not permission.allow_mutation:
                raise ValueError("mutation is not explicitly permitted")
        if occurrence_sensitive:
            if occurrence_key is None:
                raise ValueError(
                    "volatile reads and mutations require occurrence identity"
                )
            require_symbol("occurrence key", occurrence_key)
        elif occurrence_key is not None:
            raise ValueError("pure and snapshot reads cannot carry occurrence identity")
        object.__setattr__(self, "task_id", task.task_id)
        object.__setattr__(self, "governance_id", policy.governance_id)
        object.__setattr__(self, "governance_receipt_id", governance.receipt_id)
        object.__setattr__(self, "action_id", expected_action_id)
        object.__setattr__(self, "admission_decision", admission_decision)
        object.__setattr__(self, "proposal", proposal)
        object.__setattr__(self, "capability", capability)
        object.__setattr__(self, "permission_id", permission.permission_id)
        object.__setattr__(self, "tool_name", permission.tool_name)
        object.__setattr__(self, "authority_class", authority_class)
        object.__setattr__(self, "requester", requester)
        object.__setattr__(self, "dependency_fingerprint", dependency_state_id)
        object.__setattr__(self, "occurrence_key", occurrence_key)
        object.__setattr__(
            self, "_arguments", CanonicalValue.from_value(semantic_arguments)
        )
        object.__setattr__(
            self,
            "cache_reuse_permitted",
            permission.allow_cache_reuse,
        )

    @property
    def arguments(self) -> Any:
        return self._arguments.to_value()

    def action_identity_record(self) -> dict[str, object]:
        return {
            "action_id": self.action_id,
            "arguments": self.arguments,
            "arguments_id": self.arguments_id,
            "authority_class": self.authority_class.value,
            "capability_id": self.capability.capability_id,
            "decision_id": self.decision_id,
            "dependency_fingerprint": self.dependency_fingerprint,
            "governance_id": self.governance_id,
            "occurrence_key": self.occurrence_key,
            "permission_id": self.permission_id,
            "proposal_id": self.proposal.proposal_id,
            "replay_safety": self.capability.replay_safety.value,
            "task_id": self.task_id,
            "tool_name": self.tool_name,
        }

    @property
    def governed_action_id(self) -> str:
        return domain_fingerprint(TOOL_ACTION_ID_DOMAIN, self.action_identity_record())

    @property
    def decision_id(self) -> str:
        return domain_fingerprint(
            TOOL_DECISION_ID_DOMAIN,
            self.admission_decision.canonical_record(),
        )

    @property
    def arguments_id(self) -> str:
        return canonical_fingerprint(self.arguments)

    @property
    def receipt_id(self) -> str:
        return self.canonical_record()["receipt_id"]

    def canonical_record(self) -> dict[str, Any]:
        body = {
            **self.action_identity_record(),
            "authority_layer": "governance",
            "cache_reuse_permitted": self.cache_reuse_permitted,
            "governed_action_id": self.governed_action_id,
            "governance_receipt_id": self.governance_receipt_id,
            "protocol_version": TOOL_ADMISSION_RECEIPT_VERSION,
            "requester": self.requester.value,
            "status": "accepted",
        }
        return _with_receipt_id(TOOL_ADMISSION_RECEIPT_ID_DOMAIN, body)


@dataclass(frozen=True, slots=True, init=False)
class OrchestrationReceipt:
    task_id: str
    governance_id: str
    governance_receipt_id: str
    admission_receipt: AdmissionReceipt
    tool_admissions: tuple[ToolAdmissionReceipt, ...]
    _authorization_manifest: CanonicalValue
    authorization_manifest_id: str
    authorization_manifest_count: int

    def __init__(
        self,
        policy: GovernancePolicy,
        task: TaskReceipt,
        governance: GovernanceReceipt,
        admission_receipt: AdmissionReceipt,
        tool_admissions: Iterable[ToolAdmissionReceipt],
    ) -> None:
        _require_governance_binding(policy, task, governance)
        if type(admission_receipt) is not AdmissionReceipt:
            raise TypeError("admission_receipt must be an AdmissionReceipt")
        if admission_receipt.status is not BatchStatus.PROCESSED:
            raise ValueError("a rejected batch cannot become accepted orchestration")
        supplied_admissions = materialize_bounded_iterable(
            "tool admissions",
            tool_admissions,
            limit=MAX_TOOL_ADMISSIONS,
        )
        if any(type(item) is not ToolAdmissionReceipt for item in supplied_admissions):
            raise TypeError("tool_admissions must contain ToolAdmissionReceipt records")
        if any(type(item) is not AdmissionDecision for item in admission_receipt.decisions):
            raise TypeError("admission receipt must contain exact AdmissionDecision records")
        normalized_admissions = tuple(
            sorted(supplied_admissions, key=lambda item: item.action_id)
        )
        action_ids = tuple(item.action_id for item in normalized_admissions)
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("tool admissions must bind unique v0.2 action ids")
        for tool_admission in normalized_admissions:
            _require_tool_admission_binding(
                policy,
                task,
                governance,
                tool_admission,
            )
        admitted_by_proposal: dict[str, str] = {}
        admitted_by_action: dict[str, AdmissionDecision] = {}
        seen_proposal_ids: set[str] = set()
        seen_proposal_keys: set[str] = set()
        for decision in admission_receipt.decisions:
            if decision.proposal_id in seen_proposal_ids:
                raise ValueError(
                    "one proposal identity cannot have multiple admission decisions"
                )
            seen_proposal_ids.add(decision.proposal_id)
            if decision.proposal_key in seen_proposal_keys:
                raise ValueError(
                    "one proposal key cannot have multiple admission decisions"
                )
            seen_proposal_keys.add(decision.proposal_key)
            if decision.authority_layer is not AuthorityLayer.ORCHESTRATION:
                raise ValueError(
                    "governed admission decisions must belong to orchestration"
                )
            if decision.status in {
                DecisionStatus.ADMITTED,
                DecisionStatus.DEDUPLICATED,
            } and (
                decision.blocking_obligation_ids
                or decision.unresolved_state_keys
            ):
                raise ValueError(
                    "accepted admission decisions cannot carry blocking state"
                )
            if decision.status is DecisionStatus.ADMITTED:
                if decision.action_id is None:
                    raise ValueError("admitted decision is missing its action identity")
                if decision.action_id in admitted_by_action:
                    raise ValueError(
                        "one v0.2 action identity cannot have multiple admitted "
                        "decisions"
                    )
                admitted_by_proposal[decision.proposal_id] = decision.action_id
                admitted_by_action[decision.action_id] = decision
            elif decision.status is DecisionStatus.DEDUPLICATED:
                if decision.action_id is None:
                    raise ValueError(
                        "deduplicated decision is missing its action identity"
                    )
                equivalent_action_id = admitted_by_proposal.get(
                    decision.equivalent_proposal_id
                )
                if equivalent_action_id != decision.action_id:
                    raise ValueError(
                        "deduplicated decisions must reference an earlier admitted "
                        "proposal with the same action identity"
                    )
        decision_action_ids = tuple(sorted(admitted_by_action))
        if action_ids != decision_action_ids:
            raise ValueError(
                "tool admissions must exactly authorize every admitted action identity"
            )
        for tool_admission in normalized_admissions:
            admitted_decision = admitted_by_action[tool_admission.action_id]
            if (
                admitted_decision.canonical_record()
                != tool_admission.admission_decision.canonical_record()
            ):
                raise ValueError(
                    "tool admission does not bind the batch's exact admitted decision"
                )
        if any(
            item.capability.replay_safety is ReplaySafety.OCCURRENCE_SENSITIVE
            for item in normalized_admissions
        ) and (
            admission_receipt.proposal_ordering
            is not ProposalOrdering.DECLARED_SEQUENCE
        ):
            raise ValueError(
                "occurrence-sensitive actions require declared-sequence ordering"
            )
        runtime_cache_keys: set[tuple[str, str, str]] = set()
        for item in normalized_admissions:
            if item.authority_class not in {
                ToolAuthorityClass.PURE_READ,
                ToolAuthorityClass.SNAPSHOT_READ,
            }:
                continue
            runtime_cache_key = (
                item.tool_name,
                item.arguments_id,
                item.dependency_fingerprint,
            )
            if runtime_cache_key in runtime_cache_keys:
                raise ValueError(
                    "distinct governed actions cannot share one runtime cache key"
                )
            runtime_cache_keys.add(runtime_cache_key)
        manifest = tuple(
            {
                "action_id": item.action_id,
                "arguments_id": item.arguments_id,
                "authority_class": item.authority_class.name,
                "cache_reuse_permitted": item.cache_reuse_permitted,
                "dependency_fingerprint": item.dependency_fingerprint,
                "tool_admission_receipt_id": item.receipt_id,
                "tool_name": item.tool_name,
            }
            for item in normalized_admissions
        )
        manifest_id = domain_fingerprint(
            AUTHORIZATION_MANIFEST_ID_DOMAIN,
            {"entries": list(manifest)},
        )
        object.__setattr__(self, "task_id", task.task_id)
        object.__setattr__(self, "governance_id", policy.governance_id)
        object.__setattr__(self, "governance_receipt_id", governance.receipt_id)
        object.__setattr__(self, "admission_receipt", admission_receipt)
        object.__setattr__(self, "tool_admissions", normalized_admissions)
        object.__setattr__(
            self,
            "_authorization_manifest",
            CanonicalValue.from_value(list(manifest)),
        )
        object.__setattr__(self, "authorization_manifest_id", manifest_id)
        object.__setattr__(
            self, "authorization_manifest_count", len(normalized_admissions)
        )

    @property
    def authorization_manifest(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._authorization_manifest.to_value())

    def identity_record(self) -> dict[str, object]:
        return {
            "admission_receipt_id": self.admission_receipt.receipt_id,
            "authorization_manifest_count": self.authorization_manifest_count,
            "authorization_manifest_id": self.authorization_manifest_id,
            "batch_id": self.admission_receipt.batch_id,
            "governance_id": self.governance_id,
            "next_state_id": self.admission_receipt.next_state_id,
            "prior_state_id": self.admission_receipt.prior_state_id,
            "task_id": self.task_id,
        }

    @property
    def orchestration_id(self) -> str:
        return domain_fingerprint(ORCHESTRATION_ID_DOMAIN, self.identity_record())

    @property
    def receipt_id(self) -> str:
        return self.canonical_record()["receipt_id"]

    def canonical_record(self) -> dict[str, Any]:
        body = {
            **self.identity_record(),
            "authorization_manifest": list(self.authorization_manifest),
            "authority_layer": "orchestration",
            "governance_receipt_id": self.governance_receipt_id,
            "logical_tick_end": self.admission_receipt.logical_tick_end,
            "logical_tick_start": self.admission_receipt.logical_tick_start,
            "orchestration_id": self.orchestration_id,
            "protocol_version": ORCHESTRATION_RECEIPT_VERSION,
            "source_status": self.admission_receipt.status.value,
            "status": "accepted",
        }
        return _with_receipt_id(ORCHESTRATION_RECEIPT_ID_DOMAIN, body)


@dataclass(frozen=True, slots=True, init=False)
class ExecutionReceipt:
    task_id: str
    governance_id: str
    orchestration_id: str
    orchestration_receipt_id: str
    aggregate_admission_id: str
    aggregate_input_id: str
    aggregate_result_id: str
    aggregate_receipt_id: str
    authorization_manifest_id: str
    authorization_manifest_count: int
    initial_runtime_state_id: str
    transition_count: int
    initial_runtime_receipt: RuntimeReceipt
    final_runtime_receipt: RuntimeReceipt

    def __init__(
        self,
        policy: GovernancePolicy,
        task: TaskReceipt,
        governance: GovernanceReceipt,
        orchestration: OrchestrationReceipt,
        initial_runtime_receipt: RuntimeReceipt,
        final_runtime_receipt: RuntimeReceipt,
        *,
        aggregate_admission_id: str,
        aggregate_input_id: str,
        aggregate_result_id: str,
        aggregate_receipt_id: str,
        transition_count: int,
    ) -> None:
        _require_orchestration_binding(
            policy, task, governance, orchestration
        )
        if type(initial_runtime_receipt) is not RuntimeReceipt:
            raise TypeError("initial_runtime_receipt must be a RuntimeReceipt")
        if type(final_runtime_receipt) is not RuntimeReceipt:
            raise TypeError("final_runtime_receipt must be a RuntimeReceipt")
        initial_record = initial_runtime_receipt.canonical_record()
        final_record = final_runtime_receipt.canonical_record()
        if (
            initial_record["status"] != "accepted"
            or final_record["status"] != "accepted"
        ):
            raise ValueError("rejected runtime state cannot become accepted execution")
        require_fingerprint("aggregate admission id", aggregate_admission_id)
        require_fingerprint("aggregate input id", aggregate_input_id)
        require_fingerprint("aggregate result id", aggregate_result_id)
        require_fingerprint("aggregate receipt id", aggregate_receipt_id)
        require_positive_int("transition count", transition_count)
        if initial_record["session_id"] != final_record["session_id"]:
            raise ValueError(
                "execution boundary receipts must share one runtime session"
            )
        if transition_count == 1 and (
            initial_runtime_receipt.receipt_id != final_runtime_receipt.receipt_id
            or initial_record != final_record
        ):
            raise ValueError(
                "single-transition execution must use one canonical runtime receipt"
            )
        if (
            transition_count > 1
            and initial_runtime_receipt.receipt_id
            == final_runtime_receipt.receipt_id
        ):
            raise ValueError(
                "multi-transition execution requires distinct boundary receipts"
            )
        if initial_record["logical_tick"] > final_record["logical_tick"]:
            raise ValueError("execution boundary logical ticks cannot move backwards")
        object.__setattr__(self, "task_id", task.task_id)
        object.__setattr__(self, "governance_id", policy.governance_id)
        object.__setattr__(self, "orchestration_id", orchestration.orchestration_id)
        object.__setattr__(
            self, "orchestration_receipt_id", orchestration.receipt_id
        )
        object.__setattr__(self, "aggregate_admission_id", aggregate_admission_id)
        object.__setattr__(self, "aggregate_input_id", aggregate_input_id)
        object.__setattr__(self, "aggregate_result_id", aggregate_result_id)
        object.__setattr__(self, "aggregate_receipt_id", aggregate_receipt_id)
        object.__setattr__(
            self,
            "authorization_manifest_id",
            orchestration.authorization_manifest_id,
        )
        object.__setattr__(
            self,
            "authorization_manifest_count",
            orchestration.authorization_manifest_count,
        )
        object.__setattr__(
            self, "initial_runtime_state_id", initial_record["prior_state_id"]
        )
        object.__setattr__(self, "transition_count", transition_count)
        object.__setattr__(
            self, "initial_runtime_receipt", initial_runtime_receipt
        )
        object.__setattr__(self, "final_runtime_receipt", final_runtime_receipt)

    def identity_record(self) -> dict[str, object]:
        initial_record = self.initial_runtime_receipt.canonical_record()
        final_record = self.final_runtime_receipt.canonical_record()
        return {
            "aggregate_admission_id": self.aggregate_admission_id,
            "aggregate_input_id": self.aggregate_input_id,
            "aggregate_receipt_id": self.aggregate_receipt_id,
            "aggregate_result_id": self.aggregate_result_id,
            "authorization_manifest_count": self.authorization_manifest_count,
            "authorization_manifest_id": self.authorization_manifest_id,
            "final_runtime_receipt_id": self.final_runtime_receipt.receipt_id,
            "final_runtime_state_id": final_record["resulting_state_id"],
            "governance_id": self.governance_id,
            "initial_runtime_receipt_id": self.initial_runtime_receipt.receipt_id,
            "initial_runtime_state_id": self.initial_runtime_state_id,
            "orchestration_id": self.orchestration_id,
            "runtime_session_id": initial_record["session_id"],
            "task_id": self.task_id,
            "transition_count": self.transition_count,
        }

    @property
    def execution_id(self) -> str:
        return domain_fingerprint(EXECUTION_ID_DOMAIN, self.identity_record())

    @property
    def receipt_id(self) -> str:
        return self.canonical_record()["receipt_id"]

    def canonical_record(self) -> dict[str, Any]:
        body = {
            **self.identity_record(),
            "authority_layer": "execution",
            "execution_id": self.execution_id,
            "orchestration_receipt_id": self.orchestration_receipt_id,
            "protocol_version": EXECUTION_RECEIPT_VERSION,
            "status": "accepted",
        }
        return _with_receipt_id(EXECUTION_RECEIPT_ID_DOMAIN, body)


@dataclass(frozen=True, slots=True, init=False)
class ExecutionPlanReceipt:
    task_id: str
    governance_id: str
    orchestration_id: str
    _plan: CanonicalValue

    def __init__(
        self,
        policy: GovernancePolicy,
        task: TaskReceipt,
        governance: GovernanceReceipt,
        orchestration: OrchestrationReceipt,
        plan: Mapping[str, Any],
    ) -> None:
        _require_orchestration_binding(policy, task, governance, orchestration)
        object.__setattr__(self, "task_id", task.task_id)
        object.__setattr__(self, "governance_id", policy.governance_id)
        object.__setattr__(self, "orchestration_id", orchestration.orchestration_id)
        object.__setattr__(self, "_plan", _canonical_mapping("execution plan", plan))

    @property
    def plan(self) -> dict[str, Any]:
        return self._plan.to_value()

    def identity_record(self) -> dict[str, object]:
        return {
            "governance_id": self.governance_id,
            "orchestration_id": self.orchestration_id,
            "plan": self.plan,
            "task_id": self.task_id,
        }

    @property
    def execution_plan_id(self) -> str:
        return domain_fingerprint(EXECUTION_PLAN_ID_DOMAIN, self.identity_record())

    @property
    def receipt_id(self) -> str:
        return self.canonical_record()["receipt_id"]

    def canonical_record(self) -> dict[str, Any]:
        body = {
            **self.identity_record(),
            "authority_layer": "execution_plan",
            "correctness_authority": False,
            "execution_plan_id": self.execution_plan_id,
            "protocol_version": EXECUTION_PLAN_RECEIPT_VERSION,
            "status": "observed",
        }
        return _with_receipt_id(EXECUTION_PLAN_RECEIPT_ID_DOMAIN, body)


@dataclass(frozen=True, slots=True, init=False)
class BenchmarkReceipt:
    task_id: str
    execution_id: str
    _observations: CanonicalValue

    def __init__(
        self,
        task: TaskReceipt,
        execution: ExecutionReceipt,
        observations: Mapping[str, Any],
    ) -> None:
        if not isinstance(task, TaskReceipt):
            raise TypeError("task must be a TaskReceipt")
        if not isinstance(execution, ExecutionReceipt):
            raise TypeError("execution must be an ExecutionReceipt")
        if execution.task_id != task.task_id:
            raise ValueError("benchmark execution does not belong to the task")
        object.__setattr__(self, "task_id", task.task_id)
        object.__setattr__(self, "execution_id", execution.execution_id)
        object.__setattr__(
            self,
            "_observations",
            _canonical_mapping("benchmark observations", observations),
        )

    @property
    def observations(self) -> dict[str, Any]:
        return self._observations.to_value()

    def identity_record(self) -> dict[str, object]:
        return {
            "execution_id": self.execution_id,
            "observations": self.observations,
            "task_id": self.task_id,
        }

    @property
    def benchmark_id(self) -> str:
        return domain_fingerprint(BENCHMARK_ID_DOMAIN, self.identity_record())

    @property
    def receipt_id(self) -> str:
        return self.canonical_record()["receipt_id"]

    def canonical_record(self) -> dict[str, Any]:
        body = {
            **self.identity_record(),
            "authority_layer": "benchmark",
            "benchmark_id": self.benchmark_id,
            "correctness_authority": False,
            "protocol_version": BENCHMARK_RECEIPT_VERSION,
            "status": "observed",
        }
        return _with_receipt_id(BENCHMARK_RECEIPT_ID_DOMAIN, body)


@dataclass(frozen=True, slots=True)
class AcceptanceGateResult:
    gate_key: str
    satisfied: bool
    evidence_receipt_id: str | None

    def __post_init__(self) -> None:
        require_symbol("acceptance gate key", self.gate_key)
        _require_bool("gate satisfied", self.satisfied)
        if self.satisfied and self.evidence_receipt_id is None:
            raise ValueError("satisfied gates require bound evidence identity")
        if self.evidence_receipt_id is not None:
            require_fingerprint(
                "acceptance gate evidence receipt id", self.evidence_receipt_id
            )

    @property
    def gate_result_id(self) -> str:
        return domain_fingerprint(GATE_RESULT_ID_DOMAIN, self.canonical_record())

    def canonical_record(self) -> dict[str, object]:
        return {
            "evidence_receipt_id": self.evidence_receipt_id,
            "gate_key": self.gate_key,
            "satisfied": self.satisfied,
        }


@dataclass(frozen=True, slots=True, init=False)
class RejectionReceipt:
    stage: ReceiptStage
    reason: GovernanceRejectionReason
    task_id: str | None
    governance_id: str | None
    invariant_ids: tuple[str, ...]
    bound_receipt_ids: tuple[str, ...]
    _details: CanonicalValue

    def __init__(
        self,
        stage: ReceiptStage,
        reason: GovernanceRejectionReason,
        *,
        task_id: str | None,
        governance_id: str | None,
        invariant_ids: Iterable[str],
        bound_receipt_ids: Iterable[str] = (),
        details: Mapping[str, Any] | None = None,
    ) -> None:
        if not isinstance(stage, ReceiptStage):
            raise TypeError("stage must be a ReceiptStage")
        if not isinstance(reason, GovernanceRejectionReason):
            raise TypeError("reason must be a GovernanceRejectionReason")
        if task_id is not None:
            require_fingerprint("rejection task id", task_id)
        if governance_id is not None:
            require_fingerprint("rejection governance id", governance_id)
        supplied_invariants = materialize_bounded_iterable(
            "rejection invariant ids",
            invariant_ids,
            limit=MAX_REJECTION_INVARIANTS,
        )
        if not supplied_invariants:
            raise ValueError("rejections require relevant invariant ids")
        normalized_invariants = tuple(sorted(supplied_invariants))
        if len(normalized_invariants) != len(set(normalized_invariants)):
            raise ValueError("rejection invariant ids must be unique")
        for invariant_id in normalized_invariants:
            require_invariant_id(invariant_id)
        bound_ids = _bounded_fingerprints(
            "bound receipt ids",
            bound_receipt_ids,
            limit=MAX_BOUND_RECEIPT_IDS,
        )
        object.__setattr__(self, "stage", stage)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "task_id", task_id)
        object.__setattr__(self, "governance_id", governance_id)
        object.__setattr__(self, "invariant_ids", normalized_invariants)
        object.__setattr__(self, "bound_receipt_ids", bound_ids)
        object.__setattr__(
            self,
            "_details",
            _canonical_mapping("rejection details", details or {}),
        )

    @property
    def status(self) -> str:
        return "rejected"

    @property
    def details(self) -> dict[str, Any]:
        return self._details.to_value()

    @property
    def receipt_id(self) -> str:
        return self.canonical_record()["receipt_id"]

    def canonical_record(self) -> dict[str, Any]:
        body = {
            "authority_layer": "governance",
            "bound_receipt_ids": list(self.bound_receipt_ids),
            "details": self.details,
            "governance_id": self.governance_id,
            "invariant_ids": list(self.invariant_ids),
            "protocol_version": REJECTION_RECEIPT_VERSION,
            "reason": self.reason.value,
            "stage": self.stage.value,
            "status": self.status,
            "task_id": self.task_id,
        }
        return _with_receipt_id(REJECTION_RECEIPT_ID_DOMAIN, body)

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> RejectionReceipt:
        fields = {
            "authority_layer",
            "bound_receipt_ids",
            "details",
            "governance_id",
            "invariant_ids",
            "protocol_version",
            "reason",
            "receipt_id",
            "stage",
            "status",
            "task_id",
        }
        active = _bounded_exact_mapping("rejection receipt", record, fields)
        try:
            stage = ReceiptStage(active["stage"])
            reason = GovernanceRejectionReason(active["reason"])
        except (TypeError, ValueError) as exc:
            raise ValueError("rejection receipt contains an unknown enum") from exc
        receipt = cls(
            stage,
            reason,
            task_id=active["task_id"],
            governance_id=active["governance_id"],
            invariant_ids=active["invariant_ids"],
            bound_receipt_ids=active["bound_receipt_ids"],
            details=active["details"],
        )
        _require_exact_record("rejection receipt", active, receipt.canonical_record())
        return receipt


@dataclass(frozen=True, slots=True, init=False)
class PartialReceipt:
    reason: PartialReason
    task_id: str
    task_receipt_id: str
    governance_id: str
    governance_receipt_id: str
    orchestration_id: str | None
    orchestration_receipt_id: str | None
    execution_id: str | None
    execution_receipt_id: str | None
    missing_gate_keys: tuple[str, ...]
    bound_gate_results: tuple[AcceptanceGateResult, ...]

    def __init__(
        self,
        policy: GovernancePolicy,
        task: TaskReceipt,
        governance: GovernanceReceipt,
        reason: PartialReason,
        *,
        orchestration: OrchestrationReceipt | None,
        execution: ExecutionReceipt | None,
        missing_gate_keys: Iterable[str],
        gate_results: Iterable[AcceptanceGateResult],
    ) -> None:
        _require_governance_binding(policy, task, governance)
        if not isinstance(reason, PartialReason):
            raise TypeError("reason must be a PartialReason")
        if orchestration is not None:
            _require_orchestration_binding(policy, task, governance, orchestration)
        if execution is not None:
            if orchestration is None:
                raise ValueError("execution cannot exist without orchestration")
            _require_execution_binding(
                policy, task, governance, orchestration, execution
            )
        missing = _bounded_unique_symbols(
            "missing gate keys", missing_gate_keys, limit=MAX_REQUIRED_GATES
        )
        if any(item not in policy.required_gate_keys for item in missing):
            raise ValueError("partial receipt names an undeclared gate")
        results = _normalize_gate_results(gate_results)
        if any(item.gate_key not in policy.required_gate_keys for item in results):
            raise ValueError("partial receipt binds an undeclared gate")
        result_by_key = {item.gate_key: item for item in results}
        compact_result = result_by_key.get(COMPACT_EVIDENCE_GATE_KEY)
        if compact_result is not None and compact_result.satisfied:
            raise ValueError(
                "partial receipts cannot assert unvalidated compact evidence"
            )
        orchestration_result = result_by_key.get(
            ORCHESTRATION_RECEIPT_GATE_KEY
        )
        if orchestration_result is not None and orchestration_result.satisfied:
            if (
                orchestration is None
                or orchestration_result.evidence_receipt_id
                != orchestration.receipt_id
            ):
                raise ValueError(
                    "partial orchestration gate must bind its typed receipt"
                )
        execution_result = result_by_key.get(EXECUTION_RECEIPT_GATE_KEY)
        if execution_result is not None and execution_result.satisfied:
            if (
                execution is None
                or execution_result.evidence_receipt_id != execution.receipt_id
            ):
                raise ValueError(
                    "partial execution gate must bind its typed receipt"
                )
        expected_missing = tuple(
            gate_key
            for gate_key in policy.required_gate_keys
            if gate_key not in result_by_key
            or not result_by_key[gate_key].satisfied
        )
        if missing != expected_missing:
            raise ValueError(
                "partial receipt missing gates must exactly match bound gate results"
            )
        if reason is PartialReason.MISSING_ORCHESTRATION_RECEIPT:
            if orchestration is not None or execution is not None:
                raise ValueError(
                    "missing-orchestration partial state cannot bind later receipts"
                )
        elif reason is PartialReason.MISSING_EXECUTION_RECEIPT:
            if orchestration is None or execution is not None:
                raise ValueError(
                    "missing-execution partial state requires orchestration only"
                )
        elif execution is None or not missing:
            raise ValueError(
                "unsatisfied-gates partial state requires execution and missing gates"
            )
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "task_id", task.task_id)
        object.__setattr__(self, "task_receipt_id", task.receipt_id)
        object.__setattr__(self, "governance_id", policy.governance_id)
        object.__setattr__(self, "governance_receipt_id", governance.receipt_id)
        object.__setattr__(
            self,
            "orchestration_id",
            None if orchestration is None else orchestration.orchestration_id,
        )
        object.__setattr__(
            self,
            "orchestration_receipt_id",
            None if orchestration is None else orchestration.receipt_id,
        )
        object.__setattr__(
            self,
            "execution_id",
            None if execution is None else execution.execution_id,
        )
        object.__setattr__(
            self,
            "execution_receipt_id",
            None if execution is None else execution.receipt_id,
        )
        object.__setattr__(self, "missing_gate_keys", missing)
        object.__setattr__(self, "bound_gate_results", results)

    @property
    def status(self) -> str:
        return "partial"

    @property
    def receipt_id(self) -> str:
        return self.canonical_record()["receipt_id"]

    def canonical_record(self) -> dict[str, Any]:
        body = {
            "authority_layer": "governance",
            "bound_gate_results": [
                item.canonical_record() for item in self.bound_gate_results
            ],
            "execution_id": self.execution_id,
            "execution_receipt_id": self.execution_receipt_id,
            "governance_id": self.governance_id,
            "governance_receipt_id": self.governance_receipt_id,
            "missing_gate_keys": list(self.missing_gate_keys),
            "orchestration_id": self.orchestration_id,
            "orchestration_receipt_id": self.orchestration_receipt_id,
            "protocol_version": PARTIAL_RECEIPT_VERSION,
            "reason": self.reason.value,
            "status": self.status,
            "task_id": self.task_id,
            "task_receipt_id": self.task_receipt_id,
        }
        return _with_receipt_id(PARTIAL_RECEIPT_ID_DOMAIN, body)


@dataclass(frozen=True, slots=True, init=False)
class FinalAcceptanceReceipt:
    task_id: str
    task_receipt_id: str
    governance_id: str
    governance_receipt_id: str
    orchestration_id: str
    orchestration_receipt_id: str
    execution_id: str
    execution_receipt_id: str
    compact_evidence_receipt_id: str
    gate_results: tuple[AcceptanceGateResult, ...]

    def __init__(
        self,
        policy: GovernancePolicy,
        task: TaskReceipt,
        governance: GovernanceReceipt,
        orchestration: OrchestrationReceipt,
        execution: ExecutionReceipt,
        compact_evidence: Any,
        gate_results: Iterable[AcceptanceGateResult],
        *,
        requester: PrincipalAuthority,
    ) -> None:
        _require_execution_binding(
            policy, task, governance, orchestration, execution
        )
        _require_source_bound_execution(execution)
        if requester is not PrincipalAuthority.OPENAI_SUPERVISOR:
            raise ValueError("only the OpenAI supervisor may request final acceptance")
        results = _normalize_gate_results(gate_results)
        result_keys = tuple(item.gate_key for item in results)
        if result_keys != policy.required_gate_keys:
            raise ValueError("final acceptance requires the exact policy gate set")
        if any(not item.satisfied for item in results):
            raise ValueError("final acceptance requires every policy gate")
        compact_evidence_receipt_id = _validate_compact_evidence_binding(
            task,
            policy,
            orchestration,
            execution,
            compact_evidence,
        )
        compact_gate = next(
            item
            for item in results
            if item.gate_key == COMPACT_EVIDENCE_GATE_KEY
        )
        if compact_gate.evidence_receipt_id != compact_evidence_receipt_id:
            raise ValueError(
                "compact evidence gate must bind the validated evidence receipt"
            )
        orchestration_gate = next(
            item
            for item in results
            if item.gate_key == ORCHESTRATION_RECEIPT_GATE_KEY
        )
        if orchestration_gate.evidence_receipt_id != orchestration.receipt_id:
            raise ValueError(
                "orchestration gate must bind the validated orchestration receipt"
            )
        execution_gate = next(
            item
            for item in results
            if item.gate_key == EXECUTION_RECEIPT_GATE_KEY
        )
        if execution_gate.evidence_receipt_id != execution.receipt_id:
            raise ValueError(
                "execution gate must bind the validated execution receipt"
            )
        object.__setattr__(self, "task_id", task.task_id)
        object.__setattr__(self, "task_receipt_id", task.receipt_id)
        object.__setattr__(self, "governance_id", policy.governance_id)
        object.__setattr__(self, "governance_receipt_id", governance.receipt_id)
        object.__setattr__(self, "orchestration_id", orchestration.orchestration_id)
        object.__setattr__(
            self, "orchestration_receipt_id", orchestration.receipt_id
        )
        object.__setattr__(self, "execution_id", execution.execution_id)
        object.__setattr__(self, "execution_receipt_id", execution.receipt_id)
        object.__setattr__(
            self,
            "compact_evidence_receipt_id",
            compact_evidence_receipt_id,
        )
        object.__setattr__(self, "gate_results", results)

    def identity_record(self) -> dict[str, object]:
        return {
            "compact_evidence_receipt_id": self.compact_evidence_receipt_id,
            "execution_id": self.execution_id,
            "execution_receipt_id": self.execution_receipt_id,
            "gate_result_ids": [item.gate_result_id for item in self.gate_results],
            "governance_id": self.governance_id,
            "governance_receipt_id": self.governance_receipt_id,
            "orchestration_id": self.orchestration_id,
            "orchestration_receipt_id": self.orchestration_receipt_id,
            "task_id": self.task_id,
            "task_receipt_id": self.task_receipt_id,
        }

    @property
    def final_acceptance_id(self) -> str:
        return domain_fingerprint(FINAL_ACCEPTANCE_ID_DOMAIN, self.identity_record())

    @property
    def status(self) -> str:
        return "accepted"

    @property
    def receipt_id(self) -> str:
        return self.canonical_record()["receipt_id"]

    def canonical_record(self) -> dict[str, Any]:
        body = {
            **self.identity_record(),
            "authority_layer": "governance",
            "final_acceptance_id": self.final_acceptance_id,
            "gate_results": [item.canonical_record() for item in self.gate_results],
            "producer_authentication_scope": PRODUCER_AUTHENTICATION_SCOPE,
            "protocol_version": FINAL_ACCEPTANCE_RECEIPT_VERSION,
            "status": self.status,
            "verification_scope": DETERMINISTIC_VERIFICATION_SCOPE,
        }
        return _with_receipt_id(FINAL_ACCEPTANCE_RECEIPT_ID_DOMAIN, body)


class GovernanceRejected(RuntimeError):
    """Fail-closed governance decision with a canonical rejection receipt."""

    def __init__(self, receipt: RejectionReceipt) -> None:
        if not isinstance(receipt, RejectionReceipt):
            raise TypeError("receipt must be a RejectionReceipt")
        self.receipt = receipt
        super().__init__(receipt.reason.value)


class GovernanceWrapper:
    """Small v0.4 authority surface above orchestration and execution."""

    __slots__ = ("__policy",)

    def __init__(self, policy: GovernancePolicy) -> None:
        if type(policy) is not GovernancePolicy:
            raise TypeError("policy must be a GovernancePolicy")
        # Snapshot the canonical policy so later caller-side mutation of the
        # frozen Python value (including object.__setattr__ bypasses) cannot
        # rewrite active governance authority.
        self.__policy = GovernancePolicy.from_record(policy.canonical_record())

    @property
    def governance_id(self) -> str:
        return self.__policy.governance_id

    @property
    def policy_record(self) -> dict[str, object]:
        """Return a copy, never a mutable governance authority object."""

        return CanonicalValue.from_value(self.__policy.canonical_record()).to_value()

    def admit_task(
        self,
        task_key: str,
        acceptance_contract: Mapping[str, Any],
        *,
        requester: PrincipalAuthority,
        contract_version: int = 1,
    ) -> tuple[TaskReceipt, GovernanceReceipt]:
        if requester is not PrincipalAuthority.OPENAI_SUPERVISOR:
            self._reject(
                ReceiptStage.GOVERNANCE,
                GovernanceRejectionReason.AUTHORITY_ESCALATION,
                invariant_ids=("IBAE-GOV-002", "IBAE-LAY-002"),
                details={"requested_operation": "admit_task"},
            )
        task = TaskReceipt(
            task_key,
            acceptance_contract,
            required_gate_keys=self.__policy.required_gate_keys,
            contract_version=contract_version,
        )
        return task, GovernanceReceipt(self.__policy, task, requester)

    def admit_tool(
        self,
        task: TaskReceipt,
        governance: GovernanceReceipt,
        admission_decision: AdmissionDecision,
        proposal: ActionProposal,
        capability: Capability,
        authority_class: ToolAuthorityClass,
        *,
        dependency_state_id: str | None,
        requester: PrincipalAuthority,
    ) -> ToolAdmissionReceipt:
        _require_governance_binding(self.__policy, task, governance)
        if requester is not PrincipalAuthority.DETERMINISTIC_ORCHESTRATOR:
            self._reject(
                ReceiptStage.GOVERNANCE,
                GovernanceRejectionReason.AUTHORITY_ESCALATION,
                task=task,
                governance=governance,
                invariant_ids=("IBAE-GOV-003", "IBAE-LAY-002"),
                details={"requested_operation": "admit_tool"},
            )
        if (
            not isinstance(admission_decision, AdmissionDecision)
            or not isinstance(proposal, ActionProposal)
            or not isinstance(capability, Capability)
        ):
            self._reject(
                ReceiptStage.GOVERNANCE,
                GovernanceRejectionReason.MALFORMED_ACTION,
                task=task,
                governance=governance,
                invariant_ids=("IBAE-DET-001", "IBAE-GOV-006"),
                details={"record_type": "typed_v0.2_admission"},
            )
        tool_name = capability.name
        try:
            permission = self.__policy.permission_for(tool_name)
        except (TypeError, ValueError):
            self._reject(
                ReceiptStage.GOVERNANCE,
                GovernanceRejectionReason.UNKNOWN_TOOL_PERMISSION,
                task=task,
                governance=governance,
                invariant_ids=("IBAE-GOV-004", "IBAE-GOV-006"),
                details={"requested_operation": "admit_tool"},
            )
        if permission is None:
            self._reject(
                ReceiptStage.GOVERNANCE,
                GovernanceRejectionReason.UNKNOWN_TOOL_PERMISSION,
                task=task,
                governance=governance,
                invariant_ids=("IBAE-GOV-004", "IBAE-GOV-006"),
                details={"tool_name": tool_name},
            )
        if not isinstance(authority_class, ToolAuthorityClass):
            self._reject(
                ReceiptStage.GOVERNANCE,
                GovernanceRejectionReason.UNKNOWN_AUTHORITY,
                task=task,
                governance=governance,
                invariant_ids=("IBAE-GOV-004", "IBAE-GOV-006"),
                details={"tool_name": tool_name},
            )
        assert permission is not None
        if authority_class is not permission.authority_class:
            self._reject(
                ReceiptStage.GOVERNANCE,
                GovernanceRejectionReason.TOOL_CLASS_MISMATCH,
                task=task,
                governance=governance,
                invariant_ids=("IBAE-GOV-004", "IBAE-ORCH-003"),
                details={"tool_name": tool_name},
            )
        if authority_class.is_mutation and not permission.allow_mutation:
            self._reject(
                ReceiptStage.GOVERNANCE,
                GovernanceRejectionReason.MUTATION_NOT_PERMITTED,
                task=task,
                governance=governance,
                invariant_ids=("IBAE-GOV-004", "IBAE-GOV-006"),
                details={"tool_name": tool_name},
            )
        if dependency_state_id is None:
            self._reject(
                ReceiptStage.GOVERNANCE,
                GovernanceRejectionReason.DEPENDENCY_ID_REQUIRED,
                task=task,
                governance=governance,
                invariant_ids=("IBAE-REUSE-001", "IBAE-REUSE-002"),
                details={"tool_name": tool_name},
            )
        occurrence_key = proposal.occurrence_key
        if (
            authority_class.is_mutation
            or authority_class is ToolAuthorityClass.VOLATILE_READ
        ) and occurrence_key is None:
            self._reject(
                ReceiptStage.GOVERNANCE,
                GovernanceRejectionReason.OCCURRENCE_ID_REQUIRED,
                task=task,
                governance=governance,
                invariant_ids=("IBAE-GOV-004", "IBAE-ORCH-007"),
                details={"tool_name": tool_name},
            )
        if authority_class in {
            ToolAuthorityClass.PURE_READ,
            ToolAuthorityClass.SNAPSHOT_READ,
        } and occurrence_key is not None:
            self._reject(
                ReceiptStage.GOVERNANCE,
                GovernanceRejectionReason.OCCURRENCE_ID_FORBIDDEN,
                task=task,
                governance=governance,
                invariant_ids=("IBAE-GOV-004", "IBAE-ORCH-007"),
                details={"tool_name": tool_name},
            )
        try:
            return ToolAdmissionReceipt(
                self.__policy,
                task,
                governance,
                permission,
                requester,
                admission_decision,
                proposal,
                capability,
                dependency_state_id,
            )
        except (TypeError, ValueError, OverflowError, RecursionError) as exc:
            self._reject(
                ReceiptStage.GOVERNANCE,
                GovernanceRejectionReason.MALFORMED_ACTION,
                task=task,
                governance=governance,
                invariant_ids=("IBAE-DET-001", "IBAE-GOV-006"),
                details={"tool_name": tool_name},
            )
            raise AssertionError("unreachable") from exc

    def bind_orchestration(
        self,
        task: TaskReceipt,
        governance: GovernanceReceipt,
        admission_receipt: AdmissionReceipt,
        tool_admissions: Iterable[ToolAdmissionReceipt],
    ) -> OrchestrationReceipt:
        try:
            return OrchestrationReceipt(
                self.__policy,
                task,
                governance,
                admission_receipt,
                tool_admissions,
            )
        except (TypeError, ValueError) as exc:
            self._reject(
                ReceiptStage.ORCHESTRATION,
                GovernanceRejectionReason.INVALID_BOUND_RECEIPT,
                task=task,
                governance=governance,
                invariant_ids=("IBAE-GOV-007", "IBAE-ID-003"),
                details={"record_type": "orchestration"},
            )
            raise AssertionError("unreachable") from exc

    def bind_execution(
        self,
        task: TaskReceipt,
        governance: GovernanceReceipt,
        orchestration: OrchestrationReceipt,
        evidence_summary: Any,
    ) -> ExecutionReceipt:
        try:
            from .evidence import EvidenceAggregateSummary

            if type(evidence_summary) is not EvidenceAggregateSummary:
                raise TypeError(
                    "evidence_summary must be an EvidenceAggregateSummary"
                )
            if evidence_summary.source_bound is not True:
                raise ValueError("execution evidence summary must be source-bound")
            if (
                evidence_summary.task_identity != task.task_id
                or evidence_summary.governance_identity
                != self.__policy.governance_id
                or evidence_summary.orchestration_identity
                != orchestration.orchestration_id
            ):
                raise ValueError(
                    "execution evidence summary authority context does not match"
                )
            if evidence_summary.child_receipt_count != 0:
                raise ValueError(
                    "v1 finalizable execution requires direct runtime cases"
                )
            if (
                evidence_summary.case_record_count
                != evidence_summary.case_counts.total
            ):
                raise ValueError(
                    "execution summary must account for every direct runtime case"
                )
            initial_runtime_receipt = evidence_summary.first_runtime_receipt
            final_runtime_receipt = evidence_summary.last_runtime_receipt
            if type(initial_runtime_receipt) is not RuntimeReceipt or type(
                final_runtime_receipt
            ) is not RuntimeReceipt:
                raise ValueError(
                    "source-bound execution summary requires typed runtime boundaries"
                )
            execution = ExecutionReceipt(
                self.__policy,
                task,
                governance,
                orchestration,
                initial_runtime_receipt,
                final_runtime_receipt,
                aggregate_admission_id=(
                    evidence_summary.aggregate_admission_identity
                ),
                aggregate_input_id=evidence_summary.aggregate_input_identity,
                aggregate_result_id=evidence_summary.aggregate_result_identity,
                aggregate_receipt_id=evidence_summary.aggregate_receipt_identity,
                transition_count=evidence_summary.case_counts.total,
            )
            if (
                evidence_summary.authorization_manifest_identity
                != orchestration.authorization_manifest_id
                or evidence_summary.authorization_manifest_count
                != orchestration.authorization_manifest_count
            ):
                raise ValueError(
                    "execution evidence authorization manifest does not match "
                    "orchestration"
                )
            expected_boundary = {
                "final_runtime_receipt_id": execution.final_runtime_receipt.receipt_id,
                "final_runtime_state_id": execution.identity_record()[
                    "final_runtime_state_id"
                ],
                "initial_runtime_receipt_id": (
                    execution.initial_runtime_receipt.receipt_id
                ),
                "initial_runtime_state_id": execution.initial_runtime_state_id,
                "runtime_session_id": execution.identity_record()[
                    "runtime_session_id"
                ],
            }
            summary_boundary = {
                "final_runtime_receipt_id": (
                    evidence_summary.last_runtime_receipt_id
                ),
                "final_runtime_state_id": evidence_summary.final_runtime_state_id,
                "initial_runtime_receipt_id": (
                    evidence_summary.first_runtime_receipt_id
                ),
                "initial_runtime_state_id": (
                    evidence_summary.initial_runtime_state_id
                ),
                "runtime_session_id": evidence_summary.runtime_session_id,
            }
            if summary_boundary != expected_boundary:
                raise ValueError(
                    "execution summary runtime boundary does not match typed receipts"
                )
            return execution
        except (TypeError, ValueError) as exc:
            self._reject(
                ReceiptStage.EXECUTION,
                GovernanceRejectionReason.INVALID_BOUND_RECEIPT,
                task=task,
                governance=governance,
                invariant_ids=("IBAE-GOV-007", "IBAE-ID-004"),
                details={"record_type": "execution"},
            )
            raise AssertionError("unreachable") from exc

    def finalize(
        self,
        task: TaskReceipt,
        governance: GovernanceReceipt,
        orchestration: OrchestrationReceipt | None,
        execution: ExecutionReceipt | None,
        compact_evidence: Any | None,
        gate_results: Iterable[AcceptanceGateResult],
        *,
        requester: PrincipalAuthority,
    ) -> FinalAcceptanceReceipt | PartialReceipt:
        try:
            _require_governance_binding(self.__policy, task, governance)
        except (TypeError, ValueError):
            self._reject(
                ReceiptStage.FINALIZATION,
                GovernanceRejectionReason.INVALID_BOUND_RECEIPT,
                invariant_ids=("IBAE-GOV-007", "IBAE-ID-004"),
                details={"record_type": "governance_context"},
            )
        if requester is not PrincipalAuthority.OPENAI_SUPERVISOR:
            self._reject(
                ReceiptStage.FINALIZATION,
                GovernanceRejectionReason.AUTHORITY_ESCALATION,
                task=task,
                governance=governance,
                invariant_ids=("IBAE-GOV-002", "IBAE-GOV-007", "IBAE-LAY-002"),
                details={"requested_operation": "finalize"},
            )
        try:
            results = _normalize_gate_results(gate_results)
        except (TypeError, ValueError):
            self._reject(
                ReceiptStage.FINALIZATION,
                GovernanceRejectionReason.INVALID_BOUND_RECEIPT,
                task=task,
                governance=governance,
                invariant_ids=("IBAE-GOV-006", "IBAE-GOV-007"),
                details={"record_type": "acceptance_gate_results"},
            )
        unknown = tuple(
            item.gate_key
            for item in results
            if item.gate_key not in self.__policy.required_gate_keys
        )
        if unknown:
            self._reject(
                ReceiptStage.FINALIZATION,
                GovernanceRejectionReason.UNKNOWN_ACCEPTANCE_GATE,
                task=task,
                governance=governance,
                invariant_ids=("IBAE-GOV-006", "IBAE-GOV-007"),
                details={"unknown_gate_keys": list(unknown)},
            )
        result_by_key = {item.gate_key: item for item in results}
        missing = tuple(
            key
            for key in self.__policy.required_gate_keys
            if key not in result_by_key or not result_by_key[key].satisfied
        )

        def partial_receipt(
            reason: PartialReason,
            *,
            bound_orchestration: OrchestrationReceipt | None,
            bound_execution: ExecutionReceipt | None,
        ) -> PartialReceipt:
            try:
                return PartialReceipt(
                    self.__policy,
                    task,
                    governance,
                    reason,
                    orchestration=bound_orchestration,
                    execution=bound_execution,
                    missing_gate_keys=missing,
                    gate_results=results,
                )
            except (TypeError, ValueError) as exc:
                self._reject(
                    ReceiptStage.FINALIZATION,
                    GovernanceRejectionReason.INVALID_BOUND_RECEIPT,
                    task=task,
                    governance=governance,
                    invariant_ids=("IBAE-GOV-006", "IBAE-GOV-007"),
                    details={"record_type": "partial"},
                )
                raise AssertionError("unreachable") from exc

        if orchestration is None:
            return partial_receipt(
                PartialReason.MISSING_ORCHESTRATION_RECEIPT,
                bound_orchestration=None,
                bound_execution=None,
            )
        try:
            _require_orchestration_binding(
                self.__policy, task, governance, orchestration
            )
        except (TypeError, ValueError):
            self._reject(
                ReceiptStage.FINALIZATION,
                GovernanceRejectionReason.INVALID_BOUND_RECEIPT,
                task=task,
                governance=governance,
                invariant_ids=("IBAE-GOV-007", "IBAE-ID-004"),
                details={"record_type": "orchestration"},
            )
        if execution is None:
            return partial_receipt(
                PartialReason.MISSING_EXECUTION_RECEIPT,
                bound_orchestration=orchestration,
                bound_execution=None,
            )
        try:
            _require_execution_binding(
                self.__policy, task, governance, orchestration, execution
            )
        except (TypeError, ValueError):
            self._reject(
                ReceiptStage.FINALIZATION,
                GovernanceRejectionReason.INVALID_BOUND_RECEIPT,
                task=task,
                governance=governance,
                invariant_ids=("IBAE-GOV-007", "IBAE-ID-004"),
                details={"record_type": "execution"},
            )
        if missing:
            return partial_receipt(
                PartialReason.UNSATISFIED_ACCEPTANCE_GATES,
                bound_orchestration=orchestration,
                bound_execution=execution,
            )
        if compact_evidence is None:
            self._reject(
                ReceiptStage.FINALIZATION,
                GovernanceRejectionReason.INVALID_BOUND_RECEIPT,
                task=task,
                governance=governance,
                invariant_ids=("IBAE-GOV-007", "IBAE-ID-004"),
                details={"record_type": "compact_evidence"},
            )
        try:
            return FinalAcceptanceReceipt(
                self.__policy,
                task,
                governance,
                orchestration,
                execution,
                compact_evidence,
                results,
                requester=requester,
            )
        except (TypeError, ValueError) as exc:
            self._reject(
                ReceiptStage.FINALIZATION,
                GovernanceRejectionReason.INVALID_BOUND_RECEIPT,
                task=task,
                governance=governance,
                invariant_ids=("IBAE-GOV-007", "IBAE-ID-004"),
                details={"record_type": "final_acceptance"},
            )
            raise AssertionError("unreachable") from exc

    def _reject(
        self,
        stage: ReceiptStage,
        reason: GovernanceRejectionReason,
        *,
        invariant_ids: Iterable[str],
        task: TaskReceipt | None = None,
        governance: GovernanceReceipt | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        raise GovernanceRejected(
            RejectionReceipt(
                stage,
                reason,
                task_id=None if task is None else task.task_id,
                governance_id=self.__policy.governance_id,
                invariant_ids=invariant_ids,
                bound_receipt_ids=(
                    () if governance is None else (governance.receipt_id,)
                ),
                details=details,
            )
        )


class ReceiptValidator:
    """Independent reconstruction validators for every v0.4 receipt class."""

    @staticmethod
    def validate_policy(record: Mapping[str, Any]) -> GovernancePolicy:
        return GovernancePolicy.from_record(record)

    @staticmethod
    def validate_task(record: Mapping[str, Any]) -> TaskReceipt:
        return TaskReceipt.from_record(record)

    @staticmethod
    def validate_governance(
        record: Mapping[str, Any],
        *,
        policy: GovernancePolicy,
        task: TaskReceipt,
    ) -> GovernanceReceipt:
        return GovernanceReceipt.from_record(record, policy=policy, task=task)

    @staticmethod
    def validate_tool_admission(
        record: Mapping[str, Any],
        *,
        policy: GovernancePolicy,
        task: TaskReceipt,
        governance: GovernanceReceipt,
        admission_decision: AdmissionDecision,
        proposal: ActionProposal,
        capability: Capability,
    ) -> ToolAdmissionReceipt:
        required = {
            "action_id",
            "arguments",
            "arguments_id",
            "authority_class",
            "authority_layer",
            "cache_reuse_permitted",
            "capability_id",
            "decision_id",
            "dependency_fingerprint",
            "governance_id",
            "governance_receipt_id",
            "governed_action_id",
            "occurrence_key",
            "permission_id",
            "proposal_id",
            "protocol_version",
            "receipt_id",
            "requester",
            "replay_safety",
            "status",
            "task_id",
            "tool_name",
        }
        active = _bounded_exact_mapping(
            "tool admission receipt",
            record,
            required,
        )
        try:
            authority_class = ToolAuthorityClass(active["authority_class"])
            requester = PrincipalAuthority(active["requester"])
        except (TypeError, ValueError) as exc:
            raise ValueError("tool admission contains an unknown authority") from exc
        permission = policy.permission_for(active["tool_name"])
        if permission is None or permission.authority_class is not authority_class:
            raise ValueError("tool admission is not bound to an active permission")
        expected = ToolAdmissionReceipt(
            policy,
            task,
            governance,
            permission,
            requester,
            admission_decision,
            proposal,
            capability,
            active["dependency_fingerprint"],
        )
        _require_exact_record(
            "tool admission receipt", active, expected.canonical_record()
        )
        return expected

    @staticmethod
    def validate_orchestration(
        record: Mapping[str, Any],
        *,
        policy: GovernancePolicy,
        task: TaskReceipt,
        governance: GovernanceReceipt,
        admission_receipt: AdmissionReceipt,
        tool_admissions: Iterable[ToolAdmissionReceipt],
    ) -> OrchestrationReceipt:
        expected = OrchestrationReceipt(
            policy,
            task,
            governance,
            admission_receipt,
            tool_admissions,
        )
        _require_exact_record(
            "orchestration receipt", record, expected.canonical_record()
        )
        return expected

    @staticmethod
    def validate_execution(
        record: Mapping[str, Any],
        *,
        policy: GovernancePolicy,
        task: TaskReceipt,
        governance: GovernanceReceipt,
        orchestration: OrchestrationReceipt,
        initial_runtime_receipt: RuntimeReceipt,
        final_runtime_receipt: RuntimeReceipt,
    ) -> ExecutionReceipt:
        required = {
            "aggregate_admission_id",
            "aggregate_input_id",
            "aggregate_receipt_id",
            "aggregate_result_id",
            "authorization_manifest_count",
            "authorization_manifest_id",
            "authority_layer",
            "execution_id",
            "final_runtime_receipt_id",
            "final_runtime_state_id",
            "governance_id",
            "initial_runtime_receipt_id",
            "initial_runtime_state_id",
            "orchestration_id",
            "orchestration_receipt_id",
            "protocol_version",
            "receipt_id",
            "runtime_session_id",
            "status",
            "task_id",
            "transition_count",
        }
        active = _bounded_exact_mapping("execution receipt", record, required)
        expected = ExecutionReceipt(
            policy,
            task,
            governance,
            orchestration,
            initial_runtime_receipt,
            final_runtime_receipt,
            aggregate_admission_id=active["aggregate_admission_id"],
            aggregate_input_id=active["aggregate_input_id"],
            aggregate_result_id=active["aggregate_result_id"],
            aggregate_receipt_id=active["aggregate_receipt_id"],
            transition_count=active["transition_count"],
        )
        _require_exact_record("execution receipt", active, expected.canonical_record())
        return expected

    @staticmethod
    def validate_execution_plan(
        record: Mapping[str, Any],
        *,
        policy: GovernancePolicy,
        task: TaskReceipt,
        governance: GovernanceReceipt,
        orchestration: OrchestrationReceipt,
    ) -> ExecutionPlanReceipt:
        if not isinstance(record, Mapping) or "plan" not in record:
            raise ValueError("execution-plan receipt does not match the v1 schema")
        expected = ExecutionPlanReceipt(
            policy, task, governance, orchestration, record["plan"]
        )
        _require_exact_record(
            "execution-plan receipt", record, expected.canonical_record()
        )
        return expected

    @staticmethod
    def validate_benchmark(
        record: Mapping[str, Any],
        *,
        task: TaskReceipt,
        execution: ExecutionReceipt,
    ) -> BenchmarkReceipt:
        if not isinstance(record, Mapping) or "observations" not in record:
            raise ValueError("benchmark receipt does not match the v1 schema")
        expected = BenchmarkReceipt(task, execution, record["observations"])
        _require_exact_record("benchmark receipt", record, expected.canonical_record())
        return expected

    @staticmethod
    def validate_rejection(record: Mapping[str, Any]) -> RejectionReceipt:
        return RejectionReceipt.from_record(record)

    @staticmethod
    def validate_partial(
        record: Mapping[str, Any],
        *,
        policy: GovernancePolicy,
        task: TaskReceipt,
        governance: GovernanceReceipt,
        orchestration: OrchestrationReceipt | None,
        execution: ExecutionReceipt | None,
    ) -> PartialReceipt:
        if not isinstance(record, Mapping):
            raise TypeError("partial receipt must be a mapping")
        try:
            reason = PartialReason(record["reason"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("partial receipt contains an unknown reason") from exc
        try:
            gate_result_records = materialize_bounded_iterable(
                "partial receipt gate results",
                record["bound_gate_results"],
                limit=MAX_REQUIRED_GATES,
            )
            missing_gate_keys = materialize_bounded_iterable(
                "partial receipt missing gate keys",
                record["missing_gate_keys"],
                limit=MAX_REQUIRED_GATES,
            )
            gate_results = tuple(
                AcceptanceGateResult(
                    item["gate_key"],
                    item["satisfied"],
                    item["evidence_receipt_id"],
                )
                for item in gate_result_records
            )
        except (KeyError, TypeError) as exc:
            raise ValueError("partial receipt has malformed gate state") from exc
        expected = PartialReceipt(
            policy,
            task,
            governance,
            reason,
            orchestration=orchestration,
            execution=execution,
            missing_gate_keys=missing_gate_keys,
            gate_results=gate_results,
        )
        _require_exact_record("partial receipt", record, expected.canonical_record())
        return expected

    @staticmethod
    def validate_final(
        record: Mapping[str, Any],
        *,
        policy: GovernancePolicy,
        task: TaskReceipt,
        governance: GovernanceReceipt,
        orchestration: OrchestrationReceipt,
        execution: ExecutionReceipt,
        compact_evidence: Any,
    ) -> FinalAcceptanceReceipt:
        if not isinstance(record, Mapping):
            raise TypeError("final acceptance receipt must be a mapping")
        try:
            gate_result_records = materialize_bounded_iterable(
                "final receipt gate results",
                record["gate_results"],
                limit=MAX_REQUIRED_GATES,
            )
            gate_results = tuple(
                AcceptanceGateResult(
                    item["gate_key"],
                    item["satisfied"],
                    item["evidence_receipt_id"],
                )
                for item in gate_result_records
            )
        except (KeyError, TypeError) as exc:
            raise ValueError("final receipt has malformed gate state") from exc
        expected = FinalAcceptanceReceipt(
            policy,
            task,
            governance,
            orchestration,
            execution,
            compact_evidence,
            gate_results,
            requester=PrincipalAuthority.OPENAI_SUPERVISOR,
        )
        _require_exact_record(
            "final acceptance receipt", record, expected.canonical_record()
        )
        return expected


def _normalize_gate_results(
    gate_results: Iterable[AcceptanceGateResult],
) -> tuple[AcceptanceGateResult, ...]:
    supplied = materialize_bounded_iterable(
        "acceptance gate results", gate_results, limit=MAX_REQUIRED_GATES
    )
    validated: list[AcceptanceGateResult] = []
    for item in supplied:
        if type(item) is not AcceptanceGateResult:
            raise TypeError(
                "gate_results must contain exact AcceptanceGateResult records"
            )
        expected = AcceptanceGateResult(
            item.gate_key,
            item.satisfied,
            item.evidence_receipt_id,
        )
        if item.canonical_record() != expected.canonical_record():
            raise ValueError("acceptance gate result is not canonically valid")
        validated.append(expected)
    normalized = tuple(sorted(validated, key=lambda item: item.gate_key))
    keys = tuple(item.gate_key for item in normalized)
    if len(keys) != len(set(keys)):
        raise ValueError("acceptance gate result keys must be unique")
    return normalized


def _require_governance_binding(
    policy: GovernancePolicy,
    task: TaskReceipt,
    governance: GovernanceReceipt,
) -> None:
    if type(policy) is not GovernancePolicy:
        raise TypeError("policy must be a GovernancePolicy")
    if type(task) is not TaskReceipt:
        raise TypeError("task must be a TaskReceipt")
    if type(governance) is not GovernanceReceipt:
        raise TypeError("governance must be a GovernanceReceipt")
    expected_policy = GovernancePolicy.from_record(policy.canonical_record())
    if policy.canonical_record() != expected_policy.canonical_record():
        raise ValueError("governance policy is not canonically valid")
    expected_task = TaskReceipt(
        task.task_key,
        task.acceptance_contract,
        required_gate_keys=task.required_gate_keys,
        contract_version=task.contract_version,
    )
    if task.canonical_record() != expected_task.canonical_record():
        raise ValueError("task receipt is not canonically valid")
    expected = GovernanceReceipt(
        policy, task, PrincipalAuthority.OPENAI_SUPERVISOR
    )
    if governance.canonical_record() != expected.canonical_record():
        raise ValueError("governance receipt does not bind the active policy and task")


def _require_tool_admission_binding(
    policy: GovernancePolicy,
    task: TaskReceipt,
    governance: GovernanceReceipt,
    tool_admission: ToolAdmissionReceipt,
) -> None:
    _require_governance_binding(policy, task, governance)
    if type(tool_admission) is not ToolAdmissionReceipt:
        raise TypeError("tool admission must be a ToolAdmissionReceipt")
    permission = policy.permission_for(tool_admission.tool_name)
    if permission is None:
        raise ValueError("tool admission does not bind an active permission")
    expected = ToolAdmissionReceipt(
        policy,
        task,
        governance,
        permission,
        PrincipalAuthority.DETERMINISTIC_ORCHESTRATOR,
        tool_admission.admission_decision,
        tool_admission.proposal,
        tool_admission.capability,
        tool_admission.dependency_fingerprint,
    )
    if tool_admission.canonical_record() != expected.canonical_record():
        raise ValueError("tool admission receipt is not canonically valid")


def _require_orchestration_binding(
    policy: GovernancePolicy,
    task: TaskReceipt,
    governance: GovernanceReceipt,
    orchestration: OrchestrationReceipt,
) -> None:
    _require_governance_binding(policy, task, governance)
    if type(orchestration) is not OrchestrationReceipt:
        raise TypeError("orchestration must be an OrchestrationReceipt")
    if (
        orchestration.task_id != task.task_id
        or orchestration.governance_id != policy.governance_id
        or orchestration.governance_receipt_id != governance.receipt_id
    ):
        raise ValueError("orchestration receipt does not bind the governed task")
    expected = OrchestrationReceipt(
        policy,
        task,
        governance,
        orchestration.admission_receipt,
        orchestration.tool_admissions,
    )
    if orchestration.canonical_record() != expected.canonical_record():
        raise ValueError("orchestration receipt is not canonically valid")


def _require_execution_binding(
    policy: GovernancePolicy,
    task: TaskReceipt,
    governance: GovernanceReceipt,
    orchestration: OrchestrationReceipt,
    execution: ExecutionReceipt,
) -> None:
    _require_orchestration_binding(policy, task, governance, orchestration)
    if type(execution) is not ExecutionReceipt:
        raise TypeError("execution must be an ExecutionReceipt")
    if (
        execution.task_id != task.task_id
        or execution.governance_id != policy.governance_id
        or execution.orchestration_id != orchestration.orchestration_id
        or execution.orchestration_receipt_id != orchestration.receipt_id
    ):
        raise ValueError("execution receipt does not bind the governed orchestration")
    expected = ExecutionReceipt(
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
        transition_count=execution.transition_count,
    )
    if execution.canonical_record() != expected.canonical_record():
        raise ValueError("execution receipt is not canonically valid")


def _require_source_bound_execution(execution: ExecutionReceipt) -> None:
    if (
        type(execution.initial_runtime_receipt) is not RuntimeReceipt
        or type(execution.final_runtime_receipt) is not RuntimeReceipt
        or execution.initial_runtime_receipt.source_bound is not True
        or execution.final_runtime_receipt.source_bound is not True
    ):
        raise ValueError(
            "finalizable execution requires exact source-bound runtime endpoints"
        )


def _validate_compact_evidence_binding(
    task: TaskReceipt,
    policy: GovernancePolicy,
    orchestration: OrchestrationReceipt,
    execution: ExecutionReceipt,
    compact_evidence: Any,
) -> str:
    # Local import keeps governance independent from the evidence reducer and
    # prevents either layer from acquiring the other's authority.
    from .evidence import EVIDENCE_PROFILE, CompactEvidenceReceipt

    if type(compact_evidence) is not CompactEvidenceReceipt:
        raise TypeError("compact_evidence must be a CompactEvidenceReceipt")
    if compact_evidence.evidence_profile != EVIDENCE_PROFILE:
        raise ValueError("compact evidence profile is not admitted")
    if compact_evidence.status != "complete_no_failures":
        raise ValueError("compact evidence does not establish failure-free completion")
    if compact_evidence.source_bound is not True:
        raise ValueError("compact evidence was not produced from live bound inputs")
    if compact_evidence.child_receipt_count != 0:
        raise ValueError(
            "hierarchical compact evidence is not finalizable in the v1 profile"
        )
    if compact_evidence.case_record_count != compact_evidence.case_counts.total:
        raise ValueError(
            "compact evidence must account for every direct runtime case"
        )
    if compact_evidence.task_identity != task.task_id:
        raise ValueError("compact evidence task identity mismatch")
    if compact_evidence.governance_identity != policy.governance_id:
        raise ValueError("compact evidence governance identity mismatch")
    if compact_evidence.orchestration_identity != orchestration.orchestration_id:
        raise ValueError("compact evidence orchestration identity mismatch")
    if compact_evidence.execution_identity != execution.execution_id:
        raise ValueError("compact evidence execution identity mismatch")
    if (
        compact_evidence.authorization_manifest_identity
        != execution.authorization_manifest_id
        or compact_evidence.authorization_manifest_count
        != execution.authorization_manifest_count
    ):
        raise ValueError("compact evidence authorization manifest mismatch")
    if (
        compact_evidence.aggregate_admission_identity
        != execution.aggregate_admission_id
    ):
        raise ValueError("compact evidence aggregate admission identity mismatch")
    if compact_evidence.aggregate_input_identity != execution.aggregate_input_id:
        raise ValueError("compact evidence aggregate input identity mismatch")
    if compact_evidence.aggregate_result_identity != execution.aggregate_result_id:
        raise ValueError("compact evidence aggregate result identity mismatch")
    if compact_evidence.aggregate_receipt_identity != execution.aggregate_receipt_id:
        raise ValueError("compact evidence aggregate receipt identity mismatch")
    if compact_evidence.case_counts.total != execution.transition_count:
        raise ValueError("compact evidence transition count mismatch")
    execution_record = execution.identity_record()
    compact_boundary = {
        "final_runtime_receipt_id": compact_evidence.last_runtime_receipt_id,
        "final_runtime_state_id": compact_evidence.final_runtime_state_id,
        "initial_runtime_receipt_id": compact_evidence.first_runtime_receipt_id,
        "initial_runtime_state_id": compact_evidence.initial_runtime_state_id,
        "runtime_session_id": compact_evidence.runtime_session_id,
    }
    execution_boundary = {
        "final_runtime_receipt_id": execution_record["final_runtime_receipt_id"],
        "final_runtime_state_id": execution_record["final_runtime_state_id"],
        "initial_runtime_receipt_id": execution_record[
            "initial_runtime_receipt_id"
        ],
        "initial_runtime_state_id": execution_record["initial_runtime_state_id"],
        "runtime_session_id": execution_record["runtime_session_id"],
    }
    if compact_boundary != execution_boundary:
        raise ValueError("compact evidence runtime boundary mismatch")
    require_fingerprint("compact evidence receipt id", compact_evidence.receipt_id)
    return compact_evidence.receipt_id
