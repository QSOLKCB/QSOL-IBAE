"""Deterministic v0.5 objective-progress and bounded-continuation contracts.

The module deliberately separates four authorities:

* orchestration supplies canonical obligation state;
* governance precommits a finite continuation policy and grants or denies;
* the Rust runtime applies an already granted exact resource vector; and
* benchmark observations remain non-authoritative.

No object in this module calls a model provider.  In particular, a request is
not a grant, a strategy change is not proof of progress, and elapsed time is
not task completion.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Final

from ._records import (
    CanonicalValue,
    materialize_bounded_iterable,
    require_fingerprint,
    require_positive_int,
    require_symbol,
    require_text,
)
from .canonical import canonical_fingerprint, canonical_json, domain_fingerprint
from .epistemic import EpistemicClass
from .governance import (
    GovernancePolicy,
    GovernanceReceipt,
    PrincipalAuthority,
    ToolAdmissionReceipt,
    ToolAuthorityClass,
)
from .obligations import ObligationStatus
from .orchestration import OrchestrationState, Strategy
from .runtime import (
    MAX_RUNTIME_EXECUTIONS,
    MAX_RUNTIME_HISTORY,
    MAX_RUNTIME_REQUESTS,
    MAX_RUNTIME_RETRIES,
    RuntimeLeaseApplicationReceipt,
    RuntimeReceipt,
    RuntimeSnapshot,
    RuntimeTransition,
    RustRuntimeSession,
)

CONTINUATION_PROTOCOL_VERSION: Final = "IBAE-CONTINUATION-LEASE-V1"
CONTINUATION_POLICY_RECEIPT_VERSION: Final = (
    "IBAE-CONTINUATION-POLICY-RECEIPT-V1"
)
PROGRESS_PROTOCOL_VERSION: Final = "IBAE-OBJECTIVE-PROGRESS-V1"
STRATEGY_CHANGE_PROTOCOL_VERSION: Final = "IBAE-STRATEGY-CHANGE-V1"
CYCLE_EVIDENCE_PROTOCOL_VERSION: Final = "IBAE-CYCLE-EVIDENCE-V1"
LEASE_GRANT_RECEIPT_VERSION: Final = "IBAE-CONTINUATION-LEASE-GRANT-V1"
LEASE_DENY_RECEIPT_VERSION: Final = "IBAE-CONTINUATION-LEASE-DENY-V1"
CHECKPOINT_PROTOCOL_VERSION: Final = "IBAE-CONTINUATION-CHECKPOINT-V1"
CONTINUATION_EVIDENCE_VERSION: Final = "IBAE-CONTINUATION-EVIDENCE-V1"
PARTIAL_CONTINUATION_VERSION: Final = "IBAE-CONTINUATION-PARTIAL-V1"
WATCHDOG_OBSERVATION_VERSION: Final = "IBAE-WATCHDOG-OBSERVATION-V1"

CONTINUATION_POLICY_ID_DOMAIN: Final = "ibae.continuation-policy-id.v1"
CONTINUATION_POLICY_RECEIPT_ID_DOMAIN: Final = (
    "ibae.continuation-policy-receipt-id.v1"
)
PROGRESS_CONTRACT_ID_DOMAIN: Final = "ibae.progress-contract-id.v1"
PROGRESS_EVIDENCE_ID_DOMAIN: Final = "ibae.progress-evidence-id.v1"
PROGRESS_RECORD_ID_DOMAIN: Final = "ibae.progress-record-id.v1"
PROGRESS_EXTERNAL_ENDPOINT_ID_DOMAIN: Final = (
    "ibae.progress-external-endpoint-id.v1"
)
OBLIGATION_DEFINITION_ID_DOMAIN: Final = "ibae.obligation-definition-set-id.v1"
STRATEGY_MATERIAL_ID_DOMAIN: Final = "ibae.strategy-material-id.v1"
STRATEGY_CHANGE_ID_DOMAIN: Final = "ibae.strategy-change-id.v1"
CYCLE_EVIDENCE_ID_DOMAIN: Final = "ibae.cycle-evidence-id.v1"
CONTINUATION_STATE_ID_DOMAIN: Final = "ibae.continuation-state-id.v1"
CONTINUATION_REQUEST_ID_DOMAIN: Final = "ibae.continuation-request-id.v1"
LEASE_GRANT_ID_DOMAIN: Final = "ibae.continuation-lease-grant-id.v1"
LEASE_GRANT_RECEIPT_ID_DOMAIN: Final = (
    "ibae.continuation-lease-grant-receipt-id.v1"
)
LEASE_DENIAL_ID_DOMAIN: Final = "ibae.continuation-lease-denial-id.v1"
LEASE_DENY_RECEIPT_ID_DOMAIN: Final = (
    "ibae.continuation-lease-deny-receipt-id.v1"
)
CONTINUATION_DECISION_AGGREGATE_DOMAIN: Final = (
    "ibae.continuation-decision-aggregate.v1"
)
CHECKPOINT_ID_DOMAIN: Final = "ibae.continuation-checkpoint-id.v1"
CONTINUATION_EVIDENCE_PROGRESS_AGGREGATE_DOMAIN: Final = (
    "ibae.continuation-progress-aggregate.v1"
)
CONTINUATION_EVIDENCE_RECEIPT_DOMAIN: Final = (
    "ibae.continuation-evidence-receipt-id.v1"
)
PARTIAL_CONTINUATION_ID_DOMAIN: Final = "ibae.continuation-partial-id.v1"
WATCHDOG_OBSERVATION_ID_DOMAIN: Final = "ibae.watchdog-observation-id.v1"

MAX_U64: Final = (1 << 64) - 1
MAX_LEASES: Final = 64
MAX_LEASE_REQUESTS: Final = 128
MAX_PROGRESS_DIMENSIONS: Final = 64
MAX_STRATEGY_FRONTIER: Final = 128
MAX_STRATEGY_TARGETS: Final = 128
MAX_DEPENDENCY_PATH: Final = 128
MAX_TRANSITION_PATTERN: Final = 12
MIN_CYCLE_HISTORY: Final = 6
MAX_CONTINUATION_EVIDENCE_BYTES: Final = 4_096


def _u64(name: str, value: Any) -> int:
    if type(value) is not int or value < 0 or value > MAX_U64:
        raise ValueError(f"{name} must be an exact unsigned 64-bit integer")
    return value


def _bool(name: str, value: Any) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{name} must be an exact boolean")
    return value


def _enum(name: str, value: Any, enum_type: type[Enum]) -> Enum:
    if not isinstance(value, enum_type):
        raise TypeError(f"{name} must be a {enum_type.__name__}")
    return value


def _fingerprints(
    name: str,
    values: Iterable[str],
    *,
    limit: int,
    sort: bool = True,
    unique: bool = True,
) -> tuple[str, ...]:
    active = materialize_bounded_iterable(name, values, limit=limit)
    for value in active:
        require_fingerprint(name, value)
    if unique and len(active) != len(set(active)):
        raise ValueError(f"{name} must be unique")
    return tuple(sorted(active)) if sort else active


def _symbols(
    name: str,
    values: Iterable[str],
    *,
    limit: int,
    sort: bool = True,
    unique: bool = True,
) -> tuple[str, ...]:
    active = materialize_bounded_iterable(name, values, limit=limit)
    for value in active:
        require_symbol(name, value)
    if unique and len(active) != len(set(active)):
        raise ValueError(f"{name} must be unique")
    return tuple(sorted(active)) if sort else active


def _with_receipt_id(domain: str, body: Mapping[str, Any]) -> dict[str, Any]:
    record = dict(body)
    record["receipt_id"] = domain_fingerprint(domain, body)
    return record


class ProgressClassification(str, Enum):
    MEASURABLE_PROGRESS = "measurable_progress"
    NO_PROGRESS = "no_progress"
    REGRESSION = "regression"
    NEW_INFORMATION = "new_information"
    INCOMPARABLE = "incomparable"


class ProgressState(str, Enum):
    PROGRESSING = "progressing"
    STALLED = "stalled"
    STRATEGY_CHANGED = "strategy_changed"
    STRATEGY_CHANGE_REJECTED = "strategy_change_rejected"
    CYCLE_BLOCKED = "cycle_blocked"
    LEASE_EXHAUSTED = "lease_exhausted"
    COMPLETE = "complete"


class ProgressDirection(str, Enum):
    DECREASE = "decrease"
    INCREASE = "increase"


class ProgressSource(str, Enum):
    UNSATISFIED_OBLIGATION_COUNT = "unsatisfied_obligation_count"
    BLOCKED_OBLIGATION_COUNT = "blocked_obligation_count"
    SATISFIED_OBLIGATION_COUNT = "satisfied_obligation_count"
    GOVERNED_EXTERNAL_COUNTER = "governed_external_counter"


class StrategyChangeStatus(str, Enum):
    ADMITTED = "admitted"
    REJECTED = "rejected"


class StrategyChangeReason(str, Enum):
    ADMITTED_MATERIAL_CHANGE = "IBAE-STRATEGY-ADMIT-MATERIAL-CHANGE"
    SAME_STRATEGY_IDENTITY = "IBAE-STRATEGY-REJECT-SAME-IDENTITY"
    NOT_MATERIAL = "IBAE-STRATEGY-REJECT-NOT-MATERIAL"
    INVALID_ACTIVE_SCHEMA = "IBAE-STRATEGY-REJECT-INVALID-ACTIVE-SCHEMA"
    UNKNOWN_CAPABILITY = "IBAE-STRATEGY-REJECT-UNKNOWN-CAPABILITY"
    UNKNOWN_TARGET_OBLIGATION = "IBAE-STRATEGY-REJECT-UNKNOWN-TARGET"
    CYCLE_EQUIVALENT = "IBAE-STRATEGY-REJECT-CYCLE-EQUIVALENT"


class ContinuationRequester(str, Enum):
    OPENAI_SUPERVISOR = "openai_supervisor"
    LOCAL_CANDIDATE_WORKER = "local_candidate_worker"
    DETERMINISTIC_ORCHESTRATOR = "deterministic_orchestrator"
    RUST_EXECUTION_RUNTIME = "rust_execution_runtime"
    TOOL_BACKEND = "tool_backend"

    @classmethod
    def normalize(
        cls, value: ContinuationRequester | PrincipalAuthority
    ) -> ContinuationRequester:
        if isinstance(value, cls):
            return value
        if isinstance(value, PrincipalAuthority):
            return cls(value.value)
        raise TypeError("requester must be a closed continuation principal")


class LeaseDenialReason(str, Enum):
    UNAUTHORIZED_REQUESTER = "IBAE-LEASE-DENY-UNAUTHORIZED-REQUESTER"
    STALE_CONTINUATION_STATE = "IBAE-LEASE-DENY-STALE-CONTINUATION-STATE"
    STALE_GOVERNANCE = "IBAE-LEASE-DENY-STALE-GOVERNANCE"
    STALE_ORCHESTRATION_STATE = "IBAE-LEASE-DENY-STALE-ORCHESTRATION-STATE"
    STALE_RUNTIME_STATE = "IBAE-LEASE-DENY-STALE-RUNTIME-STATE"
    STALE_PROGRESS = "IBAE-LEASE-DENY-STALE-PROGRESS"
    LEASE_INDEX_MISMATCH = "IBAE-LEASE-DENY-LEASE-INDEX-MISMATCH"
    NO_MEASURABLE_PROGRESS = "IBAE-LEASE-DENY-NO-MEASURABLE-PROGRESS"
    TERMINAL_CYCLE = "IBAE-LEASE-DENY-TERMINAL-CYCLE"
    LEASE_CEILING_REACHED = "IBAE-LEASE-DENY-LEASE-CEILING-REACHED"
    LEASE_REQUEST_LIMIT = "IBAE-LEASE-DENY-LEASE-REQUEST-LIMIT"
    STRATEGY_CHANGE_NOT_MATERIAL = (
        "IBAE-LEASE-DENY-STRATEGY-CHANGE-NOT-MATERIAL"
    )
    STRATEGY_CHANGE_CYCLE_EQUIVALENT = (
        "IBAE-LEASE-DENY-STRATEGY-CHANGE-CYCLE-EQUIVALENT"
    )
    STRATEGY_RECOVERY_EXHAUSTED = (
        "IBAE-LEASE-DENY-STRATEGY-RECOVERY-EXHAUSTED"
    )
    TASK_ALREADY_COMPLETE = "IBAE-LEASE-DENY-TASK-ALREADY-COMPLETE"
    BLOCKING_GOVERNANCE_VIOLATION = (
        "IBAE-LEASE-DENY-BLOCKING-GOVERNANCE-VIOLATION"
    )
    AMOUNT_EXCEEDS_SCHEDULE = "IBAE-LEASE-DENY-AMOUNT-EXCEEDS-SCHEDULE"
    AMOUNT_EXCEEDS_CEILING = "IBAE-LEASE-DENY-AMOUNT-EXCEEDS-CEILING"
    EMPTY_RESOURCE_VECTOR = "IBAE-LEASE-DENY-EMPTY-RESOURCE-VECTOR"
    UNSUPPORTED_RESOURCE = "IBAE-LEASE-DENY-UNSUPPORTED-RESOURCE"
    PENDING_LEASE_APPLICATION = "IBAE-LEASE-DENY-PENDING-LEASE-APPLICATION"


class ContinuationPartialReason(str, Enum):
    LEASE_CEILING_EXHAUSTED = "lease_ceiling_exhausted"
    NO_PROGRESS = "no_progress"
    TERMINAL_CYCLE = "terminal_cycle"
    STRATEGY_RECOVERY_EXHAUSTED = "strategy_recovery_exhausted"
    WATCHDOG_EXPIRED = "watchdog_expired"


@dataclass(frozen=True, slots=True)
class BudgetVector:
    """Exact independent continuation resources.

    Mutation is represented so the contract cannot silently omit the class,
    but v0.5 policies require it to remain zero because mutation execution is
    outside this phase.
    """

    request_delta: int = 0
    execution_delta: int = 0
    retry_delta: int = 0
    mutation_delta: int = 0
    history_delta: int = 0

    def __post_init__(self) -> None:
        for name, value in self.canonical_record().items():
            _u64(name, value)

    @classmethod
    def zero(cls) -> BudgetVector:
        return cls()

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> BudgetVector:
        fields = {
            "execution_delta",
            "history_delta",
            "mutation_delta",
            "request_delta",
            "retry_delta",
        }
        if type(value) is not dict or set(value) != fields:
            raise ValueError("budget vector does not match the v1 schema")
        return cls(**{field: value[field] for field in sorted(fields)})

    @property
    def is_zero(self) -> bool:
        return all(value == 0 for value in self.canonical_record().values())

    def add_checked(self, other: BudgetVector) -> BudgetVector:
        if type(other) is not BudgetVector:
            raise TypeError("budget vector arithmetic requires exact BudgetVector")
        values: dict[str, int] = {}
        for name, left in self.canonical_record().items():
            total = left + other.canonical_record()[name]
            if total > MAX_U64:
                raise OverflowError("continuation budget arithmetic overflow")
            values[name] = total
        return BudgetVector(**values)

    def subtract_checked(self, other: BudgetVector) -> BudgetVector:
        if type(other) is not BudgetVector:
            raise TypeError("budget vector arithmetic requires exact BudgetVector")
        values: dict[str, int] = {}
        for name, left in self.canonical_record().items():
            right = other.canonical_record()[name]
            if right > left:
                raise OverflowError("continuation budget arithmetic underflow")
            values[name] = left - right
        return BudgetVector(**values)

    def is_within(self, ceiling: BudgetVector) -> bool:
        if type(ceiling) is not BudgetVector:
            raise TypeError("budget ceiling must be an exact BudgetVector")
        return all(
            value <= ceiling.canonical_record()[name]
            for name, value in self.canonical_record().items()
        )

    def canonical_record(self) -> dict[str, int]:
        return {
            "execution_delta": self.execution_delta,
            "history_delta": self.history_delta,
            "mutation_delta": self.mutation_delta,
            "request_delta": self.request_delta,
            "retry_delta": self.retry_delta,
        }


@dataclass(frozen=True, slots=True)
class ContinuationPolicy:
    policy_key: str
    policy_version: int
    task_profile: str
    task_profile_version: int
    initial_budget: BudgetVector
    lease_schedule: tuple[BudgetVector, ...]
    total_ceiling: BudgetVector
    max_lease_requests: int
    progress_contract_id: str
    admitted_progress: tuple[ProgressClassification, ...] = (
        ProgressClassification.MEASURABLE_PROGRESS,
    )
    max_strategy_recoveries: int = 1

    def __post_init__(self) -> None:
        require_symbol("continuation policy key", self.policy_key)
        require_positive_int("continuation policy version", self.policy_version)
        require_symbol("continuation task profile", self.task_profile)
        require_positive_int(
            "continuation task profile version", self.task_profile_version
        )
        if type(self.initial_budget) is not BudgetVector:
            raise TypeError("initial_budget must be an exact BudgetVector")
        if type(self.total_ceiling) is not BudgetVector:
            raise TypeError("total_ceiling must be an exact BudgetVector")
        schedule = materialize_bounded_iterable(
            "continuation lease schedule", self.lease_schedule, limit=MAX_LEASES
        )
        if any(type(item) is not BudgetVector for item in schedule):
            raise TypeError("lease_schedule must contain exact BudgetVector records")
        if any(item.is_zero for item in schedule):
            raise ValueError("each scheduled continuation lease must be non-empty")
        object.__setattr__(self, "lease_schedule", schedule)

        _u64("max_lease_requests", self.max_lease_requests)
        if self.max_lease_requests == 0 or self.max_lease_requests > MAX_LEASE_REQUESTS:
            raise ValueError("max_lease_requests is outside the v1 hard bound")
        if self.max_lease_requests <= len(schedule):
            raise ValueError(
                "max_lease_requests must reserve one terminal decision beyond leases"
            )
        require_fingerprint(
            "continuation progress contract id", self.progress_contract_id
        )
        _u64("max_strategy_recoveries", self.max_strategy_recoveries)
        if self.max_strategy_recoveries > len(schedule):
            raise ValueError("strategy recoveries cannot exceed scheduled leases")

        admitted = materialize_bounded_iterable(
            "admitted progress classifications",
            self.admitted_progress,
            limit=len(ProgressClassification),
        )
        if not admitted:
            raise ValueError("at least one progress classification must be admitted")
        if any(not isinstance(item, ProgressClassification) for item in admitted):
            raise TypeError("admitted_progress contains an unknown classification")
        admitted = tuple(sorted(set(admitted), key=lambda item: item.value))
        if admitted != (ProgressClassification.MEASURABLE_PROGRESS,):
            raise ValueError(
                "only measurable_progress may independently justify continuation"
            )
        object.__setattr__(self, "admitted_progress", admitted)
        self._validate_authority_fields()

        if self.initial_budget.mutation_delta != 0:
            raise ValueError("v0.5 does not support mutation budget")
        cumulative = self.initial_budget
        for item in schedule:
            if item.mutation_delta != 0:
                raise ValueError("v0.5 lease schedules cannot extend mutations")
            cumulative = cumulative.add_checked(item)
        if cumulative != self.total_ceiling:
            raise ValueError(
                "total_ceiling must exactly equal base budget plus the full schedule"
            )
        self._validate_runtime_hard_limits()

    def _validate_authority_fields(self) -> None:
        if type(self.admitted_progress) is not tuple:
            raise TypeError("admitted_progress must remain an exact tuple")
        if self.admitted_progress != (ProgressClassification.MEASURABLE_PROGRESS,):
            raise ValueError(
                "only measurable_progress may independently justify continuation"
            )

    def _validate_runtime_hard_limits(self) -> None:
        record = self.total_ceiling.canonical_record()
        hard_limits = {
            "execution_delta": MAX_RUNTIME_EXECUTIONS,
            "history_delta": MAX_RUNTIME_HISTORY,
            "mutation_delta": 0,
            "request_delta": MAX_RUNTIME_REQUESTS,
            "retry_delta": MAX_RUNTIME_RETRIES,
        }
        for name, maximum in hard_limits.items():
            if record[name] > maximum:
                raise ValueError(f"continuation {name} exceeds runtime hard limit")
        for name in (
            "request_delta",
            "execution_delta",
            "retry_delta",
            "history_delta",
        ):
            if self.initial_budget.canonical_record()[name] == 0:
                raise ValueError(f"initial {name} must be positive")
        if self.initial_budget.history_delta < MIN_CYCLE_HISTORY:
            raise ValueError(
                "initial history must retain the six-transition cycle window"
            )

    @property
    def max_leases(self) -> int:
        return len(self.lease_schedule)

    @property
    def continuation_capacity(self) -> BudgetVector:
        return self.total_ceiling.subtract_checked(self.initial_budget)

    @property
    def continuation_policy_id(self) -> str:
        return domain_fingerprint(
            CONTINUATION_POLICY_ID_DOMAIN, self.canonical_record()
        )

    def canonical_record(self) -> dict[str, Any]:
        self._validate_authority_fields()
        return {
            "admitted_progress": [item.value for item in self.admitted_progress],
            "authority_layer": "governance",
            "initial_budget": self.initial_budget.canonical_record(),
            "lease_schedule": [item.canonical_record() for item in self.lease_schedule],
            "max_lease_requests": self.max_lease_requests,
            "max_leases": self.max_leases,
            "max_strategy_recoveries": self.max_strategy_recoveries,
            "policy_key": self.policy_key,
            "policy_version": self.policy_version,
            "progress_contract_id": self.progress_contract_id,
            "protocol_version": CONTINUATION_PROTOCOL_VERSION,
            "task_profile": self.task_profile,
            "task_profile_version": self.task_profile_version,
            "total_ceiling": self.total_ceiling.canonical_record(),
        }


@dataclass(frozen=True, slots=True, init=False)
class ContinuationPolicyReceipt:
    task_id: str
    governance_id: str
    governance_receipt_id: str
    continuation_policy_id: str
    progress_contract_id: str
    task_profile: str
    task_profile_version: int

    def __init__(
        self,
        policy: ContinuationPolicy,
        governance_policy: GovernancePolicy,
        governance_receipt: GovernanceReceipt,
    ) -> None:
        if type(policy) is not ContinuationPolicy:
            raise TypeError("policy must be an exact ContinuationPolicy")
        if type(governance_policy) is not GovernancePolicy:
            raise TypeError("governance_policy must be an exact GovernancePolicy")
        if type(governance_receipt) is not GovernanceReceipt:
            raise TypeError("governance_receipt must be an exact GovernanceReceipt")
        if governance_receipt.governance_id != governance_policy.governance_id:
            raise ValueError("governance receipt does not bind the supplied policy")
        if (
            policy.task_profile != governance_policy.task_profile
            or policy.task_profile_version != governance_policy.task_profile_version
        ):
            raise ValueError("continuation and governance task profiles must match")
        object.__setattr__(self, "task_id", governance_receipt.task_id)
        object.__setattr__(self, "governance_id", governance_policy.governance_id)
        object.__setattr__(
            self, "governance_receipt_id", governance_receipt.receipt_id
        )
        object.__setattr__(
            self, "continuation_policy_id", policy.continuation_policy_id
        )
        object.__setattr__(
            self, "progress_contract_id", policy.progress_contract_id
        )
        object.__setattr__(self, "task_profile", policy.task_profile)
        object.__setattr__(
            self, "task_profile_version", policy.task_profile_version
        )

    @property
    def receipt_id(self) -> str:
        return self.canonical_record()["receipt_id"]

    def canonical_record(self) -> dict[str, Any]:
        return _with_receipt_id(
            CONTINUATION_POLICY_RECEIPT_ID_DOMAIN,
            {
                "authority_layer": "governance",
                "continuation_policy_id": self.continuation_policy_id,
                "governance_id": self.governance_id,
                "governance_receipt_id": self.governance_receipt_id,
                "progress_contract_id": self.progress_contract_id,
                "protocol_version": CONTINUATION_POLICY_RECEIPT_VERSION,
                "status": "admitted",
                "task_id": self.task_id,
                "task_profile": self.task_profile,
                "task_profile_version": self.task_profile_version,
            },
        )


@dataclass(frozen=True, slots=True)
class ProgressDimension:
    key: str
    source: ProgressSource
    direction: ProgressDirection
    completion_threshold: int | None = None

    def __post_init__(self) -> None:
        require_symbol("progress dimension key", self.key)
        _enum("progress source", self.source, ProgressSource)
        _enum("progress direction", self.direction, ProgressDirection)
        required_direction = {
            ProgressSource.UNSATISFIED_OBLIGATION_COUNT: ProgressDirection.DECREASE,
            ProgressSource.BLOCKED_OBLIGATION_COUNT: ProgressDirection.DECREASE,
            ProgressSource.SATISFIED_OBLIGATION_COUNT: ProgressDirection.INCREASE,
        }.get(self.source)
        if required_direction is not None and self.direction is not required_direction:
            raise ValueError(
                "canonical obligation progress source has an unsafe direction"
            )
        if self.completion_threshold is not None:
            _u64("progress completion threshold", self.completion_threshold)
        if (
            self.source is not ProgressSource.GOVERNED_EXTERNAL_COUNTER
            and self.completion_threshold is None
        ):
            # Obligation completeness is independently determined, but an
            # explicit threshold keeps the progress contract auditable.
            expected = (
                0
                if self.source
                in {
                    ProgressSource.UNSATISFIED_OBLIGATION_COUNT,
                    ProgressSource.BLOCKED_OBLIGATION_COUNT,
                }
                else None
            )
            if expected is not None:
                object.__setattr__(self, "completion_threshold", expected)

    def canonical_record(self) -> dict[str, Any]:
        return {
            "completion_threshold": self.completion_threshold,
            "direction": self.direction.value,
            "key": self.key,
            "source": self.source.value,
        }


@dataclass(frozen=True, slots=True)
class ProgressMeasureContract:
    contract_key: str
    contract_version: int
    dimensions: tuple[ProgressDimension, ...]

    def __post_init__(self) -> None:
        require_symbol("progress contract key", self.contract_key)
        require_positive_int("progress contract version", self.contract_version)
        supplied = materialize_bounded_iterable(
            "progress dimensions", self.dimensions, limit=MAX_PROGRESS_DIMENSIONS
        )
        if not supplied:
            raise ValueError("progress contract requires at least one dimension")
        if any(type(item) is not ProgressDimension for item in supplied):
            raise TypeError("dimensions must contain exact ProgressDimension records")
        dimensions = tuple(sorted(supplied, key=lambda item: item.key))
        if len({item.key for item in dimensions}) != len(dimensions):
            raise ValueError("progress dimension keys must be unique")
        object.__setattr__(self, "dimensions", dimensions)

    @property
    def contract_id(self) -> str:
        return domain_fingerprint(PROGRESS_CONTRACT_ID_DOMAIN, self.canonical_record())

    def canonical_record(self) -> dict[str, Any]:
        return {
            "contract_key": self.contract_key,
            "contract_version": self.contract_version,
            "dimensions": [item.canonical_record() for item in self.dimensions],
            "protocol_version": PROGRESS_PROTOCOL_VERSION,
        }


def default_obligation_progress_contract() -> ProgressMeasureContract:
    """Return the exact built-in obligation progress contract for v0.5 presets."""

    return ProgressMeasureContract(
        "ibae.obligation-progress",
        1,
        (
            ProgressDimension(
                "blocked",
                ProgressSource.BLOCKED_OBLIGATION_COUNT,
                ProgressDirection.DECREASE,
            ),
            ProgressDimension(
                "unsatisfied",
                ProgressSource.UNSATISFIED_OBLIGATION_COUNT,
                ProgressDirection.DECREASE,
            ),
        ),
    )


@dataclass(frozen=True, slots=True, init=False)
class ProgressCounterEvidence:
    task_id: str
    governance_id: str
    dimension_key: str
    value: int
    basis_identity: str
    source_receipt_id: str
    epistemic_class: EpistemicClass
    _tool_admission: ToolAdmissionReceipt = field(repr=False, compare=False)
    _source_observation: CanonicalValue = field(repr=False, compare=False)
    _source_receipt: RuntimeReceipt = field(repr=False, compare=False)

    def __init__(
        self,
        source_transition: RuntimeTransition,
        tool_admission: ToolAdmissionReceipt,
    ) -> None:
        """Derive one counter from an exact source-bound native observation."""

        if type(source_transition) is not RuntimeTransition:
            raise TypeError("progress counter source must be an exact RuntimeTransition")
        if type(tool_admission) is not ToolAdmissionReceipt:
            raise TypeError("progress counter source requires exact tool governance")
        if type(source_transition.receipt) is not RuntimeReceipt:
            raise TypeError("progress counter source must carry a runtime receipt")
        if (
            source_transition.receipt.status != "accepted"
            or not source_transition.receipt.source_bound
        ):
            raise ValueError("progress counter source must be accepted and source-bound")
        observation = CanonicalValue.from_value(source_transition.observation)
        value = observation.to_value()
        fields = {
            "basis_identity",
            "dimension_key",
            "epistemic_class",
            "governance_id",
            "task_id",
            "value",
        }
        if type(value) is not dict or set(value) != fields:
            raise ValueError("progress counter observation does not match its schema")
        epistemic_raw = value["epistemic_class"]
        if type(epistemic_raw) is not str:
            raise TypeError("progress counter epistemic class must be a string")
        try:
            epistemic_class = EpistemicClass(epistemic_raw)
        except ValueError as exc:
            raise ValueError("progress counter epistemic class is unknown") from exc
        if epistemic_class not in {
            EpistemicClass.OBSERVED,
            EpistemicClass.DERIVED,
        }:
            raise ValueError(
                "progress evidence must be observed or deterministically derived"
            )
        require_fingerprint("progress evidence task id", value["task_id"])
        require_fingerprint(
            "progress evidence governance id", value["governance_id"]
        )
        require_symbol("progress evidence dimension key", value["dimension_key"])
        _u64("progress evidence value", value["value"])
        require_fingerprint(
            "progress evidence basis identity", value["basis_identity"]
        )
        receipt_record = source_transition.receipt.canonical_record()
        if receipt_record["observation_id"] != canonical_fingerprint(value):
            raise ValueError("runtime receipt does not bind the counter observation")
        if (
            tool_admission.task_id != value["task_id"]
            or tool_admission.governance_id != value["governance_id"]
            or not tool_admission.authority_class.is_read
            or receipt_record["admission_id"] != tool_admission.action_id
            or receipt_record["tool_name"] != tool_admission.tool_name
            or receipt_record["arguments_id"] != tool_admission.arguments_id
            or receipt_record["dependency_fingerprint"]
            != tool_admission.dependency_fingerprint
        ):
            raise ValueError("runtime counter source does not match tool governance")
        for name in (
            "task_id",
            "governance_id",
            "dimension_key",
            "value",
            "basis_identity",
        ):
            object.__setattr__(self, name, value[name])
        object.__setattr__(self, "epistemic_class", epistemic_class)
        object.__setattr__(
            self, "source_receipt_id", source_transition.receipt.receipt_id
        )
        object.__setattr__(self, "_source_observation", observation)
        object.__setattr__(self, "_source_receipt", source_transition.receipt)
        object.__setattr__(self, "_tool_admission", tool_admission)

    def _validate_source(self) -> None:
        observation = object.__getattribute__(self, "_source_observation")
        receipt = object.__getattribute__(self, "_source_receipt")
        admission = object.__getattribute__(self, "_tool_admission")
        if (
            type(observation) is not CanonicalValue
            or type(receipt) is not RuntimeReceipt
            or type(admission) is not ToolAdmissionReceipt
        ):
            raise ValueError("progress counter source provenance is not trusted")
        if receipt.status != "accepted" or not receipt.source_bound:
            raise ValueError("progress counter source provenance is not source-bound")
        value = observation.to_value()
        if receipt.canonical_record()["observation_id"] != canonical_fingerprint(value):
            raise ValueError("progress counter source observation no longer matches")
        expected = {
            "basis_identity": self.basis_identity,
            "dimension_key": self.dimension_key,
            "epistemic_class": self.epistemic_class.value,
            "governance_id": self.governance_id,
            "task_id": self.task_id,
            "value": self.value,
        }
        if value != expected or receipt.receipt_id != self.source_receipt_id:
            raise ValueError("progress counter fields do not match source provenance")
        receipt_record = receipt.canonical_record()
        if (
            admission.task_id != self.task_id
            or admission.governance_id != self.governance_id
            or not admission.authority_class.is_read
            or receipt_record["admission_id"] != admission.action_id
            or receipt_record["tool_name"] != admission.tool_name
            or receipt_record["arguments_id"] != admission.arguments_id
            or receipt_record["dependency_fingerprint"]
            != admission.dependency_fingerprint
        ):
            raise ValueError("progress counter tool governance no longer matches")

    @property
    def evidence_id(self) -> str:
        return domain_fingerprint(PROGRESS_EVIDENCE_ID_DOMAIN, self.canonical_record())

    def canonical_record(self) -> dict[str, Any]:
        self._validate_source()
        return {
            "basis_identity": self.basis_identity,
            "dimension_key": self.dimension_key,
            "epistemic_class": self.epistemic_class.value,
            "governance_id": self.governance_id,
            "source_receipt_id": self.source_receipt_id,
            "task_id": self.task_id,
            "value": self.value,
        }


@dataclass(frozen=True, slots=True)
class ProgressMeasure:
    dimension_key: str
    value: int | None
    basis_identity: str | None
    evidence_id: str | None

    def __post_init__(self) -> None:
        require_symbol("progress measure dimension key", self.dimension_key)
        if self.value is None:
            if self.basis_identity is not None or self.evidence_id is not None:
                raise ValueError("unknown progress measures cannot carry evidence")
        else:
            _u64("progress measure value", self.value)
            if self.basis_identity is None or self.evidence_id is None:
                raise ValueError("known progress measures require exact evidence")
            require_fingerprint("progress measure basis identity", self.basis_identity)
            require_fingerprint("progress measure evidence id", self.evidence_id)

    def canonical_record(self) -> dict[str, Any]:
        return {
            "basis_identity": self.basis_identity,
            "dimension_key": self.dimension_key,
            "evidence_id": self.evidence_id,
            "value": self.value,
        }


def _derive_progress_classification(
    contract: ProgressMeasureContract,
    prior_measures: tuple[ProgressMeasure, ...],
    current_measures: tuple[ProgressMeasure, ...],
) -> ProgressClassification:
    improvements = 0
    regressions = 0
    new_information = False
    for dimension, prior, current in zip(
        contract.dimensions, prior_measures, current_measures, strict=True
    ):
        if (
            prior.value is None
            or current.value is None
            or prior.basis_identity != current.basis_identity
        ):
            if prior.canonical_record() != current.canonical_record():
                new_information = True
            continue
        if prior.value == current.value:
            continue
        improved = (
            current.value < prior.value
            if dimension.direction is ProgressDirection.DECREASE
            else current.value > prior.value
        )
        if improved:
            improvements += 1
        else:
            regressions += 1
    if new_information:
        return ProgressClassification.NEW_INFORMATION
    if improvements and regressions:
        return ProgressClassification.INCOMPARABLE
    if improvements:
        return ProgressClassification.MEASURABLE_PROGRESS
    if regressions:
        return ProgressClassification.REGRESSION
    return ProgressClassification.NO_PROGRESS


def _derive_task_complete(
    contract: ProgressMeasureContract,
    current_measures: tuple[ProgressMeasure, ...],
    current_state: OrchestrationState,
) -> bool:
    if not all(
        item.status is ObligationStatus.SATISFIED
        for item in current_state.obligations.obligations
    ):
        return False
    current_by_key = {item.dimension_key: item for item in current_measures}
    for dimension in contract.dimensions:
        threshold = dimension.completion_threshold
        if threshold is None:
            continue
        measure = current_by_key[dimension.key]
        if measure.value is None:
            return False
        if dimension.direction is ProgressDirection.DECREASE:
            if measure.value > threshold:
                return False
        elif measure.value < threshold:
            return False
    return True


@dataclass(frozen=True, slots=True)
class ProgressRecord:
    task_id: str
    governance_id: str
    contract: ProgressMeasureContract
    prior_orchestration_state_id: str
    current_orchestration_state_id: str
    prior_measures: tuple[ProgressMeasure, ...]
    current_measures: tuple[ProgressMeasure, ...]
    classification: ProgressClassification
    task_complete: bool
    _prior_state: OrchestrationState = field(repr=False, compare=False)
    _current_state: OrchestrationState = field(repr=False, compare=False)
    _prior_external_evidence: tuple[ProgressCounterEvidence, ...] = field(
        repr=False, compare=False
    )
    _current_external_evidence: tuple[ProgressCounterEvidence, ...] = field(
        repr=False, compare=False
    )

    def __post_init__(self) -> None:
        require_fingerprint("progress task id", self.task_id)
        require_fingerprint("progress governance id", self.governance_id)
        if type(self.contract) is not ProgressMeasureContract:
            raise TypeError("contract must be an exact ProgressMeasureContract")
        require_fingerprint(
            "prior orchestration state id", self.prior_orchestration_state_id
        )
        require_fingerprint(
            "current orchestration state id", self.current_orchestration_state_id
        )
        _enum("progress classification", self.classification, ProgressClassification)
        _bool("task_complete", self.task_complete)
        expected = tuple(item.key for item in self.contract.dimensions)
        for name, values in (
            ("prior measures", self.prior_measures),
            ("current measures", self.current_measures),
        ):
            active = materialize_bounded_iterable(
                name, values, limit=MAX_PROGRESS_DIMENSIONS
            )
            if any(type(item) is not ProgressMeasure for item in active):
                raise TypeError(f"{name} must contain exact ProgressMeasure records")
            if tuple(item.dimension_key for item in active) != expected:
                raise ValueError(f"{name} do not match the declared dimensions")
            object.__setattr__(self, name.replace(" ", "_"), active)
        for name, attribute, values in (
            (
                "prior external evidence",
                "_prior_external_evidence",
                self._prior_external_evidence,
            ),
            (
                "current external evidence",
                "_current_external_evidence",
                self._current_external_evidence,
            ),
        ):
            active = materialize_bounded_iterable(
                name, values, limit=MAX_PROGRESS_DIMENSIONS
            )
            if any(type(item) is not ProgressCounterEvidence for item in active):
                raise TypeError(f"{name} must contain exact counter evidence")
            active = tuple(sorted(active, key=lambda item: item.dimension_key))
            if len({item.dimension_key for item in active}) != len(active):
                raise ValueError(f"{name} contains duplicate dimensions")
            object.__setattr__(self, attribute, active)
        self._validate_bound_claims()

    def _validate_bound_claims(self) -> None:
        if type(self._prior_state) is not OrchestrationState or type(
            self._current_state
        ) is not OrchestrationState:
            raise TypeError("progress records require exact bound orchestration states")
        if (
            self._prior_state.state_id != self.prior_orchestration_state_id
            or self._current_state.state_id != self.current_orchestration_state_id
        ):
            raise ValueError("progress state objects do not match their declared identities")

        evidence_maps: list[dict[str, ProgressCounterEvidence]] = []
        for name, values in (
            ("prior external evidence", self._prior_external_evidence),
            ("current external evidence", self._current_external_evidence),
        ):
            if type(values) is not tuple or any(
                type(item) is not ProgressCounterEvidence for item in values
            ):
                raise TypeError(f"{name} must contain exact counter evidence")
            if tuple(sorted(values, key=lambda item: item.dimension_key)) != values:
                raise ValueError(f"{name} is not canonically ordered")
            if len({item.dimension_key for item in values}) != len(values):
                raise ValueError(f"{name} contains duplicate dimensions")
            evidence_maps.append({item.dimension_key: item for item in values})
        external_keys = {
            item.key
            for item in self.contract.dimensions
            if item.source is ProgressSource.GOVERNED_EXTERNAL_COUNTER
        }
        if any(set(mapping) - external_keys for mapping in evidence_maps):
            raise ValueError("progress record carries undeclared external evidence")

        for index, dimension in enumerate(self.contract.dimensions):
            if dimension.source is ProgressSource.GOVERNED_EXTERNAL_COUNTER:
                expected_prior = _external_measure(
                    dimension,
                    evidence_maps[0],
                    task_id=self.task_id,
                    governance_id=self.governance_id,
                )
                expected_current = _external_measure(
                    dimension,
                    evidence_maps[1],
                    task_id=self.task_id,
                    governance_id=self.governance_id,
                )
            else:
                expected_prior = _state_measure(dimension, self._prior_state)
                expected_current = _state_measure(dimension, self._current_state)
            if (
                self.prior_measures[index] != expected_prior
                or self.current_measures[index] != expected_current
            ):
                raise ValueError("progress measures do not match their bound sources")

        derived_classification = _derive_progress_classification(
            self.contract, self.prior_measures, self.current_measures
        )
        if self.classification is not derived_classification:
            raise ValueError("progress classification does not match bound measures")
        derived_complete = _derive_task_complete(
            self.contract, self.current_measures, self._current_state
        )
        if self.task_complete is not derived_complete:
            raise ValueError("task completion does not match bound measures and state")

    @property
    def progress_id(self) -> str:
        return domain_fingerprint(PROGRESS_RECORD_ID_DOMAIN, self.canonical_record())

    def _external_endpoint_id(self, *, prior: bool) -> str | None:
        measures = self.prior_measures if prior else self.current_measures
        endpoint = [
            {
                "basis_identity": measure.basis_identity,
                "dimension_key": measure.dimension_key,
                "value": measure.value,
            }
            for dimension, measure in zip(
                self.contract.dimensions, measures, strict=True
            )
            if dimension.source is ProgressSource.GOVERNED_EXTERNAL_COUNTER
        ]
        if not endpoint:
            return None
        return domain_fingerprint(
            PROGRESS_EXTERNAL_ENDPOINT_ID_DOMAIN,
            {
                "measure_contract_id": self.contract.contract_id,
                "measures": endpoint,
            },
        )

    @property
    def prior_external_endpoint_id(self) -> str | None:
        return self._external_endpoint_id(prior=True)

    @property
    def current_external_endpoint_id(self) -> str | None:
        return self._external_endpoint_id(prior=False)

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    item.evidence_id
                    for item in (*self.prior_measures, *self.current_measures)
                    if item.evidence_id is not None
                }
            )
        )

    def canonical_record(self) -> dict[str, Any]:
        self._validate_bound_claims()
        return {
            "classification": self.classification.value,
            "current_measures": [item.canonical_record() for item in self.current_measures],
            "current_orchestration_state_id": self.current_orchestration_state_id,
            "evidence_ids": list(self.evidence_ids),
            "governance_id": self.governance_id,
            "measure_contract": self.contract.canonical_record(),
            "measure_contract_id": self.contract.contract_id,
            "prior_measures": [item.canonical_record() for item in self.prior_measures],
            "prior_orchestration_state_id": self.prior_orchestration_state_id,
            "protocol_version": PROGRESS_PROTOCOL_VERSION,
            "task_complete": self.task_complete,
            "task_id": self.task_id,
        }


def _obligation_definition_identity(state: OrchestrationState) -> str:
    return domain_fingerprint(
        OBLIGATION_DEFINITION_ID_DOMAIN,
        {
            "obligations": [
                {
                    "dependencies": list(item.dependency_ids),
                    "description": item.description,
                    "key": item.key,
                    "obligation_id": item.obligation_id,
                }
                for item in state.obligations.obligations
            ]
        },
    )


def _state_measure(
    dimension: ProgressDimension, state: OrchestrationState
) -> ProgressMeasure:
    counts = {
        ProgressSource.UNSATISFIED_OBLIGATION_COUNT: sum(
            item.status is ObligationStatus.UNSATISFIED
            for item in state.obligations.obligations
        ),
        ProgressSource.BLOCKED_OBLIGATION_COUNT: sum(
            item.status is ObligationStatus.BLOCKED
            for item in state.obligations.obligations
        ),
        ProgressSource.SATISFIED_OBLIGATION_COUNT: sum(
            item.status is ObligationStatus.SATISFIED
            for item in state.obligations.obligations
        ),
    }
    basis = _obligation_definition_identity(state)
    return ProgressMeasure(
        dimension_key=dimension.key,
        value=counts[dimension.source],
        basis_identity=basis,
        evidence_id=state.state_id,
    )


def _external_measure(
    dimension: ProgressDimension,
    evidence: Mapping[str, ProgressCounterEvidence],
    *,
    task_id: str,
    governance_id: str,
) -> ProgressMeasure:
    item = evidence.get(dimension.key)
    if item is None:
        return ProgressMeasure(dimension.key, None, None, None)
    if type(item) is not ProgressCounterEvidence:
        raise TypeError("external progress evidence must be exact evidence records")
    if item.dimension_key != dimension.key:
        raise ValueError("external progress evidence dimension mismatch")
    if item.task_id != task_id or item.governance_id != governance_id:
        raise ValueError("external progress evidence authority binding mismatch")
    return ProgressMeasure(
        dimension.key, item.value, item.basis_identity, item.evidence_id
    )


def evaluate_progress(
    *,
    task_id: str,
    governance_id: str,
    contract: ProgressMeasureContract,
    prior_state: OrchestrationState,
    current_state: OrchestrationState,
    prior_evidence: Mapping[str, ProgressCounterEvidence] | None = None,
    current_evidence: Mapping[str, ProgressCounterEvidence] | None = None,
) -> ProgressRecord:
    """Classify exact declared measures without scores, confidence, or activity."""

    require_fingerprint("progress task id", task_id)
    require_fingerprint("progress governance id", governance_id)
    if type(contract) is not ProgressMeasureContract:
        raise TypeError("contract must be an exact ProgressMeasureContract")
    if type(prior_state) is not OrchestrationState:
        raise TypeError("prior_state must be an exact OrchestrationState")
    if type(current_state) is not OrchestrationState:
        raise TypeError("current_state must be an exact OrchestrationState")
    prior_external = {} if prior_evidence is None else prior_evidence
    current_external = {} if current_evidence is None else current_evidence
    if not isinstance(prior_external, Mapping) or not isinstance(
        current_external, Mapping
    ):
        raise TypeError("progress evidence collections must be mappings")
    external_keys = {
        item.key
        for item in contract.dimensions
        if item.source is ProgressSource.GOVERNED_EXTERNAL_COUNTER
    }
    for evidence in (prior_external, current_external):
        if any(type(key) is not str for key in evidence):
            raise TypeError("progress evidence mapping keys must be exact strings")
        if set(evidence) - external_keys:
            raise ValueError("progress evidence contains an undeclared dimension")

    prior_measures: list[ProgressMeasure] = []
    current_measures: list[ProgressMeasure] = []
    for dimension in contract.dimensions:
        if dimension.source is ProgressSource.GOVERNED_EXTERNAL_COUNTER:
            prior = _external_measure(
                dimension,
                prior_external,
                task_id=task_id,
                governance_id=governance_id,
            )
            current = _external_measure(
                dimension,
                current_external,
                task_id=task_id,
                governance_id=governance_id,
            )
        else:
            prior = _state_measure(dimension, prior_state)
            current = _state_measure(dimension, current_state)
        prior_measures.append(prior)
        current_measures.append(current)
    prior_tuple = tuple(prior_measures)
    current_tuple = tuple(current_measures)
    classification = _derive_progress_classification(
        contract, prior_tuple, current_tuple
    )
    task_complete = _derive_task_complete(contract, current_tuple, current_state)

    return ProgressRecord(
        task_id=task_id,
        governance_id=governance_id,
        contract=contract,
        prior_orchestration_state_id=prior_state.state_id,
        current_orchestration_state_id=current_state.state_id,
        prior_measures=prior_tuple,
        current_measures=current_tuple,
        classification=classification,
        task_complete=task_complete,
        _prior_state=prior_state,
        _current_state=current_state,
        _prior_external_evidence=tuple(
            prior_external[key] for key in sorted(prior_external)
        ),
        _current_external_evidence=tuple(
            current_external[key] for key in sorted(current_external)
        ),
    )


@dataclass(frozen=True, slots=True)
class CycleEvidence:
    runtime_session_id: str
    runtime_state_id: str
    period: int
    transition_pattern: tuple[str, ...]

    def __post_init__(self) -> None:
        require_fingerprint("cycle runtime session id", self.runtime_session_id)
        require_fingerprint("cycle runtime state id", self.runtime_state_id)
        if type(self.period) is not int or self.period not in {1, 2, 3}:
            raise ValueError("cycle period must be the exact integer 1, 2, or 3")
        pattern = _fingerprints(
            "cycle transition pattern",
            self.transition_pattern,
            limit=3,
            sort=False,
            unique=False,
        )
        if len(pattern) != self.period:
            raise ValueError("cycle pattern length must equal its period")
        object.__setattr__(self, "transition_pattern", pattern)

    @classmethod
    def from_snapshot(cls, snapshot: RuntimeSnapshot) -> CycleEvidence | None:
        if not isinstance(snapshot, RuntimeSnapshot):
            raise TypeError("snapshot must be a RuntimeSnapshot")
        history = snapshot.history
        for period in (1, 2, 3):
            width = period * 2
            if len(history) < width:
                continue
            if history[-width:-period] == history[-period:]:
                return cls(
                    runtime_session_id=snapshot.session_id,
                    runtime_state_id=snapshot.state_id,
                    period=period,
                    transition_pattern=history[-period:],
                )
        return None

    @property
    def cycle_evidence_id(self) -> str:
        return domain_fingerprint(CYCLE_EVIDENCE_ID_DOMAIN, self.canonical_record())

    def canonical_record(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "protocol_version": CYCLE_EVIDENCE_PROTOCOL_VERSION,
            "runtime_session_id": self.runtime_session_id,
            "runtime_state_id": self.runtime_state_id,
            "transition_pattern": list(self.transition_pattern),
        }

    def reproduces(self, proposed_pattern: tuple[str, ...]) -> bool:
        if not proposed_pattern:
            return False
        if len(proposed_pattern) < self.period:
            return False
        return all(
            transition_id == self.transition_pattern[index % self.period]
            for index, transition_id in enumerate(proposed_pattern)
        )


@dataclass(frozen=True, slots=True, init=False)
class StrategyMaterialization:
    """Structured strategy meaning used by the material-change gate.

    ``description`` is deliberately observational.  It is validated and kept
    for local presentation, but excluded from every authoritative identity so
    paraphrasing cannot manufacture a change.
    """

    strategy: Strategy
    capability_frontier: tuple[str, ...]
    target_obligation_ids: tuple[str, ...]
    dependency_path: tuple[str, ...]
    recovery_mode: str
    initial_transition_pattern: tuple[str, ...]
    description: str

    def __init__(
        self,
        strategy: Strategy,
        *,
        capability_frontier: Iterable[str],
        target_obligation_ids: Iterable[str],
        dependency_path: Iterable[str],
        recovery_mode: str,
        initial_transition_pattern: Iterable[str] = (),
        description: str = "structured strategy",
    ) -> None:
        if type(strategy) is not Strategy:
            raise TypeError("strategy must be an exact Strategy")
        frontier = _symbols(
            "strategy capability frontier",
            capability_frontier,
            limit=MAX_STRATEGY_FRONTIER,
        )
        targets = _fingerprints(
            "strategy target obligation ids",
            target_obligation_ids,
            limit=MAX_STRATEGY_TARGETS,
        )
        if not targets:
            raise ValueError("recovery strategy requires at least one target obligation")
        dependencies = _fingerprints(
            "strategy dependency path",
            dependency_path,
            limit=MAX_DEPENDENCY_PATH,
            sort=False,
        )
        pattern = _fingerprints(
            "strategy initial transition pattern",
            initial_transition_pattern,
            limit=MAX_TRANSITION_PATTERN,
            sort=False,
            unique=False,
        )
        require_symbol("strategy recovery mode", recovery_mode)
        require_text("strategy description", description)
        object.__setattr__(self, "strategy", strategy)
        object.__setattr__(self, "capability_frontier", frontier)
        object.__setattr__(self, "target_obligation_ids", targets)
        object.__setattr__(self, "dependency_path", dependencies)
        object.__setattr__(self, "recovery_mode", recovery_mode)
        object.__setattr__(self, "initial_transition_pattern", pattern)
        object.__setattr__(self, "description", description)

    @property
    def strategy_material_id(self) -> str:
        return domain_fingerprint(
            STRATEGY_MATERIAL_ID_DOMAIN, self.identity_record()
        )

    def semantic_difference_record(self) -> dict[str, Any]:
        return {
            "capability_frontier": list(self.capability_frontier),
            "dependency_path": list(self.dependency_path),
            "initial_transition_pattern": list(self.initial_transition_pattern),
            "recovery_mode": self.recovery_mode,
            "target_obligation_ids": list(self.target_obligation_ids),
        }

    def identity_record(self) -> dict[str, Any]:
        return {
            **self.semantic_difference_record(),
            "strategy_id": self.strategy.strategy_id,
        }

    def canonical_record(self) -> dict[str, Any]:
        # Description is intentionally absent: it is neither identity-bearing
        # nor admissibility-bearing.
        return {
            **self.identity_record(),
            "strategy_material_id": self.strategy_material_id,
        }


def _derive_strategy_change_reason(
    orchestration_state: OrchestrationState,
    prior_strategy: StrategyMaterialization,
    proposed_strategy: StrategyMaterialization,
    cycle_evidence: CycleEvidence | None,
) -> StrategyChangeReason:
    active_schema = orchestration_state.strategy_schema(proposed_strategy.strategy.key)
    if (
        active_schema is None
        or active_schema.schema_id != proposed_strategy.strategy.schema.schema_id
    ):
        return StrategyChangeReason.INVALID_ACTIVE_SCHEMA
    if proposed_strategy.strategy.strategy_id == prior_strategy.strategy.strategy_id:
        return StrategyChangeReason.SAME_STRATEGY_IDENTITY
    if (
        proposed_strategy.semantic_difference_record()
        == prior_strategy.semantic_difference_record()
    ):
        return StrategyChangeReason.NOT_MATERIAL
    if any(
        orchestration_state.capability(name) is None
        or not orchestration_state.capability(name).available  # type: ignore[union-attr]
        for name in proposed_strategy.capability_frontier
    ):
        return StrategyChangeReason.UNKNOWN_CAPABILITY
    if any(
        target not in orchestration_state.obligations.known_ids
        for target in proposed_strategy.target_obligation_ids
    ):
        return StrategyChangeReason.UNKNOWN_TARGET_OBLIGATION
    if cycle_evidence is not None and cycle_evidence.reproduces(
        proposed_strategy.initial_transition_pattern
    ):
        return StrategyChangeReason.CYCLE_EQUIVALENT
    return StrategyChangeReason.ADMITTED_MATERIAL_CHANGE


@dataclass(frozen=True, slots=True)
class StrategyChangeReceipt:
    task_id: str
    governance_id: str
    orchestration_state_id: str
    prior_strategy_material_id: str
    proposed_strategy_material_id: str
    proposed_strategy_id: str
    status: StrategyChangeStatus
    reason: StrategyChangeReason
    _orchestration_state: OrchestrationState = field(repr=False, compare=False)
    _prior_strategy: StrategyMaterialization = field(repr=False, compare=False)
    _proposed_strategy: StrategyMaterialization = field(repr=False, compare=False)
    _cycle_evidence: CycleEvidence | None = field(repr=False, compare=False)
    cycle_evidence_id: str | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("strategy change task id", self.task_id),
            ("strategy change governance id", self.governance_id),
            ("strategy change orchestration state id", self.orchestration_state_id),
            ("prior strategy material id", self.prior_strategy_material_id),
            ("proposed strategy material id", self.proposed_strategy_material_id),
            ("proposed strategy id", self.proposed_strategy_id),
        ):
            require_fingerprint(name, value)
        _enum("strategy change status", self.status, StrategyChangeStatus)
        _enum("strategy change reason", self.reason, StrategyChangeReason)
        if self.cycle_evidence_id is not None:
            require_fingerprint("strategy cycle evidence id", self.cycle_evidence_id)
        admitted = self.status is StrategyChangeStatus.ADMITTED
        if admitted != (
            self.reason is StrategyChangeReason.ADMITTED_MATERIAL_CHANGE
        ):
            raise ValueError("strategy change status and reason are inconsistent")
        self._validate_bound_material()

    def _validate_bound_material(self) -> None:
        if type(self._orchestration_state) is not OrchestrationState:
            raise TypeError("strategy receipt requires exact orchestration state")
        if type(self._prior_strategy) is not StrategyMaterialization or type(
            self._proposed_strategy
        ) is not StrategyMaterialization:
            raise TypeError("strategy receipt requires exact strategy material")
        if self._cycle_evidence is not None and type(
            self._cycle_evidence
        ) is not CycleEvidence:
            raise TypeError("strategy receipt requires exact cycle evidence or None")
        expected_reason = _derive_strategy_change_reason(
            self._orchestration_state,
            self._prior_strategy,
            self._proposed_strategy,
            self._cycle_evidence,
        )
        expected_status = (
            StrategyChangeStatus.ADMITTED
            if expected_reason is StrategyChangeReason.ADMITTED_MATERIAL_CHANGE
            else StrategyChangeStatus.REJECTED
        )
        expected_cycle_id = (
            None
            if self._cycle_evidence is None
            else self._cycle_evidence.cycle_evidence_id
        )
        if (
            self.orchestration_state_id != self._orchestration_state.state_id
            or self.prior_strategy_material_id
            != self._prior_strategy.strategy_material_id
            or self.proposed_strategy_material_id
            != self._proposed_strategy.strategy_material_id
            or self.proposed_strategy_id
            != self._proposed_strategy.strategy.strategy_id
            or self.cycle_evidence_id != expected_cycle_id
            or self.reason is not expected_reason
            or self.status is not expected_status
        ):
            raise ValueError("strategy change claims do not match bound material")

    @property
    def strategy_change_id(self) -> str:
        return domain_fingerprint(STRATEGY_CHANGE_ID_DOMAIN, self.canonical_record())

    def canonical_record(self) -> dict[str, Any]:
        self._validate_bound_material()
        return {
            "authority_layer": "orchestration",
            "cycle_evidence_id": self.cycle_evidence_id,
            "governance_id": self.governance_id,
            "orchestration_state_id": self.orchestration_state_id,
            "prior_strategy_material_id": self.prior_strategy_material_id,
            "proposed_strategy_id": self.proposed_strategy_id,
            "proposed_strategy_material_id": self.proposed_strategy_material_id,
            "protocol_version": STRATEGY_CHANGE_PROTOCOL_VERSION,
            "reason": self.reason.value,
            "status": self.status.value,
            "task_id": self.task_id,
        }


def evaluate_strategy_change(
    *,
    task_id: str,
    governance_id: str,
    orchestration_state: OrchestrationState,
    prior_strategy: StrategyMaterialization,
    proposed_strategy: StrategyMaterialization,
    cycle_evidence: CycleEvidence | None = None,
) -> StrategyChangeReceipt:
    require_fingerprint("strategy task id", task_id)
    require_fingerprint("strategy governance id", governance_id)
    if type(orchestration_state) is not OrchestrationState:
        raise TypeError("orchestration_state must be an exact OrchestrationState")
    if type(prior_strategy) is not StrategyMaterialization:
        raise TypeError("prior_strategy must be an exact StrategyMaterialization")
    if type(proposed_strategy) is not StrategyMaterialization:
        raise TypeError("proposed_strategy must be an exact StrategyMaterialization")
    if cycle_evidence is not None and type(cycle_evidence) is not CycleEvidence:
        raise TypeError("cycle_evidence must be exact CycleEvidence or None")

    reason = _derive_strategy_change_reason(
        orchestration_state, prior_strategy, proposed_strategy, cycle_evidence
    )

    status = (
        StrategyChangeStatus.ADMITTED
        if reason is StrategyChangeReason.ADMITTED_MATERIAL_CHANGE
        else StrategyChangeStatus.REJECTED
    )
    return StrategyChangeReceipt(
        task_id=task_id,
        governance_id=governance_id,
        orchestration_state_id=orchestration_state.state_id,
        prior_strategy_material_id=prior_strategy.strategy_material_id,
        proposed_strategy_material_id=proposed_strategy.strategy_material_id,
        proposed_strategy_id=proposed_strategy.strategy.strategy_id,
        status=status,
        reason=reason,
        cycle_evidence_id=(
            None if cycle_evidence is None else cycle_evidence.cycle_evidence_id
        ),
        _orchestration_state=orchestration_state,
        _prior_strategy=prior_strategy,
        _proposed_strategy=proposed_strategy,
        _cycle_evidence=cycle_evidence,
    )


def _profile_policy(
    name: str,
    base: BudgetVector,
    schedule: tuple[BudgetVector, ...],
    *,
    progress_contract: ProgressMeasureContract,
) -> ContinuationPolicy:
    ceiling = base
    for item in schedule:
        ceiling = ceiling.add_checked(item)
    return ContinuationPolicy(
        policy_key=f"experimental.{name}",
        policy_version=1,
        task_profile=name,
        task_profile_version=1,
        initial_budget=base,
        lease_schedule=schedule,
        total_ceiling=ceiling,
        max_lease_requests=max(2, len(schedule) * 2),
        progress_contract_id=progress_contract.contract_id,
        max_strategy_recoveries=min(1, len(schedule)),
    )


def experimental_continuation_profile(
    name: str,
    *,
    progress_contract: ProgressMeasureContract | None = None,
) -> ContinuationPolicy:
    """Return one exact version-1 benchmark preset.

    These values are experimental policy fixtures, not universal optimal
    execution limits.
    """

    require_symbol("continuation profile name", name)
    active_contract = (
        default_obligation_progress_contract()
        if progress_contract is None
        else progress_contract
    )
    if type(active_contract) is not ProgressMeasureContract:
        raise TypeError("progress_contract must be an exact ProgressMeasureContract")
    profiles = {
        "tiny": (
            BudgetVector(8, 4, 2, 0, 8),
            (BudgetVector(4, 2, 1, 0, 4),),
        ),
        "standard": (
            BudgetVector(32, 16, 4, 0, 32),
            (
                BudgetVector(16, 8, 2, 0, 16),
                BudgetVector(8, 4, 1, 0, 8),
            ),
        ),
        "extended": (
            BudgetVector(64, 32, 8, 0, 64),
            (
                BudgetVector(32, 16, 4, 0, 32),
                BudgetVector(16, 8, 2, 0, 16),
                BudgetVector(8, 4, 1, 0, 8),
            ),
        ),
        "repository": (
            BudgetVector(128, 64, 16, 0, 128),
            (
                BudgetVector(64, 32, 8, 0, 64),
                BudgetVector(32, 16, 4, 0, 32),
                BudgetVector(16, 8, 2, 0, 16),
            ),
        ),
    }
    try:
        base, schedule = profiles[name]
    except KeyError as exc:
        raise ValueError("unknown experimental continuation profile") from exc
    return _profile_policy(
        name,
        base,
        schedule,
        progress_contract=active_contract,
    )


def _initial_decision_aggregate(
    *, task_id: str, governance_id: str, continuation_policy_id: str
) -> str:
    return domain_fingerprint(
        CONTINUATION_DECISION_AGGREGATE_DOMAIN,
        {
            "continuation_policy_id": continuation_policy_id,
            "governance_id": governance_id,
            "item_type": "seed",
            "task_id": task_id,
        },
    )


def _advance_decision_aggregate(
    prior: str, receipt_id: str, ordinal: int
) -> str:
    require_fingerprint("prior continuation decision aggregate", prior)
    require_fingerprint("continuation decision receipt id", receipt_id)
    _u64("continuation decision ordinal", ordinal)
    return domain_fingerprint(
        CONTINUATION_DECISION_AGGREGATE_DOMAIN,
        {
            "item_type": "decision",
            "ordinal": ordinal,
            "prior": prior,
            "receipt_id": receipt_id,
        },
    )


@dataclass(frozen=True, slots=True)
class ContinuationState:
    task_id: str
    governance_id: str
    governance_receipt_id: str
    continuation_policy_id: str
    continuation_policy_receipt_id: str
    progress_contract_id: str
    orchestration_state_id: str
    runtime_session_id: str
    runtime_state_id: str
    lease_requests: int
    leases_granted: int
    leases_denied: int
    cumulative_granted: BudgetVector
    continuation_logical_tick: int
    decision_aggregate_id: str
    decision_receipt_ids: tuple[str, ...]
    strategy_recoveries: int
    current_strategy_material_id: str | None
    last_progress_id: str | None
    progress_event_count: int
    progress_aggregate_id: str
    last_consumed_progress_id: str | None
    last_external_progress_endpoint_id: str | None
    last_consumed_external_progress_endpoint_id: str | None
    last_progress_classification: ProgressClassification | None
    last_decision: str
    last_denial_reason: LeaseDenialReason | None
    progress_state: ProgressState
    pending_grant_id: str | None = None
    pending_grant_receipt_id: str | None = None
    _decision_lineage_capability: Any | None = field(
        default=None, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        for name, value in (
            ("continuation task id", self.task_id),
            ("continuation governance id", self.governance_id),
            ("continuation governance receipt id", self.governance_receipt_id),
            ("continuation policy id", self.continuation_policy_id),
            (
                "continuation policy receipt id",
                self.continuation_policy_receipt_id,
            ),
            ("continuation progress contract id", self.progress_contract_id),
            ("continuation orchestration state id", self.orchestration_state_id),
            ("continuation runtime session id", self.runtime_session_id),
            ("continuation runtime state id", self.runtime_state_id),
            ("continuation decision aggregate id", self.decision_aggregate_id),
        ):
            require_fingerprint(name, value)
        for name, value in (
            ("lease_requests", self.lease_requests),
            ("leases_granted", self.leases_granted),
            ("leases_denied", self.leases_denied),
            ("continuation_logical_tick", self.continuation_logical_tick),
            ("strategy_recoveries", self.strategy_recoveries),
            ("progress_event_count", self.progress_event_count),
        ):
            _u64(name, value)
        if self.lease_requests != self.leases_granted + self.leases_denied:
            raise ValueError("continuation lease request accounting is inconsistent")
        if self.continuation_logical_tick != self.lease_requests:
            raise ValueError("each recorded lease decision must consume one tick")
        if type(self.cumulative_granted) is not BudgetVector:
            raise TypeError("cumulative_granted must be an exact BudgetVector")
        receipts = _fingerprints(
            "continuation decision receipt ids",
            self.decision_receipt_ids,
            limit=MAX_LEASE_REQUESTS,
            sort=False,
        )
        if len(receipts) != self.lease_requests:
            raise ValueError("decision receipt history does not match request count")
        object.__setattr__(self, "decision_receipt_ids", receipts)
        if self.current_strategy_material_id is not None:
            require_fingerprint(
                "current strategy material id", self.current_strategy_material_id
            )
        if self.last_progress_id is not None:
            require_fingerprint("last progress id", self.last_progress_id)
        require_fingerprint(
            "continuation progress aggregate id", self.progress_aggregate_id
        )
        if (self.progress_event_count == 0) != (self.last_progress_id is None):
            raise ValueError(
                "continuation progress count must match the live progress endpoint"
            )
        if self.last_consumed_progress_id is not None:
            require_fingerprint(
                "last consumed progress id", self.last_consumed_progress_id
            )
        if self.last_external_progress_endpoint_id is not None:
            require_fingerprint(
                "last external progress endpoint id",
                self.last_external_progress_endpoint_id,
            )
        if self.last_consumed_external_progress_endpoint_id is not None:
            require_fingerprint(
                "last consumed external progress endpoint id",
                self.last_consumed_external_progress_endpoint_id,
            )
        if self.last_progress_classification is not None:
            _enum(
                "last progress classification",
                self.last_progress_classification,
                ProgressClassification,
            )
        if self.last_decision not in {"none", "granted", "denied"}:
            raise ValueError("last_decision is outside the closed v1 taxonomy")
        if self.last_denial_reason is not None:
            _enum("last denial reason", self.last_denial_reason, LeaseDenialReason)
        _enum("continuation progress state", self.progress_state, ProgressState)
        if (self.pending_grant_id is None) != (
            self.pending_grant_receipt_id is None
        ):
            raise ValueError("pending grant and receipt identities must be paired")
        if self.pending_grant_id is not None:
            require_fingerprint("pending grant id", self.pending_grant_id)
            require_fingerprint(
                "pending grant receipt id", self.pending_grant_receipt_id
            )
        if self.last_decision == "denied" and self.last_denial_reason is None:
            raise ValueError("a denied last decision requires a denial reason")
        if self.last_decision != "denied" and self.last_denial_reason is not None:
            raise ValueError("only a denied last decision may carry a denial reason")
        if (self.lease_requests == 0) != (self.last_decision == "none"):
            raise ValueError("last decision must match the recorded decision ledger")
        if self.last_decision == "granted" and self.leases_granted == 0:
            raise ValueError("a granted last decision requires a recorded grant")
        if self.last_decision == "denied" and self.leases_denied == 0:
            raise ValueError("a denied last decision requires a recorded denial")
        if self.last_consumed_progress_id is not None and self.leases_granted == 0:
            raise ValueError("consumed progress requires a recorded grant")
        if (
            self.last_consumed_external_progress_endpoint_id is not None
            and self.leases_granted == 0
        ):
            raise ValueError(
                "consumed external progress requires a recorded grant"
            )
        if (
            self.last_consumed_external_progress_endpoint_id is not None
            and self.last_external_progress_endpoint_id is None
        ):
            raise ValueError(
                "consumed external progress requires a live external endpoint"
            )
        if self.strategy_recoveries > self.leases_granted:
            raise ValueError("strategy recoveries cannot exceed recorded grants")
        if self._decision_lineage_capability is not None:
            from ._runtime import NativeContinuationStateSeal

            if type(self._decision_lineage_capability) is not NativeContinuationStateSeal:
                raise TypeError("continuation decision lineage is not trusted")
            if not bool(
                self._decision_lineage_capability.validates(
                    self._decision_lineage_text()
                )
            ):
                raise ValueError("continuation decision lineage does not match state")

    @classmethod
    def create(
        cls,
        *,
        policy: ContinuationPolicy,
        policy_receipt: ContinuationPolicyReceipt,
        runtime_session: RustRuntimeSession,
        orchestration_state: OrchestrationState,
        runtime_snapshot: RuntimeSnapshot,
        strategy: StrategyMaterialization | None = None,
        progress: ProgressRecord | None = None,
    ) -> ContinuationState:
        if type(policy) is not ContinuationPolicy:
            raise TypeError("policy must be an exact ContinuationPolicy")
        if type(policy_receipt) is not ContinuationPolicyReceipt:
            raise TypeError("policy_receipt must be an exact policy receipt")
        if type(runtime_session) is not RustRuntimeSession:
            raise TypeError("runtime_session must be an exact RustRuntimeSession")
        if policy_receipt.continuation_policy_id != policy.continuation_policy_id:
            raise ValueError("continuation policy receipt identity mismatch")
        if policy_receipt.progress_contract_id != policy.progress_contract_id:
            raise ValueError("continuation progress contract receipt mismatch")
        if type(orchestration_state) is not OrchestrationState:
            raise TypeError("orchestration_state must be exact OrchestrationState")
        if not isinstance(runtime_snapshot, RuntimeSnapshot):
            raise TypeError("runtime_snapshot must be a RuntimeSnapshot")
        live_runtime_snapshot = runtime_session.snapshot
        if (
            live_runtime_snapshot.session_id != runtime_snapshot.session_id
            or live_runtime_snapshot.state_id != runtime_snapshot.state_id
        ):
            raise ValueError("initial runtime snapshot is not the live session state")
        native_continuation = runtime_snapshot.continuation
        if native_continuation is None:
            raise ValueError("continuation state requires an opt-in native runtime")
        if (
            native_continuation.task_id != policy_receipt.task_id
            or native_continuation.governance_id != policy_receipt.governance_id
            or native_continuation.governance_receipt_id
            != policy_receipt.governance_receipt_id
            or native_continuation.continuation_policy_id
            != policy.continuation_policy_id
            or native_continuation.continuation_policy_receipt_id
            != policy_receipt.receipt_id
            or native_continuation.progress_contract_id
            != policy.progress_contract_id
        ):
            raise ValueError("native continuation context authority binding mismatch")
        if native_continuation.leases_applied != 0 or not all(
            value == 0
            for value in native_continuation.cumulative_granted.canonical_record().values()
        ):
            raise ValueError("new continuation state requires zero applied native leases")
        if (
            native_continuation.total_ceiling.canonical_record()
            != policy.total_ceiling.canonical_record()
        ):
            raise ValueError("native continuation ceiling does not match policy")
        expected = policy.initial_budget
        limits = runtime_snapshot.limits
        if (
            limits.max_requests != expected.request_delta
            or limits.max_executions != expected.execution_delta
            or limits.max_retries != expected.retry_delta
            or limits.max_history != expected.history_delta
        ):
            raise ValueError("runtime base limits do not match continuation policy")
        if strategy is not None and type(strategy) is not StrategyMaterialization:
            raise TypeError("strategy must be exact StrategyMaterialization or None")
        if progress is not None:
            if type(progress) is not ProgressRecord:
                raise TypeError("progress must be an exact ProgressRecord or None")
            if (
                progress.task_id != policy_receipt.task_id
                or progress.governance_id != policy_receipt.governance_id
                or progress.contract.contract_id != policy.progress_contract_id
                or progress.current_orchestration_state_id
                != orchestration_state.state_id
            ):
                raise ValueError("initial progress does not bind continuation context")
        initial = cls(
            task_id=policy_receipt.task_id,
            governance_id=policy_receipt.governance_id,
            governance_receipt_id=policy_receipt.governance_receipt_id,
            continuation_policy_id=policy.continuation_policy_id,
            continuation_policy_receipt_id=policy_receipt.receipt_id,
            progress_contract_id=policy.progress_contract_id,
            orchestration_state_id=orchestration_state.state_id,
            runtime_session_id=runtime_snapshot.session_id,
            runtime_state_id=runtime_snapshot.state_id,
            lease_requests=0,
            leases_granted=0,
            leases_denied=0,
            cumulative_granted=BudgetVector.zero(),
            continuation_logical_tick=0,
            decision_aggregate_id=_initial_decision_aggregate(
                task_id=policy_receipt.task_id,
                governance_id=policy_receipt.governance_id,
                continuation_policy_id=policy.continuation_policy_id,
            ),
            decision_receipt_ids=(),
            strategy_recoveries=0,
            current_strategy_material_id=(
                None if strategy is None else strategy.strategy_material_id
            ),
            last_progress_id=(
                None if progress is None else progress.progress_id
            ),
            progress_event_count=0 if progress is None else 1,
            progress_aggregate_id=_progress_aggregate(
                () if progress is None else (progress,)
            ),
            last_consumed_progress_id=None,
            last_external_progress_endpoint_id=(
                None
                if progress is None
                else progress.current_external_endpoint_id
            ),
            last_consumed_external_progress_endpoint_id=None,
            last_progress_classification=(
                None if progress is None else progress.classification
            ),
            last_decision="none",
            last_denial_reason=None,
            progress_state=(
                ProgressState.STALLED
                if progress is None
                else (
                    ProgressState.COMPLETE
                    if progress.task_complete
                    else (
                        ProgressState.PROGRESSING
                        if progress.classification
                        is ProgressClassification.MEASURABLE_PROGRESS
                        else ProgressState.STALLED
                    )
                )
            ),
        )
        sealed = runtime_session._seal_initial_continuation_state(
            initial,
            orchestration_state,
            progress,
            strategy,
        )
        if type(sealed) is not cls:
            raise TypeError("native runtime returned an invalid continuation state")
        return sealed

    @property
    def continuation_state_id(self) -> str:
        return domain_fingerprint(CONTINUATION_STATE_ID_DOMAIN, self.canonical_record())

    @property
    def has_pending_grant(self) -> bool:
        return self.pending_grant_id is not None

    def remaining_capacity(self, policy: ContinuationPolicy) -> BudgetVector:
        self._require_policy(policy)
        return policy.continuation_capacity.subtract_checked(
            self.cumulative_granted
        )

    def leases_remaining(self, policy: ContinuationPolicy) -> int:
        self._require_policy(policy)
        return policy.max_leases - self.leases_granted

    def _require_policy(self, policy: ContinuationPolicy) -> None:
        self._require_decision_lineage()
        if type(policy) is not ContinuationPolicy:
            raise TypeError("policy must be an exact ContinuationPolicy")
        policy._validate_authority_fields()
        if policy.continuation_policy_id != self.continuation_policy_id:
            raise ValueError("continuation state policy identity mismatch")
        if policy.progress_contract_id != self.progress_contract_id:
            raise ValueError("continuation state progress contract mismatch")
        if self.leases_granted > policy.max_leases:
            raise ValueError("continuation state exceeds the policy lease count")
        if self.lease_requests > policy.max_lease_requests:
            raise ValueError("continuation state exceeds the request ceiling")
        if self.progress_event_count > policy.max_lease_requests + 1:
            raise ValueError("continuation state exceeds progress evidence capacity")
        if self.strategy_recoveries > policy.max_strategy_recoveries:
            raise ValueError("continuation state exceeds strategy recovery capacity")

    def compact_projection(self, policy: ContinuationPolicy) -> dict[str, Any]:
        self._require_policy(policy)
        request_decisions_remaining = policy.max_lease_requests - self.lease_requests
        schedule_slots_remaining = self.leases_remaining(policy)
        progress_observations_remaining = (
            policy.max_lease_requests + 1 - self.progress_event_count
        )
        recovery_actions: list[str] = []
        strategy_recovery_available = (
            self.current_strategy_material_id is not None
            and self.strategy_recoveries < policy.max_strategy_recoveries
        )
        if request_decisions_remaining == 0 or schedule_slots_remaining == 0:
            recovery_actions = []
        elif self.progress_state is ProgressState.STALLED:
            if progress_observations_remaining > 0:
                recovery_actions.append("provide_objective_progress")
            if strategy_recovery_available:
                recovery_actions.append("propose_material_strategy_change")
        elif self.progress_state is ProgressState.CYCLE_BLOCKED:
            if strategy_recovery_available:
                recovery_actions.append("propose_cycle_breaking_strategy")
        elif self.progress_state is ProgressState.STRATEGY_CHANGE_REJECTED:
            if strategy_recovery_available:
                recovery_actions.append("provide_material_semantic_difference")
        if self.has_pending_grant:
            recovery_actions = ["apply_pending_lease"]
        return {
            "continuation_policy_id": self.continuation_policy_id,
            "progress_contract_id": self.progress_contract_id,
            "continuation_state_id": self.continuation_state_id,
            "current_progress_classification": (
                None
                if self.last_progress_classification is None
                else self.last_progress_classification.value
            ),
            "current_progress_evidence_id": self.last_progress_id,
            "last_denial_reason": (
                None
                if self.last_denial_reason is None
                else self.last_denial_reason.value
            ),
            "last_lease_decision": self.last_decision,
            "lease_requests_remaining": request_decisions_remaining,
            "lease_schedule_slots_remaining": schedule_slots_remaining,
            "leases_remaining": min(
                request_decisions_remaining, schedule_slots_remaining
            ),
            "leases_used": self.leases_granted,
            "legal_recovery_actions": recovery_actions,
            "material_strategy_change_admissible": (
                request_decisions_remaining > 0
                and schedule_slots_remaining > 0
                and not self.has_pending_grant
                and self.current_strategy_material_id is not None
                and self.strategy_recoveries < policy.max_strategy_recoveries
                and self.progress_state
                not in {ProgressState.COMPLETE, ProgressState.LEASE_EXHAUSTED}
            ),
            "pending_grant_receipt_id": self.pending_grant_receipt_id,
            "progress_observations_remaining": progress_observations_remaining,
            "progress_state": self.progress_state.value,
            "remaining_total_continuation_ceiling": self.remaining_capacity(
                policy
            ).canonical_record(),
        }

    def _decision_lineage_record(self) -> dict[str, Any]:
        """Return the complete authority-bearing state protected by Rust."""

        return self._canonical_record_unchecked()

    def _decision_lineage_text(self) -> str:
        return canonical_json(self._decision_lineage_record())

    def _with_native_lineage(self, seal: Any) -> ContinuationState:
        from ._runtime import NativeContinuationStateSeal

        if self._decision_lineage_capability is not None:
            raise ValueError("continuation state already carries decision lineage")
        if type(seal) is not NativeContinuationStateSeal:
            raise TypeError("continuation decision lineage seal is not trusted")
        if not bool(seal.validates(self._decision_lineage_text())):
            raise ValueError("continuation decision lineage does not match state")
        return replace(self, _decision_lineage_capability=seal)

    def _native_lineage_seal(self) -> Any | None:
        self._require_decision_lineage()
        return self._decision_lineage_capability

    def _require_decision_lineage(self) -> None:
        capability = self._decision_lineage_capability
        from ._runtime import NativeContinuationStateSeal

        if type(capability) is not NativeContinuationStateSeal:
            raise ValueError("continuation state lacks evaluated decision lineage")
        if not bool(capability.validates(self._decision_lineage_text())):
            raise ValueError("continuation decision lineage does not match state")

    def canonical_record(self) -> dict[str, Any]:
        self._require_decision_lineage()
        return self._canonical_record_unchecked()

    def _canonical_record_unchecked(self) -> dict[str, Any]:
        return {
            "continuation_logical_tick": self.continuation_logical_tick,
            "continuation_policy_id": self.continuation_policy_id,
            "continuation_policy_receipt_id": self.continuation_policy_receipt_id,
            "progress_contract_id": self.progress_contract_id,
            "cumulative_granted": self.cumulative_granted.canonical_record(),
            "current_strategy_material_id": self.current_strategy_material_id,
            "decision_aggregate_id": self.decision_aggregate_id,
            "decision_receipt_ids": list(self.decision_receipt_ids),
            "governance_id": self.governance_id,
            "governance_receipt_id": self.governance_receipt_id,
            "last_decision": self.last_decision,
            "last_denial_reason": (
                None
                if self.last_denial_reason is None
                else self.last_denial_reason.value
            ),
            "last_progress_classification": (
                None
                if self.last_progress_classification is None
                else self.last_progress_classification.value
            ),
            "last_consumed_progress_id": self.last_consumed_progress_id,
            "last_consumed_external_progress_endpoint_id": (
                self.last_consumed_external_progress_endpoint_id
            ),
            "last_progress_id": self.last_progress_id,
            "progress_event_count": self.progress_event_count,
            "progress_aggregate_id": self.progress_aggregate_id,
            "last_external_progress_endpoint_id": (
                self.last_external_progress_endpoint_id
            ),
            "lease_requests": self.lease_requests,
            "leases_denied": self.leases_denied,
            "leases_granted": self.leases_granted,
            "orchestration_state_id": self.orchestration_state_id,
            "pending_grant_id": self.pending_grant_id,
            "pending_grant_receipt_id": self.pending_grant_receipt_id,
            "progress_state": self.progress_state.value,
            "protocol_version": CONTINUATION_PROTOCOL_VERSION,
            "runtime_session_id": self.runtime_session_id,
            "runtime_state_id": self.runtime_state_id,
            "strategy_recoveries": self.strategy_recoveries,
            "task_id": self.task_id,
        }


def _observe_continuation_context(
    state: ContinuationState,
    *,
    policy: ContinuationPolicy,
    orchestration_state: OrchestrationState,
    runtime_snapshot: RuntimeSnapshot,
    progress: ProgressRecord | None = None,
    strategy: StrategyMaterialization | None = None,
) -> ContinuationState:
    """Rebind ordinary work state without consuming a continuation quantum."""

    if type(state) is not ContinuationState:
        raise TypeError("state must be an exact ContinuationState")
    state._require_policy(policy)
    if state.has_pending_grant:
        raise ValueError("a pending lease must be applied before context advances")
    if type(orchestration_state) is not OrchestrationState:
        raise TypeError("orchestration_state must be exact OrchestrationState")
    if not isinstance(runtime_snapshot, RuntimeSnapshot):
        raise TypeError("runtime_snapshot must be a RuntimeSnapshot")
    if runtime_snapshot.session_id != state.runtime_session_id:
        raise ValueError("runtime session identity cannot change")
    native_continuation = runtime_snapshot.continuation
    if native_continuation is None:
        raise ValueError("continuation context requires an opt-in native runtime")
    if (
        native_continuation.task_id != state.task_id
        or native_continuation.governance_id != state.governance_id
        or native_continuation.governance_receipt_id != state.governance_receipt_id
        or native_continuation.continuation_policy_id
        != state.continuation_policy_id
        or native_continuation.continuation_policy_receipt_id
        != state.continuation_policy_receipt_id
        or native_continuation.progress_contract_id
        != state.progress_contract_id
        or native_continuation.leases_applied != state.leases_granted
        or native_continuation.cumulative_granted.canonical_record()
        != state.cumulative_granted.canonical_record()
        or native_continuation.total_ceiling.canonical_record()
        != policy.total_ceiling.canonical_record()
    ):
        raise ValueError("native continuation state does not match governance state")
    expected = policy.initial_budget.add_checked(state.cumulative_granted)
    limits = runtime_snapshot.limits
    if (
        limits.max_requests != expected.request_delta
        or limits.max_executions != expected.execution_delta
        or limits.max_retries != expected.retry_delta
        or limits.max_history != expected.history_delta
    ):
        raise ValueError("runtime limits do not match applied continuation grants")
    if progress is not None:
        if type(progress) is not ProgressRecord:
            raise TypeError("progress must be an exact ProgressRecord")
        if (
            progress.task_id != state.task_id
            or progress.governance_id != state.governance_id
            or progress.contract.contract_id != state.progress_contract_id
            or progress.prior_orchestration_state_id
            != state.orchestration_state_id
            or progress.current_orchestration_state_id != orchestration_state.state_id
        ):
            raise ValueError("progress does not bind the observed context")
        if (
            state.last_external_progress_endpoint_id is not None
            and progress.prior_external_endpoint_id
            != state.last_external_progress_endpoint_id
        ):
            raise ValueError(
                "external progress does not continue from the live endpoint"
            )
        if state.progress_event_count >= policy.max_lease_requests + 1:
            raise ValueError("progress history exceeds the bounded evidence capacity")
    elif orchestration_state.state_id != state.orchestration_state_id:
        raise ValueError(
            "orchestration state cannot advance without exact progress lineage"
        )
    if strategy is not None and type(strategy) is not StrategyMaterialization:
        raise TypeError("strategy must be exact StrategyMaterialization or None")
    return replace(
        state,
        _decision_lineage_capability=None,
        orchestration_state_id=orchestration_state.state_id,
        runtime_state_id=runtime_snapshot.state_id,
        current_strategy_material_id=(
            state.current_strategy_material_id
            if strategy is None
            else strategy.strategy_material_id
        ),
        last_progress_id=(
            state.last_progress_id if progress is None else progress.progress_id
        ),
        progress_event_count=(
            state.progress_event_count
            if progress is None
            else state.progress_event_count + 1
        ),
        progress_aggregate_id=(
            state.progress_aggregate_id
            if progress is None
            else _advance_progress_aggregate(
                state.progress_aggregate_id,
                progress.progress_id,
                state.progress_event_count,
            )
        ),
        last_external_progress_endpoint_id=(
            state.last_external_progress_endpoint_id
            if progress is None
            else progress.current_external_endpoint_id
        ),
        last_progress_classification=(
            state.last_progress_classification
            if progress is None
            else progress.classification
        ),
        progress_state=(
            state.progress_state
            if progress is None
            else (
                ProgressState.COMPLETE
                if progress.task_complete
                else (
                    ProgressState.PROGRESSING
                    if progress.classification
                    is ProgressClassification.MEASURABLE_PROGRESS
                    else ProgressState.STALLED
                )
            )
        ),
    )


def observe_continuation_context(
    state: ContinuationState,
    *,
    runtime_session: RustRuntimeSession,
    policy: ContinuationPolicy,
    orchestration_state: OrchestrationState,
    runtime_snapshot: RuntimeSnapshot,
    progress: ProgressRecord | None = None,
    strategy: StrategyMaterialization | None = None,
) -> ContinuationState:
    """Rebind context and preserve native evaluator lineage when it exists."""

    if type(state) is not ContinuationState:
        raise TypeError("state must be an exact ContinuationState")
    if type(runtime_session) is not RustRuntimeSession:
        raise TypeError("runtime_session must be an exact RustRuntimeSession")
    lineage = state._native_lineage_seal()
    observed = runtime_session._observe_continuation_context(
        lineage,
        state,
        policy,
        orchestration_state,
        runtime_snapshot,
        progress,
        strategy,
    )
    if type(observed) is not ContinuationState:
        raise TypeError("native observer returned an invalid continuation state")
    return observed


def _commit_lease_application(
    state: ContinuationState,
    *,
    policy: ContinuationPolicy,
    grant: LeaseGrantReceipt,
    application: RuntimeLeaseApplicationReceipt,
    runtime_snapshot: RuntimeSnapshot,
) -> ContinuationState:
    """Commit one exact Rust-applied grant back into governance lineage."""

    if type(state) is not ContinuationState:
        raise TypeError("state must be an exact ContinuationState")
    state._require_policy(policy)
    if type(grant) is not LeaseGrantReceipt:
        raise TypeError("grant must be an exact LeaseGrantReceipt")
    if type(application) is not RuntimeLeaseApplicationReceipt:
        raise TypeError("application must be an exact runtime lease receipt")
    if not isinstance(runtime_snapshot, RuntimeSnapshot):
        raise TypeError("runtime_snapshot must be a RuntimeSnapshot")
    if application.status != "accepted":
        raise ValueError("only an accepted Rust lease application may be committed")
    application_record = application.canonical_record()
    if (
        state.pending_grant_id != grant.lease_grant_id
        or state.pending_grant_receipt_id != grant.receipt_id
        or application.lease_grant_id != grant.lease_grant_id
        or application_record["grant_receipt_id"] != grant.receipt_id
        or application_record["task_id"] != state.task_id
        or application_record["governance_id"] != state.governance_id
        or application_record["continuation_policy_id"]
        != state.continuation_policy_id
        or application_record["continuation_policy_receipt_id"]
        != state.continuation_policy_receipt_id
        or application_record["session_id"] != state.runtime_session_id
        or application_record["lease_index"] != state.leases_granted
        or application_record["cumulative_granted"]
        != state.cumulative_granted.canonical_record()
        or application_record["total_ceiling"]
        != policy.total_ceiling.canonical_record()
        or application.prior_state_id != state.runtime_state_id
        or application.resulting_state_id != runtime_snapshot.state_id
        or runtime_snapshot.session_id != state.runtime_session_id
    ):
        raise ValueError("runtime lease application lineage mismatch")
    if (
        grant.task_id != state.task_id
        or grant.governance_id != state.governance_id
        or grant.continuation_policy_id != state.continuation_policy_id
        or grant.lease_index != state.leases_granted
        or grant.cumulative_granted != state.cumulative_granted
    ):
        raise ValueError("lease grant does not match pending governance state")
    native_continuation = runtime_snapshot.continuation
    if native_continuation is None:
        raise ValueError("lease application requires an opt-in native snapshot")
    if (
        native_continuation.task_id != state.task_id
        or native_continuation.governance_id != state.governance_id
        or native_continuation.governance_receipt_id
        != state.governance_receipt_id
        or native_continuation.continuation_policy_id
        != state.continuation_policy_id
        or native_continuation.continuation_policy_receipt_id
        != state.continuation_policy_receipt_id
        or native_continuation.progress_contract_id
        != state.progress_contract_id
        or native_continuation.leases_applied != state.leases_granted
        or native_continuation.applied_grant_ids[-1:] != (grant.lease_grant_id,)
        or native_continuation.cumulative_granted.canonical_record()
        != state.cumulative_granted.canonical_record()
    ):
        raise ValueError("native lease application state does not match the grant")
    expected = policy.initial_budget.add_checked(state.cumulative_granted)
    if (
        runtime_snapshot.limits.max_requests != expected.request_delta
        or runtime_snapshot.limits.max_executions != expected.execution_delta
        or runtime_snapshot.limits.max_retries != expected.retry_delta
        or runtime_snapshot.limits.max_history != expected.history_delta
    ):
        raise ValueError("native resulting limits do not match applied lease")
    return replace(
        state,
        _decision_lineage_capability=None,
        runtime_state_id=runtime_snapshot.state_id,
        pending_grant_id=None,
        pending_grant_receipt_id=None,
    )


def commit_lease_application(
    state: ContinuationState,
    *,
    runtime_session: RustRuntimeSession,
    policy: ContinuationPolicy,
    grant: LeaseGrantReceipt,
    application: RuntimeLeaseApplicationReceipt,
    runtime_snapshot: RuntimeSnapshot,
) -> ContinuationState:
    """Commit an application only through its exact live native session."""

    if type(state) is not ContinuationState:
        raise TypeError("state must be an exact ContinuationState")
    if type(runtime_session) is not RustRuntimeSession:
        raise TypeError("runtime_session must be an exact RustRuntimeSession")
    lineage = state._native_lineage_seal()
    committed = runtime_session._commit_continuation_lease_application(
        lineage,
        state,
        policy,
        grant,
        application,
        runtime_snapshot,
    )
    if type(committed) is not ContinuationState:
        raise TypeError("native committer returned an invalid continuation state")
    return committed


@dataclass(frozen=True, slots=True)
class ContinuationRequest:
    task_id: str
    governance_id: str
    continuation_policy_id: str
    continuation_state_id: str
    orchestration_state_id: str
    runtime_session_id: str
    runtime_state_id: str
    progress_id: str
    lease_index: int
    requested_resources: BudgetVector
    requester: ContinuationRequester | PrincipalAuthority
    strategy_change_id: str | None = None
    _native_request_seal: Any | None = field(
        default=None, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        for name, value in (
            ("continuation request task id", self.task_id),
            ("continuation request governance id", self.governance_id),
            ("continuation request policy id", self.continuation_policy_id),
            ("continuation request state id", self.continuation_state_id),
            ("continuation request orchestration id", self.orchestration_state_id),
            ("continuation request runtime session id", self.runtime_session_id),
            ("continuation request runtime state id", self.runtime_state_id),
            ("continuation request progress id", self.progress_id),
        ):
            require_fingerprint(name, value)
        _u64("continuation request lease index", self.lease_index)
        if self.lease_index == 0:
            raise ValueError("continuation request lease index must be positive")
        if type(self.requested_resources) is not BudgetVector:
            raise TypeError("requested_resources must be an exact BudgetVector")
        object.__setattr__(
            self, "requester", ContinuationRequester.normalize(self.requester)
        )
        if self.strategy_change_id is not None:
            require_fingerprint(
                "continuation request strategy change id", self.strategy_change_id
            )
        if self._native_request_seal is not None:
            from ._runtime import NativeContinuationRequestSeal

            if self.requester is not ContinuationRequester.OPENAI_SUPERVISOR:
                raise ValueError("only the supervisor may carry request authority")
            if type(self._native_request_seal) is not NativeContinuationRequestSeal:
                raise TypeError("continuation request authority is not trusted")
            if not bool(
                self._native_request_seal.validates(self._canonical_text())
            ):
                raise ValueError("continuation request authority does not match")

    @classmethod
    def from_state(
        cls,
        state: ContinuationState,
        *,
        progress: ProgressRecord,
        requested_resources: BudgetVector,
        requester: ContinuationRequester | PrincipalAuthority,
        requester_authority: Any | None = None,
        strategy_change: StrategyChangeReceipt | None = None,
    ) -> ContinuationRequest:
        if type(state) is not ContinuationState:
            raise TypeError("state must be an exact ContinuationState")
        if type(progress) is not ProgressRecord:
            raise TypeError("progress must be an exact ProgressRecord")
        if strategy_change is not None and type(
            strategy_change
        ) is not StrategyChangeReceipt:
            raise TypeError("strategy_change must be exact receipt or None")
        if (
            progress.task_id != state.task_id
            or progress.governance_id != state.governance_id
            or progress.contract.contract_id != state.progress_contract_id
            or progress.current_orchestration_state_id
            != state.orchestration_state_id
            or progress.progress_id != state.last_progress_id
        ):
            raise ValueError("progress does not match the live continuation ledger")
        request = cls(
            task_id=state.task_id,
            governance_id=state.governance_id,
            continuation_policy_id=state.continuation_policy_id,
            continuation_state_id=state.continuation_state_id,
            orchestration_state_id=state.orchestration_state_id,
            runtime_session_id=state.runtime_session_id,
            runtime_state_id=state.runtime_state_id,
            progress_id=progress.progress_id,
            lease_index=state.leases_granted + 1,
            requested_resources=requested_resources,
            requester=requester,
            strategy_change_id=(
                None
                if strategy_change is None
                else strategy_change.strategy_change_id
            ),
        )
        if requester_authority is None:
            return request
        return request._with_request_authority(requester_authority)

    def _with_request_authority(self, requester_authority: Any) -> ContinuationRequest:
        from ._runtime import NativeContinuationSupervisorAuthority

        if type(requester_authority) is not NativeContinuationSupervisorAuthority:
            raise TypeError("requester_authority is not trusted")
        if self.requester is not ContinuationRequester.OPENAI_SUPERVISOR:
            raise ValueError("non-supervisor requesters cannot use supervisor authority")
        seal = requester_authority.authorize_request(
            self._canonical_text(),
        )
        return replace(self, _native_request_seal=seal)

    @property
    def continuation_request_id(self) -> str:
        return domain_fingerprint(
            CONTINUATION_REQUEST_ID_DOMAIN, self.canonical_record()
        )

    def canonical_record(self) -> dict[str, Any]:
        return {
            "continuation_policy_id": self.continuation_policy_id,
            "continuation_state_id": self.continuation_state_id,
            "governance_id": self.governance_id,
            "lease_index": self.lease_index,
            "orchestration_state_id": self.orchestration_state_id,
            "progress_id": self.progress_id,
            "protocol_version": CONTINUATION_PROTOCOL_VERSION,
            "requested_resources": self.requested_resources.canonical_record(),
            "requester": self.requester.value,
            "runtime_session_id": self.runtime_session_id,
            "runtime_state_id": self.runtime_state_id,
            "strategy_change_id": self.strategy_change_id,
            "task_id": self.task_id,
        }

    def _canonical_text(self) -> str:
        return canonical_json(self.canonical_record())

    def _native_request_authority(self) -> Any | None:
        seal = self._native_request_seal
        if seal is None:
            return None
        from ._runtime import NativeContinuationRequestSeal

        if type(seal) is not NativeContinuationRequestSeal or not bool(
            seal.validates(self._canonical_text())
        ):
            raise ValueError("continuation request lacks exact native authority")
        return seal


@dataclass(frozen=True, slots=True)
class LeaseGrantReceipt:
    task_id: str
    governance_id: str
    governance_receipt_id: str
    continuation_policy_id: str
    continuation_policy_receipt_id: str
    continuation_request_id: str
    prior_continuation_state_id: str
    orchestration_state_id: str
    runtime_session_id: str
    prior_runtime_state_id: str
    progress_id: str
    strategy_change_id: str | None
    lease_index: int
    granted_resources: BudgetVector
    cumulative_granted: BudgetVector
    total_ceiling: BudgetVector
    decision_logical_tick: int
    _native_seal: Any | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        for name, value in (
            ("lease task id", self.task_id),
            ("lease governance id", self.governance_id),
            ("lease governance receipt id", self.governance_receipt_id),
            ("lease continuation policy id", self.continuation_policy_id),
            (
                "lease continuation policy receipt id",
                self.continuation_policy_receipt_id,
            ),
            ("lease continuation request id", self.continuation_request_id),
            ("lease prior continuation state id", self.prior_continuation_state_id),
            ("lease orchestration state id", self.orchestration_state_id),
            ("lease runtime session id", self.runtime_session_id),
            ("lease prior runtime state id", self.prior_runtime_state_id),
            ("lease progress id", self.progress_id),
        ):
            require_fingerprint(name, value)
        if self.strategy_change_id is not None:
            require_fingerprint("lease strategy change id", self.strategy_change_id)
        _u64("lease index", self.lease_index)
        if self.lease_index == 0:
            raise ValueError("lease index must be positive")
        _u64("lease decision logical tick", self.decision_logical_tick)
        for name, value in (
            ("granted_resources", self.granted_resources),
            ("cumulative_granted", self.cumulative_granted),
            ("total_ceiling", self.total_ceiling),
        ):
            if type(value) is not BudgetVector:
                raise TypeError(f"{name} must be an exact BudgetVector")
        if self.granted_resources.is_zero:
            raise ValueError("a lease grant cannot carry an empty resource vector")
        if self.granted_resources.mutation_delta != 0:
            raise ValueError("v0.5 lease grants cannot authorize mutations")
        if not self.cumulative_granted.is_within(self.total_ceiling):
            raise ValueError("cumulative lease resources exceed the total ceiling")
        if self._native_seal is not None:
            from ._runtime import NativeLeaseGrantSeal

            if type(self._native_seal) is not NativeLeaseGrantSeal:
                raise TypeError("lease grant requires a native governance seal")
            if not bool(
                self._native_seal.validates(canonical_json(self.canonical_record()))
            ):
                raise ValueError("native lease grant seal does not match its receipt")

    def _grant_body(self) -> dict[str, Any]:
        return {
            "authority_layer": "governance",
            "continuation_policy_id": self.continuation_policy_id,
            "continuation_policy_receipt_id": self.continuation_policy_receipt_id,
            "continuation_request_id": self.continuation_request_id,
            "cumulative_granted": self.cumulative_granted.canonical_record(),
            "decision_logical_tick": self.decision_logical_tick,
            "governance_id": self.governance_id,
            "governance_receipt_id": self.governance_receipt_id,
            "granted_resources": self.granted_resources.canonical_record(),
            "lease_index": self.lease_index,
            "orchestration_state_id": self.orchestration_state_id,
            "prior_continuation_state_id": self.prior_continuation_state_id,
            "prior_runtime_state_id": self.prior_runtime_state_id,
            "progress_id": self.progress_id,
            "protocol_version": LEASE_GRANT_RECEIPT_VERSION,
            "runtime_session_id": self.runtime_session_id,
            "status": "granted",
            "strategy_change_id": self.strategy_change_id,
            "task_id": self.task_id,
            "total_ceiling": self.total_ceiling.canonical_record(),
        }

    @property
    def lease_grant_id(self) -> str:
        return domain_fingerprint(LEASE_GRANT_ID_DOMAIN, self._grant_body())

    @property
    def receipt_id(self) -> str:
        return self.canonical_record()["receipt_id"]

    def canonical_record(self) -> dict[str, Any]:
        return _with_receipt_id(
            LEASE_GRANT_RECEIPT_ID_DOMAIN,
            {**self._grant_body(), "lease_grant_id": self.lease_grant_id},
        )

    @property
    def source_bound(self) -> bool:
        return self.governance_bound

    @property
    def governance_bound(self) -> bool:
        from ._runtime import NativeLeaseGrantSeal

        return (
            type(self._native_seal) is NativeLeaseGrantSeal
            and bool(self._native_seal.validates(self._canonical_text()))
        )

    def _with_native_seal(self, seal: Any) -> LeaseGrantReceipt:
        if self._native_seal is not None:
            raise ValueError("lease grant is already source-bound")
        from ._runtime import NativeLeaseGrantSeal

        if type(seal) is not NativeLeaseGrantSeal:
            raise TypeError("lease grant native authority is not trusted")
        if not bool(seal.validates(self._canonical_text())):
            raise ValueError("lease grant native authority does not match")
        return replace(self, _native_seal=seal)

    def _native_source_seal(self) -> Any | None:
        if self._native_seal is None:
            return None
        from ._runtime import NativeLeaseGrantSeal

        if type(self._native_seal) is not NativeLeaseGrantSeal:
            raise ValueError("lease grant native source seal is not trusted")
        if not bool(
            self._native_seal.validates(self._canonical_text())
        ):
            raise ValueError("lease grant native source seal no longer matches")
        return self._native_seal

    def _canonical_text(self) -> str:
        return canonical_json(self.canonical_record())


@dataclass(frozen=True, slots=True)
class LeaseDenyReceipt:
    task_id: str
    governance_id: str
    continuation_policy_id: str
    continuation_request_id: str
    prior_continuation_state_id: str
    orchestration_state_id: str
    runtime_state_id: str
    progress_id: str
    strategy_change_id: str | None
    lease_index: int
    denial_reason: LeaseDenialReason
    decision_logical_tick: int
    blocking_evidence_id: str | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("lease denial task id", self.task_id),
            ("lease denial governance id", self.governance_id),
            ("lease denial policy id", self.continuation_policy_id),
            ("lease denial request id", self.continuation_request_id),
            (
                "lease denial prior continuation state id",
                self.prior_continuation_state_id,
            ),
            ("lease denial orchestration id", self.orchestration_state_id),
            ("lease denial runtime id", self.runtime_state_id),
            ("lease denial progress id", self.progress_id),
        ):
            require_fingerprint(name, value)
        if self.strategy_change_id is not None:
            require_fingerprint(
                "lease denial strategy change id", self.strategy_change_id
            )
        if self.blocking_evidence_id is not None:
            require_fingerprint(
                "lease denial blocking evidence id", self.blocking_evidence_id
            )
        _u64("lease denial lease index", self.lease_index)
        _u64("lease denial logical tick", self.decision_logical_tick)
        _enum("lease denial reason", self.denial_reason, LeaseDenialReason)

    def _denial_body(self) -> dict[str, Any]:
        return {
            "authority_layer": "governance",
            "blocking_evidence_id": self.blocking_evidence_id,
            "continuation_policy_id": self.continuation_policy_id,
            "continuation_request_id": self.continuation_request_id,
            "decision_logical_tick": self.decision_logical_tick,
            "denial_reason": self.denial_reason.value,
            "governance_id": self.governance_id,
            "lease_index": self.lease_index,
            "orchestration_state_id": self.orchestration_state_id,
            "prior_continuation_state_id": self.prior_continuation_state_id,
            "progress_id": self.progress_id,
            "protocol_version": LEASE_DENY_RECEIPT_VERSION,
            "runtime_state_id": self.runtime_state_id,
            "status": "denied",
            "strategy_change_id": self.strategy_change_id,
            "task_id": self.task_id,
        }

    @property
    def lease_denial_id(self) -> str:
        return domain_fingerprint(LEASE_DENIAL_ID_DOMAIN, self._denial_body())

    @property
    def receipt_id(self) -> str:
        return self.canonical_record()["receipt_id"]

    def canonical_record(self) -> dict[str, Any]:
        return _with_receipt_id(
            LEASE_DENY_RECEIPT_ID_DOMAIN,
            {**self._denial_body(), "lease_denial_id": self.lease_denial_id},
        )


@dataclass(frozen=True, slots=True)
class _ContinuationEvaluationResult:
    """Unsigned deterministic result finalized only by native request authority."""

    next_state: ContinuationState
    receipt: LeaseGrantReceipt | LeaseDenyReceipt

    @property
    def granted(self) -> bool:
        return type(self.receipt) is LeaseGrantReceipt

    def _finalize(
        self,
        next_state: ContinuationState,
        receipt: LeaseGrantReceipt | LeaseDenyReceipt,
    ) -> ContinuationDecision:
        if type(next_state) is not ContinuationState:
            raise TypeError("finalized state must be exact ContinuationState")
        if type(receipt) is not type(self.receipt):
            raise TypeError("finalized receipt type does not match evaluation")
        if (
            next_state._canonical_record_unchecked()
            != self.next_state._canonical_record_unchecked()
        ):
            raise ValueError("finalized state does not match evaluation")
        if receipt.canonical_record() != self.receipt.canonical_record():
            raise ValueError("finalized receipt does not match evaluation")
        return ContinuationDecision(next_state, receipt)


@dataclass(frozen=True, slots=True)
class ContinuationDecision:
    next_state: ContinuationState
    receipt: LeaseGrantReceipt | LeaseDenyReceipt

    def __post_init__(self) -> None:
        if type(self.next_state) is not ContinuationState:
            raise TypeError("next_state must be an exact ContinuationState")
        if type(self.receipt) not in {LeaseGrantReceipt, LeaseDenyReceipt}:
            raise TypeError("receipt must be an exact lease decision receipt")
        if type(self.receipt) is LeaseGrantReceipt and not self.receipt.source_bound:
            raise ValueError("granted decisions require evaluated native authority")

    @property
    def granted(self) -> bool:
        return type(self.receipt) is LeaseGrantReceipt


def _denial_state(reason: LeaseDenialReason) -> ProgressState:
    if reason is LeaseDenialReason.TASK_ALREADY_COMPLETE:
        return ProgressState.COMPLETE
    if reason in {
        LeaseDenialReason.LEASE_CEILING_REACHED,
        LeaseDenialReason.LEASE_REQUEST_LIMIT,
    }:
        return ProgressState.LEASE_EXHAUSTED
    if reason in {
        LeaseDenialReason.TERMINAL_CYCLE,
        LeaseDenialReason.STRATEGY_CHANGE_CYCLE_EQUIVALENT,
    }:
        return ProgressState.CYCLE_BLOCKED
    if reason is LeaseDenialReason.STRATEGY_CHANGE_NOT_MATERIAL:
        return ProgressState.STRATEGY_CHANGE_REJECTED
    return ProgressState.STALLED


def _deny_continuation(
    state: ContinuationState,
    request: ContinuationRequest,
    progress: ProgressRecord,
    reason: LeaseDenialReason,
    *,
    policy: ContinuationPolicy,
    blocking_evidence_id: str | None = None,
    record_decision: bool = True,
) -> _ContinuationEvaluationResult:
    if blocking_evidence_id is not None:
        require_fingerprint("blocking governance evidence id", blocking_evidence_id)
    decision_tick = state.continuation_logical_tick + (
        1 if record_decision else 0
    )
    denial = LeaseDenyReceipt(
        task_id=state.task_id,
        governance_id=state.governance_id,
        continuation_policy_id=state.continuation_policy_id,
        continuation_request_id=request.continuation_request_id,
        prior_continuation_state_id=state.continuation_state_id,
        orchestration_state_id=state.orchestration_state_id,
        runtime_state_id=state.runtime_state_id,
        progress_id=progress.progress_id,
        strategy_change_id=request.strategy_change_id,
        lease_index=request.lease_index,
        denial_reason=reason,
        decision_logical_tick=decision_tick,
        blocking_evidence_id=blocking_evidence_id,
    )
    if not record_decision:
        return _ContinuationEvaluationResult(state, denial)
    ordinal = state.lease_requests
    next_state = replace(
        state,
        _decision_lineage_capability=None,
        lease_requests=state.lease_requests + 1,
        leases_denied=state.leases_denied + 1,
        continuation_logical_tick=decision_tick,
        decision_aggregate_id=_advance_decision_aggregate(
            state.decision_aggregate_id, denial.receipt_id, ordinal
        ),
        decision_receipt_ids=(*state.decision_receipt_ids, denial.receipt_id),
        last_decision="denied",
        last_denial_reason=reason,
        progress_state=_denial_state(reason),
    )
    # The constructor bounds the history; the evaluator must never cross the
    # precommitted request ceiling.
    if next_state.lease_requests > policy.max_lease_requests:
        raise AssertionError("continuation request accounting exceeded policy")
    return _ContinuationEvaluationResult(next_state, denial)


def _evaluate_continuation(
    state: ContinuationState,
    request: ContinuationRequest,
    *,
    runtime_session: RustRuntimeSession,
    policy: ContinuationPolicy,
    policy_receipt: ContinuationPolicyReceipt,
    progress: ProgressRecord,
    strategy_change: StrategyChangeReceipt | None = None,
    cycle_evidence: CycleEvidence | None = None,
    blocking_governance_violation_id: str | None = None,
    benchmark_observation: Any | None = None,
    _request_authorized: bool,
) -> _ContinuationEvaluationResult:
    """Return a deterministic finite GRANT or DENY decision.

    ``benchmark_observation`` is deliberately never inspected.  Benchmark
    data is outside correctness authority and cannot execute caller callbacks
    while governance evaluates a lease request.
    """

    if type(state) is not ContinuationState:
        raise TypeError("state must be an exact ContinuationState")
    if type(request) is not ContinuationRequest:
        raise TypeError("request must be an exact ContinuationRequest")
    if type(runtime_session) is not RustRuntimeSession:
        raise TypeError("runtime_session must be an exact RustRuntimeSession")
    if type(policy) is not ContinuationPolicy:
        raise TypeError("policy must be an exact ContinuationPolicy")
    if type(policy_receipt) is not ContinuationPolicyReceipt:
        raise TypeError("policy_receipt must be an exact policy receipt")
    if type(progress) is not ProgressRecord:
        raise TypeError("progress must be an exact ProgressRecord")
    if type(_request_authorized) is not bool:
        raise TypeError("request authorization must be an exact boolean")
    if strategy_change is not None and type(
        strategy_change
    ) is not StrategyChangeReceipt:
        raise TypeError("strategy_change must be exact receipt or None")
    if cycle_evidence is not None and type(cycle_evidence) is not CycleEvidence:
        raise TypeError("cycle_evidence must be exact evidence or None")
    if blocking_governance_violation_id is not None:
        require_fingerprint(
            "blocking governance violation id",
            blocking_governance_violation_id,
        )

    state._require_policy(policy)
    if (
        policy_receipt.continuation_policy_id != policy.continuation_policy_id
        or policy_receipt.receipt_id != state.continuation_policy_receipt_id
        or policy_receipt.task_id != state.task_id
        or policy_receipt.governance_id != state.governance_id
        or policy_receipt.progress_contract_id != state.progress_contract_id
    ):
        raise ValueError("active continuation policy receipt does not bind state")

    live_runtime_snapshot = runtime_session.snapshot
    live_cycle_evidence = CycleEvidence.from_snapshot(live_runtime_snapshot)

    reason: LeaseDenialReason | None = None
    blocking_id: str | None = None
    if (
        request.requester is not ContinuationRequester.OPENAI_SUPERVISOR
        or not _request_authorized
    ):
        reason = LeaseDenialReason.UNAUTHORIZED_REQUESTER
    elif request.continuation_state_id != state.continuation_state_id:
        reason = LeaseDenialReason.STALE_CONTINUATION_STATE
    elif (
        request.task_id != state.task_id
        or request.governance_id != state.governance_id
        or request.continuation_policy_id != state.continuation_policy_id
    ):
        reason = LeaseDenialReason.STALE_GOVERNANCE
    elif request.orchestration_state_id != state.orchestration_state_id:
        reason = LeaseDenialReason.STALE_ORCHESTRATION_STATE
    elif (
        request.runtime_session_id != state.runtime_session_id
        or request.runtime_state_id != state.runtime_state_id
        or live_runtime_snapshot.session_id != state.runtime_session_id
        or live_runtime_snapshot.state_id != state.runtime_state_id
    ):
        reason = LeaseDenialReason.STALE_RUNTIME_STATE
    elif state.has_pending_grant:
        reason = LeaseDenialReason.PENDING_LEASE_APPLICATION
    elif (
        progress.task_id != state.task_id
        or progress.governance_id != state.governance_id
        or progress.contract.contract_id != state.progress_contract_id
        or progress.progress_id != state.last_progress_id
        or progress.current_orchestration_state_id != state.orchestration_state_id
        or request.progress_id != progress.progress_id
    ):
        reason = LeaseDenialReason.STALE_PROGRESS
    elif progress.task_complete:
        reason = LeaseDenialReason.TASK_ALREADY_COMPLETE
    elif blocking_governance_violation_id is not None:
        reason = LeaseDenialReason.BLOCKING_GOVERNANCE_VIOLATION
        blocking_id = blocking_governance_violation_id
    elif state.leases_granted >= policy.max_leases:
        reason = LeaseDenialReason.LEASE_CEILING_REACHED
    elif state.lease_requests >= policy.max_lease_requests:
        reason = LeaseDenialReason.LEASE_REQUEST_LIMIT
    elif request.lease_index != state.leases_granted + 1:
        reason = LeaseDenialReason.LEASE_INDEX_MISMATCH
    elif not state.cumulative_granted.is_within(policy.continuation_capacity):
        reason = LeaseDenialReason.LEASE_CEILING_REACHED
    elif cycle_evidence is not None and (
        live_cycle_evidence is None
        or cycle_evidence.cycle_evidence_id
        != live_cycle_evidence.cycle_evidence_id
    ):
        reason = LeaseDenialReason.STALE_RUNTIME_STATE

    strategy_admitted = False
    if reason is None and request.strategy_change_id is not None:
        if (
            strategy_change is None
            or request.strategy_change_id != strategy_change.strategy_change_id
            or strategy_change.task_id != state.task_id
            or strategy_change.governance_id != state.governance_id
            or strategy_change.orchestration_state_id
            != state.orchestration_state_id
        ):
            reason = LeaseDenialReason.STRATEGY_CHANGE_NOT_MATERIAL
        elif (
            state.current_strategy_material_id is None
            or strategy_change.prior_strategy_material_id
            != state.current_strategy_material_id
        ):
            reason = LeaseDenialReason.STRATEGY_CHANGE_NOT_MATERIAL
        elif strategy_change.cycle_evidence_id != (
            None
            if live_cycle_evidence is None
            else live_cycle_evidence.cycle_evidence_id
        ):
            reason = LeaseDenialReason.STRATEGY_CHANGE_CYCLE_EQUIVALENT
        elif strategy_change.status is StrategyChangeStatus.REJECTED:
            reason = (
                LeaseDenialReason.STRATEGY_CHANGE_CYCLE_EQUIVALENT
                if strategy_change.reason is StrategyChangeReason.CYCLE_EQUIVALENT
                else LeaseDenialReason.STRATEGY_CHANGE_NOT_MATERIAL
            )
        else:
            strategy_admitted = True
    elif reason is None and strategy_change is not None:
        # A receipt not bound into the request cannot confer authority.
        reason = LeaseDenialReason.STRATEGY_CHANGE_NOT_MATERIAL

    progress_admitted = (
        progress.classification is ProgressClassification.MEASURABLE_PROGRESS
        and progress.progress_id != state.last_consumed_progress_id
    )
    if reason is None and live_cycle_evidence is not None and not strategy_admitted:
        reason = LeaseDenialReason.TERMINAL_CYCLE
    elif reason is None and not progress_admitted and not strategy_admitted:
        reason = LeaseDenialReason.NO_MEASURABLE_PROGRESS
    elif (
        reason is None
        and strategy_admitted
        and state.strategy_recoveries >= policy.max_strategy_recoveries
    ):
        reason = LeaseDenialReason.STRATEGY_RECOVERY_EXHAUSTED

    if reason is None and request.requested_resources.is_zero:
        reason = LeaseDenialReason.EMPTY_RESOURCE_VECTOR
    elif reason is None and request.requested_resources.mutation_delta != 0:
        reason = LeaseDenialReason.UNSUPPORTED_RESOURCE
    elif reason is None:
        scheduled = policy.lease_schedule[state.leases_granted]
        if not request.requested_resources.is_within(scheduled):
            reason = LeaseDenialReason.AMOUNT_EXCEEDS_SCHEDULE

    next_cumulative: BudgetVector | None = None
    if reason is None:
        try:
            next_cumulative = state.cumulative_granted.add_checked(
                request.requested_resources
            )
        except OverflowError:
            reason = LeaseDenialReason.AMOUNT_EXCEEDS_CEILING
        else:
            if not next_cumulative.is_within(policy.continuation_capacity):
                reason = LeaseDenialReason.AMOUNT_EXCEEDS_CEILING

    if reason is not None:
        terminal_ceiling_without_request_slot = (
            reason is LeaseDenialReason.LEASE_CEILING_REACHED
            and state.leases_granted >= policy.max_leases
            and state.lease_requests >= policy.max_lease_requests
        )
        denied = _deny_continuation(
            state,
            request,
            progress,
            reason,
            policy=policy,
            blocking_evidence_id=blocking_id,
            record_decision=(
                reason is not LeaseDenialReason.UNAUTHORIZED_REQUESTER
                and not terminal_ceiling_without_request_slot
                and state.lease_requests < policy.max_lease_requests
            ),
        )
        if not terminal_ceiling_without_request_slot:
            return denied
        if state.progress_state is ProgressState.LEASE_EXHAUSTED:
            return denied
        return _ContinuationEvaluationResult(
            replace(
                state,
                _decision_lineage_capability=None,
                progress_state=ProgressState.LEASE_EXHAUSTED,
            ),
            denied.receipt,
        )

    assert next_cumulative is not None
    decision_tick = state.continuation_logical_tick + 1
    grant = LeaseGrantReceipt(
        task_id=state.task_id,
        governance_id=state.governance_id,
        governance_receipt_id=state.governance_receipt_id,
        continuation_policy_id=state.continuation_policy_id,
        continuation_policy_receipt_id=state.continuation_policy_receipt_id,
        continuation_request_id=request.continuation_request_id,
        prior_continuation_state_id=state.continuation_state_id,
        orchestration_state_id=state.orchestration_state_id,
        runtime_session_id=state.runtime_session_id,
        prior_runtime_state_id=state.runtime_state_id,
        progress_id=progress.progress_id,
        strategy_change_id=(
            strategy_change.strategy_change_id if strategy_admitted else None
        ),
        lease_index=request.lease_index,
        granted_resources=request.requested_resources,
        cumulative_granted=next_cumulative,
        total_ceiling=policy.total_ceiling,
        decision_logical_tick=decision_tick,
    )
    used_strategy_recovery = strategy_admitted and (
        live_cycle_evidence is not None or not progress_admitted
    )
    next_state = replace(
        state,
        _decision_lineage_capability=None,
        lease_requests=state.lease_requests + 1,
        leases_granted=state.leases_granted + 1,
        cumulative_granted=next_cumulative,
        continuation_logical_tick=decision_tick,
        decision_aggregate_id=_advance_decision_aggregate(
            state.decision_aggregate_id, grant.receipt_id, state.lease_requests
        ),
        decision_receipt_ids=(*state.decision_receipt_ids, grant.receipt_id),
        strategy_recoveries=(
            state.strategy_recoveries + (1 if used_strategy_recovery else 0)
        ),
        current_strategy_material_id=(
            strategy_change.proposed_strategy_material_id
            if strategy_admitted and strategy_change is not None
            else state.current_strategy_material_id
        ),
        last_progress_id=progress.progress_id,
        last_consumed_progress_id=(
            progress.progress_id
            if progress_admitted
            else state.last_consumed_progress_id
        ),
        last_consumed_external_progress_endpoint_id=(
            progress.current_external_endpoint_id
            if progress_admitted
            else state.last_consumed_external_progress_endpoint_id
        ),
        last_progress_classification=progress.classification,
        last_decision="granted",
        last_denial_reason=None,
        progress_state=(
            ProgressState.STRATEGY_CHANGED
            if used_strategy_recovery
            else ProgressState.PROGRESSING
        ),
        pending_grant_id=grant.lease_grant_id,
        pending_grant_receipt_id=grant.receipt_id,
    )
    return _ContinuationEvaluationResult(next_state, grant)


def evaluate_continuation(
    state: ContinuationState,
    request: ContinuationRequest,
    *,
    runtime_session: RustRuntimeSession,
    policy: ContinuationPolicy,
    policy_receipt: ContinuationPolicyReceipt,
    progress: ProgressRecord,
    strategy_change: StrategyChangeReceipt | None = None,
    cycle_evidence: CycleEvidence | None = None,
    blocking_governance_violation_id: str | None = None,
    benchmark_observation: Any | None = None,
) -> ContinuationDecision:
    """Return one deterministic decision under exact native request authority."""

    if type(request) is not ContinuationRequest:
        raise TypeError("request must be an exact ContinuationRequest")
    request_authority = request._native_request_authority()
    if request_authority is None:
        unsigned = _evaluate_continuation(
            state,
            request,
            runtime_session=runtime_session,
            policy=policy,
            policy_receipt=policy_receipt,
            progress=progress,
            strategy_change=strategy_change,
            cycle_evidence=cycle_evidence,
            blocking_governance_violation_id=blocking_governance_violation_id,
            benchmark_observation=benchmark_observation,
            _request_authorized=False,
        )
        if unsigned.granted or unsigned.next_state is not state:
            raise AssertionError("unauthorized requests must be state-neutral denials")
        return unsigned._finalize(unsigned.next_state, unsigned.receipt)

    decision = runtime_session._evaluate_continuation_request(
        request_authority,
        state,
        request,
        policy,
        policy_receipt,
        progress,
        strategy_change,
        cycle_evidence,
        blocking_governance_violation_id,
        benchmark_observation,
    )
    if type(decision) is not ContinuationDecision:
        raise TypeError("native evaluator returned an invalid continuation decision")
    return decision


def _validate_semantic_partial_reason(
    state: ContinuationState,
    reason: ContinuationPartialReason,
    *,
    leases_remaining: int,
    strategy_recoveries_remaining: int,
) -> None:
    """Require a semantic partial reason to describe the live decision ledger."""

    if reason is ContinuationPartialReason.WATCHDOG_EXPIRED:
        return
    if reason is ContinuationPartialReason.LEASE_CEILING_EXHAUSTED:
        if state.progress_state is not ProgressState.LEASE_EXHAUSTED:
            raise ValueError("partial reason does not match continuation progress state")
        if leases_remaining != 0:
            raise ValueError("lease-ceiling partial requires exhausted lease capacity")
        return
    required_state = {
        ContinuationPartialReason.LEASE_CEILING_EXHAUSTED: (
            ProgressState.LEASE_EXHAUSTED
        ),
        ContinuationPartialReason.NO_PROGRESS: ProgressState.STALLED,
        ContinuationPartialReason.TERMINAL_CYCLE: ProgressState.CYCLE_BLOCKED,
        ContinuationPartialReason.STRATEGY_RECOVERY_EXHAUSTED: (
            ProgressState.STALLED
        ),
    }[reason]
    if state.progress_state is not required_state:
        raise ValueError("partial reason does not match continuation progress state")
    required_denials = {
        ContinuationPartialReason.LEASE_CEILING_EXHAUSTED: (
            LeaseDenialReason.LEASE_CEILING_REACHED,
        ),
        ContinuationPartialReason.NO_PROGRESS: (
            LeaseDenialReason.NO_MEASURABLE_PROGRESS,
        ),
        ContinuationPartialReason.TERMINAL_CYCLE: (
            LeaseDenialReason.TERMINAL_CYCLE,
            LeaseDenialReason.STRATEGY_CHANGE_CYCLE_EQUIVALENT,
        ),
        ContinuationPartialReason.STRATEGY_RECOVERY_EXHAUSTED: (
            LeaseDenialReason.STRATEGY_RECOVERY_EXHAUSTED,
        ),
    }[reason]
    if (
        state.last_decision != "denied"
        or state.last_denial_reason not in required_denials
    ):
        raise ValueError("partial reason does not match the actual lease denial")
    if (
        reason is ContinuationPartialReason.LEASE_CEILING_EXHAUSTED
        and leases_remaining != 0
    ):
        raise ValueError("lease-ceiling partial requires exhausted lease capacity")
    if (
        reason is ContinuationPartialReason.STRATEGY_RECOVERY_EXHAUSTED
        and strategy_recoveries_remaining != 0
    ):
        raise ValueError(
            "strategy-recovery partial requires exhausted recovery capacity"
        )


@dataclass(frozen=True, slots=True, init=False)
class ContinuationCheckpoint:
    """Structural in-process continuation lineage checkpoint.

    A canonical hash proves internal correspondence only.  It is not producer
    authentication, durable remote attestation, or authority to reconstruct a
    native runtime in another process.  Construction requires the matching
    live native session to validate the complete supplied runtime snapshot.
    """

    task_id: str
    governance_id: str
    governance_receipt_id: str
    orchestration_state_id: str
    runtime_session_id: str
    runtime_state_id: str
    continuation_policy_id: str
    continuation_policy_receipt_id: str
    progress_contract_id: str
    continuation_state_id: str
    progress_id: str | None
    strategy_material_id: str | None
    leases_used: int
    leases_remaining: int
    lease_requests: int
    leases_denied: int
    strategy_recoveries_used: int
    strategy_recoveries_remaining: int
    cumulative_granted: BudgetVector
    remaining_capacity: BudgetVector
    compact_evidence_receipt_id: str | None
    relevant_receipt_id: str | None
    orchestration_logical_tick: int
    runtime_logical_tick: int
    continuation_logical_tick: int
    checkpoint_status: ProgressState
    partial_reason: ContinuationPartialReason | None

    def __init__(
        self,
        *,
        state: ContinuationState,
        runtime_session: RustRuntimeSession,
        policy: ContinuationPolicy,
        orchestration_state: OrchestrationState,
        runtime_snapshot: RuntimeSnapshot,
        progress: ProgressRecord | None = None,
        strategy: StrategyMaterialization | None = None,
        compact_evidence_receipt_id: str | None = None,
        relevant_receipt_id: str | None = None,
        checkpoint_status: ProgressState | None = None,
        partial_reason: ContinuationPartialReason | None = None,
    ) -> None:
        if type(state) is not ContinuationState:
            raise TypeError("state must be an exact ContinuationState")
        if type(runtime_session) is not RustRuntimeSession:
            raise TypeError("runtime_session must be an exact RustRuntimeSession")
        state._require_policy(policy)
        if type(orchestration_state) is not OrchestrationState:
            raise TypeError("orchestration_state must be exact OrchestrationState")
        if type(runtime_snapshot) is not RuntimeSnapshot:
            raise TypeError("runtime_snapshot must be an exact RuntimeSnapshot")
        runtime_session._validate_continuation_checkpoint_snapshot(
            state._native_lineage_seal(),
            state,
            runtime_snapshot,
        )
        if orchestration_state.state_id != state.orchestration_state_id:
            raise ValueError("checkpoint orchestration state is stale")
        if (
            runtime_snapshot.session_id != state.runtime_session_id
            or runtime_snapshot.state_id != state.runtime_state_id
        ):
            raise ValueError("checkpoint runtime state is stale")
        native_continuation = runtime_snapshot.continuation
        if native_continuation is None:
            raise ValueError("checkpoint requires an opt-in native runtime")
        if (
            native_continuation.task_id != state.task_id
            or native_continuation.governance_id != state.governance_id
            or native_continuation.governance_receipt_id
            != state.governance_receipt_id
            or native_continuation.continuation_policy_id
            != state.continuation_policy_id
            or native_continuation.continuation_policy_receipt_id
            != state.continuation_policy_receipt_id
            or native_continuation.progress_contract_id
            != state.progress_contract_id
            or native_continuation.leases_applied != state.leases_granted
            or native_continuation.cumulative_granted.canonical_record()
            != state.cumulative_granted.canonical_record()
        ):
            raise ValueError("checkpoint native continuation ledger is stale")
        expected_limits = policy.initial_budget.add_checked(
            state.cumulative_granted
        )
        if (
            runtime_snapshot.limits.max_requests != expected_limits.request_delta
            or runtime_snapshot.limits.max_executions
            != expected_limits.execution_delta
            or runtime_snapshot.limits.max_retries != expected_limits.retry_delta
            or runtime_snapshot.limits.max_history != expected_limits.history_delta
        ):
            raise ValueError("checkpoint native continuation limits are stale")
        if progress is not None:
            if type(progress) is not ProgressRecord:
                raise TypeError("progress must be an exact ProgressRecord")
            if (
                progress.task_id != state.task_id
                or progress.governance_id != state.governance_id
                or progress.contract.contract_id != state.progress_contract_id
                or progress.current_orchestration_state_id
                != state.orchestration_state_id
                or progress.progress_id != state.last_progress_id
            ):
                raise ValueError("checkpoint progress identity is stale")
        if strategy is not None:
            if type(strategy) is not StrategyMaterialization:
                raise TypeError("strategy must be exact StrategyMaterialization")
            if strategy.strategy_material_id != state.current_strategy_material_id:
                raise ValueError("checkpoint strategy identity is stale")
        for name, value in (
            ("compact evidence receipt id", compact_evidence_receipt_id),
            ("relevant receipt id", relevant_receipt_id),
        ):
            if value is not None:
                require_fingerprint(name, value)
        status = state.progress_state if checkpoint_status is None else checkpoint_status
        _enum("checkpoint status", status, ProgressState)
        if status is not state.progress_state:
            raise ValueError("checkpoint status does not match live continuation state")
        if partial_reason is not None:
            _enum("checkpoint partial reason", partial_reason, ContinuationPartialReason)
        if status is ProgressState.COMPLETE and partial_reason is not None:
            raise ValueError("complete checkpoints cannot carry a partial reason")
        effective_leases_remaining = min(
            policy.max_lease_requests - state.lease_requests,
            state.leases_remaining(policy),
        )
        strategy_recoveries_remaining = (
            policy.max_strategy_recoveries - state.strategy_recoveries
        )
        if partial_reason is not None:
            _validate_semantic_partial_reason(
                state,
                partial_reason,
                leases_remaining=effective_leases_remaining,
                strategy_recoveries_remaining=strategy_recoveries_remaining,
            )

        values: dict[str, Any] = {
            "task_id": state.task_id,
            "governance_id": state.governance_id,
            "governance_receipt_id": state.governance_receipt_id,
            "orchestration_state_id": state.orchestration_state_id,
            "runtime_session_id": state.runtime_session_id,
            "runtime_state_id": state.runtime_state_id,
            "continuation_policy_id": state.continuation_policy_id,
            "continuation_policy_receipt_id": (
                state.continuation_policy_receipt_id
            ),
            "progress_contract_id": state.progress_contract_id,
            "continuation_state_id": state.continuation_state_id,
            "progress_id": (
                state.last_progress_id if progress is None else progress.progress_id
            ),
            "strategy_material_id": (
                state.current_strategy_material_id
                if strategy is None
                else strategy.strategy_material_id
            ),
            "leases_used": state.leases_granted,
            "leases_remaining": effective_leases_remaining,
            "lease_requests": state.lease_requests,
            "leases_denied": state.leases_denied,
            "strategy_recoveries_used": state.strategy_recoveries,
            "strategy_recoveries_remaining": strategy_recoveries_remaining,
            "cumulative_granted": state.cumulative_granted,
            "remaining_capacity": state.remaining_capacity(policy),
            "compact_evidence_receipt_id": compact_evidence_receipt_id,
            "relevant_receipt_id": relevant_receipt_id,
            "orchestration_logical_tick": orchestration_state.logical_tick,
            "runtime_logical_tick": runtime_snapshot.logical_tick,
            "continuation_logical_tick": state.continuation_logical_tick,
            "checkpoint_status": status,
            "partial_reason": partial_reason,
        }
        for name, value in values.items():
            object.__setattr__(self, name, value)

    @property
    def checkpoint_id(self) -> str:
        return domain_fingerprint(CHECKPOINT_ID_DOMAIN, self.canonical_record())

    def canonical_record(self) -> dict[str, Any]:
        return {
            "checkpoint_status": self.checkpoint_status.value,
            "compact_evidence_receipt_id": self.compact_evidence_receipt_id,
            "continuation_logical_tick": self.continuation_logical_tick,
            "continuation_policy_id": self.continuation_policy_id,
            "continuation_policy_receipt_id": self.continuation_policy_receipt_id,
            "progress_contract_id": self.progress_contract_id,
            "continuation_state_id": self.continuation_state_id,
            "cumulative_granted": self.cumulative_granted.canonical_record(),
            "governance_id": self.governance_id,
            "governance_receipt_id": self.governance_receipt_id,
            "lease_requests": self.lease_requests,
            "leases_denied": self.leases_denied,
            "leases_remaining": self.leases_remaining,
            "leases_used": self.leases_used,
            "strategy_recoveries_remaining": self.strategy_recoveries_remaining,
            "strategy_recoveries_used": self.strategy_recoveries_used,
            "orchestration_logical_tick": self.orchestration_logical_tick,
            "orchestration_state_id": self.orchestration_state_id,
            "partial_reason": (
                None if self.partial_reason is None else self.partial_reason.value
            ),
            "progress_id": self.progress_id,
            "protocol_version": CHECKPOINT_PROTOCOL_VERSION,
            "relevant_receipt_id": self.relevant_receipt_id,
            "remaining_capacity": self.remaining_capacity.canonical_record(),
            "runtime_logical_tick": self.runtime_logical_tick,
            "runtime_session_id": self.runtime_session_id,
            "runtime_state_id": self.runtime_state_id,
            "strategy_material_id": self.strategy_material_id,
            "task_id": self.task_id,
            "trust_scope": "structural-in-process-lineage-only",
        }


def resume_continuation_checkpoint(
    checkpoint: ContinuationCheckpoint,
    *,
    live_state: ContinuationState,
    runtime_session: RustRuntimeSession,
    policy: ContinuationPolicy,
    orchestration_state: OrchestrationState,
    runtime_snapshot: RuntimeSnapshot,
    progress: ProgressRecord | None = None,
    strategy: StrategyMaterialization | None = None,
) -> ContinuationState:
    """Validate an exact live in-process context and return that live state."""

    if type(checkpoint) is not ContinuationCheckpoint:
        raise TypeError("checkpoint must be an exact ContinuationCheckpoint")
    if type(live_state) is not ContinuationState:
        raise TypeError("live_state must be an exact ContinuationState")
    live_state._require_policy(policy)
    expected = ContinuationCheckpoint(
        state=live_state,
        runtime_session=runtime_session,
        policy=policy,
        orchestration_state=orchestration_state,
        runtime_snapshot=runtime_snapshot,
        progress=progress,
        strategy=strategy,
        compact_evidence_receipt_id=checkpoint.compact_evidence_receipt_id,
        relevant_receipt_id=checkpoint.relevant_receipt_id,
        checkpoint_status=checkpoint.checkpoint_status,
        partial_reason=checkpoint.partial_reason,
    )
    if expected.canonical_record() != checkpoint.canonical_record():
        raise ValueError("continuation checkpoint does not match live lineage")
    if expected.checkpoint_id != checkpoint.checkpoint_id:
        raise ValueError("continuation checkpoint identity mismatch")
    return live_state


def _initial_progress_aggregate() -> str:
    return domain_fingerprint(
        CONTINUATION_EVIDENCE_PROGRESS_AGGREGATE_DOMAIN,
        {"item_type": "seed", "protocol_version": CONTINUATION_EVIDENCE_VERSION},
    )


def _advance_progress_aggregate(
    prior: str, progress_id: str, ordinal: int
) -> str:
    require_fingerprint("prior continuation progress aggregate", prior)
    require_fingerprint("continuation progress id", progress_id)
    _u64("continuation progress ordinal", ordinal)
    return domain_fingerprint(
        CONTINUATION_EVIDENCE_PROGRESS_AGGREGATE_DOMAIN,
        {
            "item_type": "progress",
            "ordinal": ordinal,
            "prior": prior,
            "progress_id": progress_id,
        },
    )


def _progress_aggregate(records: tuple[ProgressRecord, ...]) -> str:
    prior = _initial_progress_aggregate()
    for ordinal, record in enumerate(records):
        prior = _advance_progress_aggregate(prior, record.progress_id, ordinal)
    return prior


@dataclass(frozen=True, slots=True, init=False)
class ContinuationEvidenceReceipt:
    task_id: str
    governance_id: str
    continuation_policy_id: str
    progress_contract_id: str
    continuation_state_id: str
    progress_events: int
    leases_requested: int
    leases_granted: int
    leases_denied: int
    final_lease_index: int
    continuation_status: ProgressState
    progress_aggregate_id: str
    decision_aggregate_id: str
    final_progress_id: str | None
    final_decision_receipt_id: str | None
    compact_execution_evidence_receipt_id: str | None

    def __init__(
        self,
        *,
        state: ContinuationState,
        policy: ContinuationPolicy,
        progress_records: Iterable[ProgressRecord],
        compact_execution_evidence_receipt_id: str | None = None,
    ) -> None:
        if type(state) is not ContinuationState:
            raise TypeError("state must be an exact ContinuationState")
        state._require_policy(policy)
        records = materialize_bounded_iterable(
            "continuation progress records",
            progress_records,
            limit=policy.max_lease_requests + 1,
        )
        if any(type(item) is not ProgressRecord for item in records):
            raise TypeError("progress_records must contain exact ProgressRecord values")
        for record in records:
            if (
                record.task_id != state.task_id
                or record.governance_id != state.governance_id
                or record.contract.contract_id != state.progress_contract_id
            ):
                raise ValueError("progress evidence authority binding mismatch")
        if state.last_progress_id is None:
            if records:
                raise ValueError("progress evidence contradicts an empty live ledger")
        elif not records or records[-1].progress_id != state.last_progress_id:
            raise ValueError("progress evidence endpoint does not match live ledger")
        for prior, current in zip(records, records[1:], strict=False):
            if (
                prior.current_orchestration_state_id
                != current.prior_orchestration_state_id
            ):
                raise ValueError("progress evidence is not a contiguous ordered trace")
        if (
            records
            and records[-1].current_orchestration_state_id
            != state.orchestration_state_id
        ):
            raise ValueError("progress evidence endpoint orchestration is stale")
        if len(records) != state.progress_event_count:
            raise ValueError("progress evidence does not contain the full live history")
        progress_aggregate_id = _progress_aggregate(records)
        if progress_aggregate_id != state.progress_aggregate_id:
            raise ValueError("progress evidence aggregate does not match live history")
        if compact_execution_evidence_receipt_id is not None:
            require_fingerprint(
                "compact execution evidence receipt id",
                compact_execution_evidence_receipt_id,
            )
        values = {
            "task_id": state.task_id,
            "governance_id": state.governance_id,
            "continuation_policy_id": state.continuation_policy_id,
            "progress_contract_id": state.progress_contract_id,
            "continuation_state_id": state.continuation_state_id,
            "progress_events": len(records),
            "leases_requested": state.lease_requests,
            "leases_granted": state.leases_granted,
            "leases_denied": state.leases_denied,
            "final_lease_index": state.leases_granted,
            "continuation_status": state.progress_state,
            "progress_aggregate_id": progress_aggregate_id,
            "decision_aggregate_id": state.decision_aggregate_id,
            "final_progress_id": (
                None if not records else records[-1].progress_id
            ),
            "final_decision_receipt_id": (
                None
                if not state.decision_receipt_ids
                else state.decision_receipt_ids[-1]
            ),
            "compact_execution_evidence_receipt_id": (
                compact_execution_evidence_receipt_id
            ),
        }
        for name, value in values.items():
            object.__setattr__(self, name, value)
        encoded = canonical_json(self.canonical_record()).encode("utf-8")
        if len(encoded) > MAX_CONTINUATION_EVIDENCE_BYTES:
            raise ValueError("continuation evidence exceeds its compact byte bound")

    def _body(self) -> dict[str, Any]:
        return {
            "authority_layer": "evidence",
            "compact_execution_evidence_receipt_id": (
                self.compact_execution_evidence_receipt_id
            ),
            "continuation_policy_id": self.continuation_policy_id,
            "progress_contract_id": self.progress_contract_id,
            "continuation_state_id": self.continuation_state_id,
            "continuation_status": self.continuation_status.value,
            "decision_aggregate_id": self.decision_aggregate_id,
            "final_decision_receipt_id": self.final_decision_receipt_id,
            "final_lease_index": self.final_lease_index,
            "final_progress_id": self.final_progress_id,
            "governance_id": self.governance_id,
            "leases_denied": self.leases_denied,
            "leases_granted": self.leases_granted,
            "leases_requested": self.leases_requested,
            "progress_aggregate_id": self.progress_aggregate_id,
            "progress_events": self.progress_events,
            "protocol_version": CONTINUATION_EVIDENCE_VERSION,
            "status": "reported",
            "task_id": self.task_id,
        }

    @property
    def receipt_id(self) -> str:
        return self.canonical_record()["receipt_id"]

    def canonical_record(self) -> dict[str, Any]:
        return _with_receipt_id(CONTINUATION_EVIDENCE_RECEIPT_DOMAIN, self._body())


@dataclass(frozen=True, slots=True)
class WatchdogObservation:
    task_id: str
    governance_id: str
    orchestration_state_id: str
    runtime_state_id: str
    continuation_state_id: str
    elapsed_milliseconds: int
    lease_exhausted: bool = False

    def __post_init__(self) -> None:
        for name, value in (
            ("watchdog task id", self.task_id),
            ("watchdog governance id", self.governance_id),
            ("watchdog orchestration id", self.orchestration_state_id),
            ("watchdog runtime id", self.runtime_state_id),
            ("watchdog continuation state id", self.continuation_state_id),
        ):
            require_fingerprint(name, value)
        _u64("watchdog elapsed milliseconds", self.elapsed_milliseconds)
        _bool("watchdog lease_exhausted", self.lease_exhausted)

    @property
    def observation_id(self) -> str:
        # Wall-clock magnitude is observational and intentionally excluded
        # from correctness identity.
        return domain_fingerprint(
            WATCHDOG_OBSERVATION_ID_DOMAIN,
            {
                "continuation_state_id": self.continuation_state_id,
                "governance_id": self.governance_id,
                "lease_exhausted": self.lease_exhausted,
                "orchestration_state_id": self.orchestration_state_id,
                "reason": ContinuationPartialReason.WATCHDOG_EXPIRED.value,
                "runtime_state_id": self.runtime_state_id,
                "task_id": self.task_id,
            },
        )

    def canonical_record(self) -> dict[str, Any]:
        return {
            "continuation_state_id": self.continuation_state_id,
            "correctness_authority": False,
            "elapsed_milliseconds": self.elapsed_milliseconds,
            "governance_id": self.governance_id,
            "lease_exhausted": self.lease_exhausted,
            "observation_id": self.observation_id,
            "orchestration_state_id": self.orchestration_state_id,
            "protocol_version": WATCHDOG_OBSERVATION_VERSION,
            "reason": ContinuationPartialReason.WATCHDOG_EXPIRED.value,
            "runtime_state_id": self.runtime_state_id,
            "task_complete": False,
            "task_id": self.task_id,
        }


@dataclass(frozen=True, slots=True, init=False)
class ContinuationPartialReceipt:
    task_id: str
    governance_id: str
    orchestration_state_id: str
    runtime_state_id: str
    continuation_state_id: str
    progress_id: str | None
    decision_aggregate_id: str
    checkpoint_id: str
    compact_evidence_receipt_id: str | None
    execution_receipt_id: str | None
    watchdog_observation_id: str | None
    reason: ContinuationPartialReason

    def __init__(
        self,
        *,
        state: ContinuationState,
        checkpoint: ContinuationCheckpoint,
        reason: ContinuationPartialReason,
        compact_evidence_receipt_id: str | None = None,
        execution_receipt_id: str | None = None,
        watchdog_observation: WatchdogObservation | None = None,
    ) -> None:
        if type(state) is not ContinuationState:
            raise TypeError("state must be an exact ContinuationState")
        if type(checkpoint) is not ContinuationCheckpoint:
            raise TypeError("checkpoint must be an exact ContinuationCheckpoint")
        _enum("continuation partial reason", reason, ContinuationPartialReason)
        if checkpoint.continuation_state_id != state.continuation_state_id:
            raise ValueError("partial checkpoint does not bind continuation state")
        if checkpoint.partial_reason is not reason:
            raise ValueError("partial checkpoint reason does not match finalization")
        if state.progress_state is ProgressState.COMPLETE:
            raise ValueError("a complete task cannot be finalized as partial")
        _validate_semantic_partial_reason(
            state,
            reason=reason,
            leases_remaining=checkpoint.leases_remaining,
            strategy_recoveries_remaining=(
                checkpoint.strategy_recoveries_remaining
            ),
        )
        for name, supplied, bound in (
            (
                "partial compact evidence receipt id",
                compact_evidence_receipt_id,
                checkpoint.compact_evidence_receipt_id,
            ),
            (
                "partial execution receipt id",
                execution_receipt_id,
                checkpoint.relevant_receipt_id,
            ),
        ):
            if supplied is not None:
                require_fingerprint(name, supplied)
            if supplied is not None and supplied != bound:
                raise ValueError(f"{name} does not match checkpoint evidence")
        bound_compact_evidence_id = checkpoint.compact_evidence_receipt_id
        bound_execution_receipt_id = checkpoint.relevant_receipt_id
        if reason is ContinuationPartialReason.WATCHDOG_EXPIRED:
            if type(watchdog_observation) is not WatchdogObservation:
                raise ValueError("watchdog expiry requires a watchdog observation")
            if (
                watchdog_observation.continuation_state_id
                != state.continuation_state_id
                or watchdog_observation.task_id != state.task_id
                or watchdog_observation.governance_id != state.governance_id
                or watchdog_observation.orchestration_state_id
                != state.orchestration_state_id
                or watchdog_observation.runtime_state_id
                != state.runtime_state_id
            ):
                raise ValueError("watchdog observation does not bind partial state")
            if watchdog_observation.lease_exhausted != (
                checkpoint.leases_remaining == 0
            ):
                raise ValueError(
                    "watchdog lease exhaustion must match effective checkpoint capacity"
                )
        elif watchdog_observation is not None:
            raise ValueError("only watchdog expiry may bind a watchdog observation")
        values = {
            "task_id": state.task_id,
            "governance_id": state.governance_id,
            "orchestration_state_id": state.orchestration_state_id,
            "runtime_state_id": state.runtime_state_id,
            "continuation_state_id": state.continuation_state_id,
            "progress_id": state.last_progress_id,
            "decision_aggregate_id": state.decision_aggregate_id,
            "checkpoint_id": checkpoint.checkpoint_id,
            "compact_evidence_receipt_id": bound_compact_evidence_id,
            "execution_receipt_id": bound_execution_receipt_id,
            "watchdog_observation_id": (
                None
                if watchdog_observation is None
                else watchdog_observation.observation_id
            ),
            "reason": reason,
        }
        for name, value in values.items():
            object.__setattr__(self, name, value)

    @property
    def partial_id(self) -> str:
        return domain_fingerprint(
            PARTIAL_CONTINUATION_ID_DOMAIN, self.canonical_record()
        )

    def canonical_record(self) -> dict[str, Any]:
        return {
            "authority_layer": "governance",
            "checkpoint_id": self.checkpoint_id,
            "compact_evidence_receipt_id": self.compact_evidence_receipt_id,
            "continuation_state_id": self.continuation_state_id,
            "decision_aggregate_id": self.decision_aggregate_id,
            "execution_receipt_id": self.execution_receipt_id,
            "governance_id": self.governance_id,
            "orchestration_state_id": self.orchestration_state_id,
            "progress_id": self.progress_id,
            "protocol_version": PARTIAL_CONTINUATION_VERSION,
            "reason": self.reason.value,
            "runtime_state_id": self.runtime_state_id,
            "status": "partial",
            "task_complete": False,
            "task_id": self.task_id,
            "watchdog_observation_id": self.watchdog_observation_id,
        }


# Capture the authoritative evaluator/observer/application committer once in
# native storage during trusted module initialization, then remove the one-shot
# bootstrap entrypoint.
# Later continuation-session creation never resolves mutable module globals.
from . import _runtime as _native_runtime

_native_runtime._register_continuation_engine(
    _evaluate_continuation,
    _observe_continuation_context,
    _commit_lease_application,
    ContinuationState,
    ContinuationRequest,
    RuntimeSnapshot,
)
delattr(_native_runtime, "_register_continuation_engine")
del _native_runtime
