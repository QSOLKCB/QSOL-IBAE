"""Deterministic Python orchestration reference semantics for IBAE v0.2."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any

from ._records import (
    CanonicalValue,
    materialize_iterable,
    require_fingerprint,
    require_invariant_id,
    require_nonnegative_int,
    require_positive_int,
    require_symbol,
    require_text,
)
from .canonical import domain_fingerprint
from .epistemic import EpistemicState
from .obligations import (
    Obligation,
    ObligationReadiness,
    ObligationRegistry,
)

AGENT_PROTOCOL = "IBAE-AGENT-PROTOCOL-V1"
LOGICAL_CLOCK_PROFILE = "IBAE-LOGICAL-CLOCK-V1"

CAPABILITY_ID_DOMAIN = "ibae.capability-id.v1"
STRATEGY_ID_DOMAIN = "ibae.strategy-id.v1"
PROPOSAL_ID_DOMAIN = "ibae.proposal-id.v1"
BATCH_ID_DOMAIN = "ibae.proposal-batch-id.v1"
ACTION_ID_DOMAIN = "ibae.action-id.v1"
STATE_ID_DOMAIN = "ibae.orchestration-state-id.v1"
EVENT_ID_DOMAIN = "ibae.orchestration-event-id.v1"
RECEIPT_ID_DOMAIN = "ibae.admission-receipt-id.v1"


class ReplaySafety(str, Enum):
    CACHEABLE_READ = "cacheable_read"
    PROVEN_REPLAY_SAFE = "proven_replay_safe"
    OCCURRENCE_SENSITIVE = "occurrence_sensitive"


class AuthorityLayer(str, Enum):
    GOVERNANCE = "governance"
    ORCHESTRATION = "orchestration"
    EXECUTION = "execution"
    BENCHMARK = "benchmark"


class DecisionStatus(str, Enum):
    ADMITTED = "admitted"
    DEDUPLICATED = "deduplicated"
    REJECTED = "rejected"


class BatchStatus(str, Enum):
    PROCESSED = "processed"
    REJECTED = "rejected"


class RejectionReason(str, Enum):
    BATCH_LIMIT_EXCEEDED = "IBAE-REJECT-BATCH-LIMIT-EXCEEDED"
    UNKNOWN_CAPABILITY = "IBAE-REJECT-UNKNOWN-CAPABILITY"
    CAPABILITY_UNAVAILABLE = "IBAE-REJECT-CAPABILITY-UNAVAILABLE"
    UNKNOWN_OBLIGATION = "IBAE-REJECT-UNKNOWN-OBLIGATION"
    OBLIGATION_SATISFIED = "IBAE-REJECT-OBLIGATION-SATISFIED"
    OBLIGATION_BLOCKED = "IBAE-REJECT-OBLIGATION-BLOCKED"
    DEPENDENCY_UNSATISFIED = "IBAE-REJECT-DEPENDENCY-UNSATISFIED"
    UNKNOWN_STATE = "IBAE-REJECT-UNKNOWN-STATE"
    OCCURRENCE_KEY_REQUIRED = "IBAE-REJECT-OCCURRENCE-KEY-REQUIRED"
    UNEXPECTED_OCCURRENCE_KEY = "IBAE-REJECT-UNEXPECTED-OCCURRENCE-KEY"
    DUPLICATE_OCCURRENCE = "IBAE-REJECT-DUPLICATE-OCCURRENCE"


class RecoveryAction(str, Enum):
    SPLIT_BATCH = "IBAE-RECOVERY-SPLIT-BATCH"
    CHOOSE_AVAILABLE_CAPABILITY = "IBAE-RECOVERY-CHOOSE-AVAILABLE-CAPABILITY"
    CHOOSE_KNOWN_OBLIGATION = "IBAE-RECOVERY-CHOOSE-KNOWN-OBLIGATION"
    TARGET_UNSATISFIED_OBLIGATION = "IBAE-RECOVERY-TARGET-UNSATISFIED-OBLIGATION"
    RESOLVE_BLOCKER = "IBAE-RECOVERY-RESOLVE-BLOCKER"
    SATISFY_DEPENDENCIES = "IBAE-RECOVERY-SATISFY-DEPENDENCIES"
    OBSERVE_REQUIRED_STATE = "IBAE-RECOVERY-OBSERVE-REQUIRED-STATE"
    ADD_OCCURRENCE_KEY = "IBAE-RECOVERY-ADD-OCCURRENCE-KEY"
    REMOVE_OCCURRENCE_KEY = "IBAE-RECOVERY-REMOVE-OCCURRENCE-KEY"
    USE_DISTINCT_OCCURRENCE_KEY = "IBAE-RECOVERY-USE-DISTINCT-OCCURRENCE-KEY"


_REJECTION_INVARIANTS: dict[RejectionReason, tuple[str, ...]] = {
    RejectionReason.BATCH_LIMIT_EXCEEDED: ("IBAE-BND-008", "IBAE-ORCH-006"),
    RejectionReason.UNKNOWN_CAPABILITY: ("IBAE-GOV-006", "IBAE-ORCH-001"),
    RejectionReason.CAPABILITY_UNAVAILABLE: ("IBAE-ORCH-001",),
    RejectionReason.UNKNOWN_OBLIGATION: ("IBAE-ORCH-005",),
    RejectionReason.OBLIGATION_SATISFIED: (
        "IBAE-ORCH-005",
        "IBAE-PROG-003",
    ),
    RejectionReason.OBLIGATION_BLOCKED: (
        "IBAE-ORCH-005",
        "IBAE-PROG-003",
    ),
    RejectionReason.DEPENDENCY_UNSATISFIED: ("IBAE-ORCH-005",),
    RejectionReason.UNKNOWN_STATE: ("IBAE-AI-004", "IBAE-ORCH-005"),
    RejectionReason.OCCURRENCE_KEY_REQUIRED: ("IBAE-ORCH-007",),
    RejectionReason.UNEXPECTED_OCCURRENCE_KEY: ("IBAE-ORCH-003",),
    RejectionReason.DUPLICATE_OCCURRENCE: ("IBAE-ORCH-007",),
}


@dataclass(frozen=True, slots=True)
class Capability:
    """Orchestrator-owned capability classification.

    A model proposal references a capability by name. Replay safety is read
    from this admitted state record, never from model-proposed arguments.
    """

    name: str
    replay_safety: ReplaySafety
    description: str
    available: bool = True
    contract_version: int = 1
    required_state_keys: tuple[str, ...] = ()
    replay_evidence_id: str | None = None

    def __post_init__(self) -> None:
        require_symbol("capability name", self.name)
        if not isinstance(self.replay_safety, ReplaySafety):
            raise TypeError("replay_safety must be a ReplaySafety")
        require_text("capability description", self.description)
        if not isinstance(self.available, bool):
            raise TypeError("available must be a boolean")
        require_positive_int("contract_version", self.contract_version)
        required_state_keys = tuple(
            sorted(
                materialize_iterable(
                    "capability required state keys", self.required_state_keys
                )
            )
        )
        if len(required_state_keys) != len(set(required_state_keys)):
            raise ValueError("capability required state keys must be unique")
        for state_key in required_state_keys:
            require_symbol("capability required state key", state_key)
        object.__setattr__(self, "required_state_keys", required_state_keys)
        if self.replay_safety is ReplaySafety.PROVEN_REPLAY_SAFE:
            if self.replay_evidence_id is None:
                raise ValueError(
                    "proven replay-safe capabilities require replay evidence"
                )
            require_fingerprint("replay evidence id", self.replay_evidence_id)
        elif self.replay_evidence_id is not None:
            raise ValueError(
                "only proven replay-safe capabilities may carry replay evidence"
            )

    @property
    def is_replay_safe(self) -> bool:
        return self.replay_safety in {
            ReplaySafety.CACHEABLE_READ,
            ReplaySafety.PROVEN_REPLAY_SAFE,
        }

    @property
    def capability_id(self) -> str:
        return domain_fingerprint(
            CAPABILITY_ID_DOMAIN,
            {
                "contract_version": self.contract_version,
                "name": self.name,
                "replay_evidence_id": self.replay_evidence_id,
                "replay_safety": self.replay_safety.value,
                "required_state_keys": list(self.required_state_keys),
            },
        )

    def canonical_record(self) -> dict[str, object]:
        return {
            "available": self.available,
            "capability_id": self.capability_id,
            "contract_version": self.contract_version,
            "description": self.description,
            "name": self.name,
            "replay_evidence_id": self.replay_evidence_id,
            "replay_safety": self.replay_safety.value,
            "required_state_keys": list(self.required_state_keys),
        }


@dataclass(frozen=True, slots=True)
class OrchestrationLimits:
    max_obligations: int = 128
    max_epistemic_records: int = 256
    max_capabilities: int = 64
    max_batch_proposals: int = 64
    max_history: int = 256

    def __post_init__(self) -> None:
        for name, value in (
            ("max_obligations", self.max_obligations),
            ("max_epistemic_records", self.max_epistemic_records),
            ("max_capabilities", self.max_capabilities),
            ("max_batch_proposals", self.max_batch_proposals),
            ("max_history", self.max_history),
        ):
            require_positive_int(name, value)

    def canonical_record(self) -> dict[str, int]:
        return {
            "max_batch_proposals": self.max_batch_proposals,
            "max_capabilities": self.max_capabilities,
            "max_epistemic_records": self.max_epistemic_records,
            "max_history": self.max_history,
            "max_obligations": self.max_obligations,
        }


@dataclass(frozen=True, slots=True, init=False)
class Strategy:
    key: str
    _parameters: CanonicalValue

    def __init__(self, key: str, parameters: Any) -> None:
        require_symbol("strategy key", key)
        object.__setattr__(self, "key", key)
        object.__setattr__(self, "_parameters", CanonicalValue.from_value(parameters))

    @property
    def parameters(self) -> Any:
        return self._parameters.to_value()

    @property
    def strategy_id(self) -> str:
        return domain_fingerprint(STRATEGY_ID_DOMAIN, self.canonical_record())

    def canonical_record(self) -> dict[str, object]:
        return {"key": self.key, "parameters": self._parameters.to_value()}


@dataclass(frozen=True, slots=True, init=False)
class ActionProposal:
    """A model proposal, kept distinct from an admitted action."""

    proposal_key: str
    capability: str
    target_obligation_ids: tuple[str, ...]
    required_state_keys: tuple[str, ...]
    occurrence_key: str | None
    _arguments: CanonicalValue

    def __init__(
        self,
        proposal_key: str,
        capability: str,
        arguments: Any,
        *,
        target_obligation_ids: Iterable[str],
        required_state_keys: Iterable[str] = (),
        occurrence_key: str | None = None,
    ) -> None:
        require_symbol("proposal key", proposal_key)
        require_symbol("capability", capability)

        targets = tuple(
            sorted(materialize_iterable("target obligation ids", target_obligation_ids))
        )
        if not targets:
            raise ValueError("an action proposal must target at least one obligation")
        if len(targets) != len(set(targets)):
            raise ValueError("target obligation ids must be unique")
        for target in targets:
            require_fingerprint("target obligation id", target)

        state_keys = tuple(
            sorted(materialize_iterable("required state keys", required_state_keys))
        )
        if len(state_keys) != len(set(state_keys)):
            raise ValueError("required state keys must be unique")
        for state_key in state_keys:
            require_symbol("required state key", state_key)

        if occurrence_key is not None:
            require_symbol("occurrence key", occurrence_key)

        object.__setattr__(self, "proposal_key", proposal_key)
        object.__setattr__(self, "capability", capability)
        object.__setattr__(self, "target_obligation_ids", targets)
        object.__setattr__(self, "required_state_keys", state_keys)
        object.__setattr__(self, "occurrence_key", occurrence_key)
        object.__setattr__(self, "_arguments", CanonicalValue.from_value(arguments))

    @property
    def arguments(self) -> Any:
        return self._arguments.to_value()

    @property
    def proposal_id(self) -> str:
        return domain_fingerprint(PROPOSAL_ID_DOMAIN, self.canonical_record())

    def canonical_record(self) -> dict[str, object]:
        return {
            "arguments": self._arguments.to_value(),
            "capability": self.capability,
            "epistemic_class": "model_proposed",
            "occurrence_key": self.occurrence_key,
            "proposal_key": self.proposal_key,
            "required_state_keys": list(self.required_state_keys),
            "target_obligation_ids": list(self.target_obligation_ids),
        }


@dataclass(frozen=True, slots=True)
class ProposalBatch:
    batch_key: str
    strategy: Strategy
    proposals: tuple[ActionProposal, ...]

    def __post_init__(self) -> None:
        require_symbol("batch key", self.batch_key)
        if not isinstance(self.strategy, Strategy):
            raise TypeError("strategy must be a Strategy")
        proposals = materialize_iterable("proposals", self.proposals)
        if not proposals:
            raise ValueError("a proposal batch must not be empty")
        if any(not isinstance(item, ActionProposal) for item in proposals):
            raise TypeError("proposals must contain only ActionProposal records")
        keys = [item.proposal_key for item in proposals]
        if len(keys) != len(set(keys)):
            raise ValueError("proposal keys must be unique within a batch")
        object.__setattr__(self, "proposals", proposals)

    @property
    def ordered_proposals(self) -> tuple[ActionProposal, ...]:
        return tuple(sorted(self.proposals, key=lambda item: item.proposal_id))

    @property
    def batch_id(self) -> str:
        return domain_fingerprint(BATCH_ID_DOMAIN, self.canonical_record())

    def canonical_record(self) -> dict[str, object]:
        return {
            "batch_key": self.batch_key,
            "epistemic_class": "model_proposed",
            "proposals": [
                proposal.canonical_record() for proposal in self.ordered_proposals
            ],
            "strategy": self.strategy.canonical_record(),
        }


@dataclass(frozen=True, slots=True)
class AdmissionDecision:
    proposal_id: str
    proposal_key: str
    status: DecisionStatus
    logical_tick: int
    authority_layer: AuthorityLayer = AuthorityLayer.ORCHESTRATION
    invariant_ids: tuple[str, ...] = ()
    action_id: str | None = None
    equivalent_proposal_id: str | None = None
    rejection_reason: RejectionReason | None = None
    recovery_actions: tuple[RecoveryAction, ...] = ()
    blocking_obligation_ids: tuple[str, ...] = ()
    dependency_state_keys: tuple[str, ...] = ()
    unresolved_state_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_fingerprint("proposal id", self.proposal_id)
        require_symbol("proposal key", self.proposal_key)
        if not isinstance(self.status, DecisionStatus):
            raise TypeError("status must be a DecisionStatus")
        if not isinstance(self.authority_layer, AuthorityLayer):
            raise TypeError("authority_layer must be an AuthorityLayer")
        require_nonnegative_int("logical_tick", self.logical_tick)
        if self.action_id is not None:
            require_fingerprint("action id", self.action_id)
        if self.equivalent_proposal_id is not None:
            require_fingerprint("equivalent proposal id", self.equivalent_proposal_id)
        if self.rejection_reason is not None and not isinstance(
            self.rejection_reason, RejectionReason
        ):
            raise TypeError("rejection_reason must be a RejectionReason")
        if any(
            not isinstance(action, RecoveryAction) for action in self.recovery_actions
        ):
            raise TypeError("recovery_actions must contain RecoveryAction values")

        recoveries = tuple(
            sorted(
                set(materialize_iterable("recovery actions", self.recovery_actions)),
                key=lambda action: action.value,
            )
        )
        blocking_ids = tuple(
            sorted(
                materialize_iterable(
                    "blocking obligation ids", self.blocking_obligation_ids
                )
            )
        )
        dependency_keys = tuple(
            sorted(
                materialize_iterable(
                    "dependency state keys", self.dependency_state_keys
                )
            )
        )
        unresolved_keys = tuple(
            sorted(
                materialize_iterable(
                    "unresolved state keys", self.unresolved_state_keys
                )
            )
        )
        invariant_ids = tuple(
            sorted(materialize_iterable("invariant ids", self.invariant_ids))
        )
        for name, values in (
            ("blocking obligation ids", blocking_ids),
            ("dependency state keys", dependency_keys),
            ("unresolved state keys", unresolved_keys),
            ("invariant ids", invariant_ids),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must be unique")
        for blocking_id in blocking_ids:
            require_fingerprint("blocking obligation id", blocking_id)
        for unresolved_key in unresolved_keys:
            require_symbol("unresolved state key", unresolved_key)
        for dependency_key in dependency_keys:
            require_symbol("dependency state key", dependency_key)
        for invariant_id in invariant_ids:
            require_invariant_id(invariant_id)
        object.__setattr__(self, "recovery_actions", recoveries)
        object.__setattr__(self, "blocking_obligation_ids", blocking_ids)
        object.__setattr__(self, "dependency_state_keys", dependency_keys)
        object.__setattr__(self, "unresolved_state_keys", unresolved_keys)
        object.__setattr__(self, "invariant_ids", invariant_ids)

        if self.status is DecisionStatus.ADMITTED:
            if self.action_id is None:
                raise ValueError("admitted decisions require an action id")
            if self.equivalent_proposal_id is not None:
                raise ValueError(
                    "admitted decisions cannot name an equivalent proposal"
                )
            if self.rejection_reason is not None or recoveries:
                raise ValueError("admitted decisions cannot carry rejection state")
            if invariant_ids:
                raise ValueError("admitted decisions cannot carry rejection invariants")
        elif self.status is DecisionStatus.DEDUPLICATED:
            if self.action_id is None or self.equivalent_proposal_id is None:
                raise ValueError(
                    "deduplicated decisions require action and equivalent proposal ids"
                )
            if self.rejection_reason is not None or recoveries:
                raise ValueError("deduplicated decisions cannot carry rejection state")
            if invariant_ids:
                raise ValueError(
                    "deduplicated decisions cannot carry rejection invariants"
                )
        else:
            if self.action_id is not None or self.equivalent_proposal_id is not None:
                raise ValueError("rejected decisions cannot carry admitted identities")
            if self.rejection_reason is None:
                raise ValueError("rejected decisions require a reason code")
            if not invariant_ids:
                raise ValueError("rejected decisions require relevant invariant ids")

    def canonical_record(self) -> dict[str, object]:
        return {
            "action_id": self.action_id,
            "authority_layer": self.authority_layer.value,
            "blocking_obligation_ids": list(self.blocking_obligation_ids),
            "dependency_state_keys": list(self.dependency_state_keys),
            "equivalent_proposal_id": self.equivalent_proposal_id,
            "logical_tick": self.logical_tick,
            "invariant_ids": list(self.invariant_ids),
            "proposal_id": self.proposal_id,
            "proposal_key": self.proposal_key,
            "recovery_actions": [action.value for action in self.recovery_actions],
            "rejection_reason": (
                None if self.rejection_reason is None else self.rejection_reason.value
            ),
            "status": self.status.value,
            "unresolved_state_keys": list(self.unresolved_state_keys),
        }


@dataclass(frozen=True, slots=True)
class BatchRejection:
    reason: RejectionReason
    recovery_actions: tuple[RecoveryAction, ...]
    logical_tick: int
    authority_layer: AuthorityLayer = AuthorityLayer.ORCHESTRATION
    invariant_ids: tuple[str, ...] = ("IBAE-BND-008", "IBAE-ORCH-006")

    def __post_init__(self) -> None:
        if not isinstance(self.reason, RejectionReason):
            raise TypeError("reason must be a RejectionReason")
        if not isinstance(self.authority_layer, AuthorityLayer):
            raise TypeError("authority_layer must be an AuthorityLayer")
        if any(
            not isinstance(action, RecoveryAction) for action in self.recovery_actions
        ):
            raise TypeError("recovery_actions must contain RecoveryAction values")
        require_nonnegative_int("logical_tick", self.logical_tick)
        object.__setattr__(
            self,
            "recovery_actions",
            tuple(
                sorted(
                    set(
                        materialize_iterable("recovery actions", self.recovery_actions)
                    ),
                    key=lambda action: action.value,
                )
            ),
        )
        invariant_ids = tuple(
            sorted(materialize_iterable("invariant ids", self.invariant_ids))
        )
        if not invariant_ids:
            raise ValueError("batch rejections require relevant invariant ids")
        for invariant_id in invariant_ids:
            require_invariant_id(invariant_id)
        object.__setattr__(self, "invariant_ids", invariant_ids)

    def canonical_record(self) -> dict[str, object]:
        return {
            "authority_layer": self.authority_layer.value,
            "invariant_ids": list(self.invariant_ids),
            "logical_tick": self.logical_tick,
            "reason": self.reason.value,
            "recovery_actions": [action.value for action in self.recovery_actions],
        }


@dataclass(frozen=True, slots=True)
class AdmissionReceipt:
    batch_id: str
    strategy_id: str
    prior_state_id: str
    next_state_id: str
    status: BatchStatus
    logical_tick_start: int
    logical_tick_end: int
    decisions: tuple[AdmissionDecision, ...] = ()
    batch_rejection: BatchRejection | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("batch_id", self.batch_id),
            ("strategy_id", self.strategy_id),
            ("prior_state_id", self.prior_state_id),
            ("next_state_id", self.next_state_id),
        ):
            require_fingerprint(name, value)
        if not isinstance(self.status, BatchStatus):
            raise TypeError("status must be a BatchStatus")
        require_nonnegative_int("logical_tick_start", self.logical_tick_start)
        require_nonnegative_int("logical_tick_end", self.logical_tick_end)
        if self.logical_tick_end < self.logical_tick_start:
            raise ValueError("logical tick cannot move backwards")
        decisions = materialize_iterable("decisions", self.decisions)
        if any(not isinstance(item, AdmissionDecision) for item in decisions):
            raise TypeError("decisions must contain AdmissionDecision records")
        object.__setattr__(self, "decisions", decisions)
        if self.status is BatchStatus.REJECTED:
            if self.batch_rejection is None or decisions:
                raise ValueError(
                    "rejected batches require one batch rejection and no decisions"
                )
            if self.logical_tick_end != self.logical_tick_start + 1:
                raise ValueError("a batch rejection consumes exactly one logical tick")
            if self.batch_rejection.logical_tick != self.logical_tick_end:
                raise ValueError("batch rejection tick must match receipt end tick")
        elif self.batch_rejection is not None:
            raise ValueError("processed batches cannot carry a batch rejection")
        else:
            if not decisions:
                raise ValueError("a processed batch must contain decisions")
            expected_ticks = tuple(
                range(self.logical_tick_start + 1, self.logical_tick_end + 1)
            )
            if tuple(item.logical_tick for item in decisions) != expected_ticks:
                raise ValueError(
                    "processed proposal decisions must consume contiguous logical ticks"
                )
            if tuple(item.proposal_id for item in decisions) != tuple(
                sorted(item.proposal_id for item in decisions)
            ):
                raise ValueError("proposal decisions must use canonical id ordering")

    @property
    def receipt_id(self) -> str:
        return domain_fingerprint(RECEIPT_ID_DOMAIN, self.canonical_record())

    def canonical_record(self) -> dict[str, object]:
        return {
            "batch_id": self.batch_id,
            "batch_rejection": (
                None
                if self.batch_rejection is None
                else self.batch_rejection.canonical_record()
            ),
            "decisions": [decision.canonical_record() for decision in self.decisions],
            "logical_clock_profile": LOGICAL_CLOCK_PROFILE,
            "logical_tick_end": self.logical_tick_end,
            "logical_tick_start": self.logical_tick_start,
            "next_state_id": self.next_state_id,
            "prior_state_id": self.prior_state_id,
            "protocol": AGENT_PROTOCOL,
            "status": self.status.value,
            "strategy_id": self.strategy_id,
        }


@dataclass(frozen=True, slots=True)
class OrchestrationState:
    obligations: ObligationRegistry
    epistemic_state: EpistemicState
    capabilities: tuple[Capability, ...]
    limits: OrchestrationLimits = OrchestrationLimits()
    logical_tick: int = 0
    history: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.obligations, ObligationRegistry):
            raise TypeError("obligations must be an ObligationRegistry")
        if not isinstance(self.epistemic_state, EpistemicState):
            raise TypeError("epistemic_state must be an EpistemicState")
        if not isinstance(self.limits, OrchestrationLimits):
            raise TypeError("limits must be OrchestrationLimits")
        require_nonnegative_int("logical_tick", self.logical_tick)

        if self.obligations.max_obligations != self.limits.max_obligations:
            raise ValueError("obligation registry bound must match state limits")
        if self.epistemic_state.max_records != self.limits.max_epistemic_records:
            raise ValueError("epistemic state bound must match state limits")

        supplied_capabilities = materialize_iterable("capabilities", self.capabilities)
        if any(not isinstance(item, Capability) for item in supplied_capabilities):
            raise TypeError("capabilities must contain Capability records")
        capabilities = tuple(sorted(supplied_capabilities, key=lambda item: item.name))
        if len(capabilities) > self.limits.max_capabilities:
            raise ValueError("capability registry exceeds max_capabilities")
        names = [item.name for item in capabilities]
        if len(names) != len(set(names)):
            raise ValueError("capability names must be unique")
        object.__setattr__(self, "capabilities", capabilities)

        history = materialize_iterable("history", self.history)
        if len(history) > self.limits.max_history:
            raise ValueError("orchestration history exceeds max_history")
        for event_id in history:
            require_fingerprint("history event id", event_id)
        object.__setattr__(self, "history", history)

    @classmethod
    def create(
        cls,
        obligations: Iterable[Obligation],
        *,
        epistemic_state: EpistemicState | None = None,
        capabilities: Iterable[Capability] = (),
        limits: OrchestrationLimits | None = None,
    ) -> OrchestrationState:
        active_limits = limits or OrchestrationLimits()
        active_epistemic_state = epistemic_state or EpistemicState(
            max_records=active_limits.max_epistemic_records
        )
        return cls(
            obligations=ObligationRegistry.from_iterable(
                obligations, max_obligations=active_limits.max_obligations
            ),
            epistemic_state=active_epistemic_state,
            capabilities=tuple(capabilities),
            limits=active_limits,
        )

    @property
    def state_id(self) -> str:
        return domain_fingerprint(STATE_ID_DOMAIN, self.canonical_record())

    def capability(self, name: str) -> Capability | None:
        require_symbol("capability name", name)
        return next((item for item in self.capabilities if item.name == name), None)

    def canonical_record(self) -> dict[str, object]:
        return {
            "capabilities": [item.canonical_record() for item in self.capabilities],
            "epistemic_state": self.epistemic_state.canonical_record(),
            "history": list(self.history),
            "limits": self.limits.canonical_record(),
            "logical_clock": {
                "profile": LOGICAL_CLOCK_PROFILE,
                "tick": self.logical_tick,
            },
            "obligations": self.obligations.canonical_record(),
            "protocol": AGENT_PROTOCOL,
        }

    def compact_projection(self) -> dict[str, object]:
        obligation_groups: dict[str, list[dict[str, object]]] = {
            "blocked": [],
            "ready": [],
            "satisfied": [],
        }
        for obligation in self.obligations.obligations:
            readiness = self.obligations.readiness(obligation.obligation_id)
            record = {
                "blocking_dependency_ids": list(
                    self.obligations.blocking_dependency_ids(obligation.obligation_id)
                ),
                "key": obligation.key,
                "obligation_id": obligation.obligation_id,
                "readiness": readiness.value,
                "status": obligation.status.value,
            }
            if readiness is ObligationReadiness.READY:
                obligation_groups["ready"].append(record)
            elif readiness is ObligationReadiness.SATISFIED:
                obligation_groups["satisfied"].append(record)
            else:
                obligation_groups["blocked"].append(record)

        return {
            "bounds": self.limits.canonical_record(),
            "capabilities": [item.canonical_record() for item in self.capabilities],
            "capacity": {
                "capability_slots_remaining": (
                    self.limits.max_capabilities - len(self.capabilities)
                ),
                "epistemic_slots_remaining": (
                    self.limits.max_epistemic_records
                    - len(self.epistemic_state.records)
                ),
                "obligation_slots_remaining": (
                    self.limits.max_obligations - len(self.obligations.obligations)
                ),
            },
            "canonical_state_identity": self.state_id,
            "epistemic_state": self.epistemic_state.projection(),
            "logical_clock": {
                "profile": LOGICAL_CLOCK_PROFILE,
                "tick": self.logical_tick,
            },
            "obligations": obligation_groups,
            "protocol": AGENT_PROTOCOL,
        }

    def advance(
        self,
        *,
        logical_tick: int,
        event_ids: Iterable[str],
    ) -> OrchestrationState:
        require_nonnegative_int("logical_tick", logical_tick)
        if logical_tick < self.logical_tick:
            raise ValueError("logical tick cannot move backwards")
        additions = materialize_iterable("event ids", event_ids)
        for event_id in additions:
            require_fingerprint("event id", event_id)
        if logical_tick - self.logical_tick != len(additions):
            raise ValueError("each orchestration event must consume one logical tick")
        history = (*self.history, *additions)[-self.limits.max_history :]
        return replace(self, logical_tick=logical_tick, history=history)


@dataclass(frozen=True, slots=True)
class AdmissionTransition:
    next_state: OrchestrationState
    receipt: AdmissionReceipt

    def __post_init__(self) -> None:
        if not isinstance(self.next_state, OrchestrationState):
            raise TypeError("next_state must be an OrchestrationState")
        if not isinstance(self.receipt, AdmissionReceipt):
            raise TypeError("receipt must be an AdmissionReceipt")
        if self.next_state.state_id != self.receipt.next_state_id:
            raise ValueError("receipt next state identity does not match next_state")


def _event_id(batch_id: str, record: dict[str, object]) -> str:
    return domain_fingerprint(
        EVENT_ID_DOMAIN,
        {"batch_id": batch_id, "event": record},
    )


def _rejected_decision(
    proposal: ActionProposal,
    *,
    logical_tick: int,
    reason: RejectionReason,
    recovery_actions: tuple[RecoveryAction, ...],
    blocking_obligation_ids: tuple[str, ...] = (),
    dependency_state_keys: tuple[str, ...] = (),
    unresolved_state_keys: tuple[str, ...] = (),
) -> AdmissionDecision:
    return AdmissionDecision(
        proposal_id=proposal.proposal_id,
        proposal_key=proposal.proposal_key,
        status=DecisionStatus.REJECTED,
        logical_tick=logical_tick,
        invariant_ids=_REJECTION_INVARIANTS[reason],
        rejection_reason=reason,
        recovery_actions=recovery_actions,
        blocking_obligation_ids=blocking_obligation_ids,
        dependency_state_keys=dependency_state_keys,
        unresolved_state_keys=unresolved_state_keys,
    )


def _validate_targets(
    state: OrchestrationState,
    proposal: ActionProposal,
    *,
    logical_tick: int,
    dependency_state_keys: tuple[str, ...],
) -> AdmissionDecision | None:
    known_ids = set(state.obligations.known_ids)
    unknown = tuple(
        target for target in proposal.target_obligation_ids if target not in known_ids
    )
    if unknown:
        return _rejected_decision(
            proposal,
            logical_tick=logical_tick,
            reason=RejectionReason.UNKNOWN_OBLIGATION,
            recovery_actions=(RecoveryAction.CHOOSE_KNOWN_OBLIGATION,),
            blocking_obligation_ids=unknown,
            dependency_state_keys=dependency_state_keys,
        )

    satisfied = tuple(
        target
        for target in proposal.target_obligation_ids
        if state.obligations.readiness(target) is ObligationReadiness.SATISFIED
    )
    if satisfied:
        return _rejected_decision(
            proposal,
            logical_tick=logical_tick,
            reason=RejectionReason.OBLIGATION_SATISFIED,
            recovery_actions=(RecoveryAction.TARGET_UNSATISFIED_OBLIGATION,),
            blocking_obligation_ids=satisfied,
            dependency_state_keys=dependency_state_keys,
        )

    explicitly_blocked = tuple(
        target
        for target in proposal.target_obligation_ids
        if state.obligations.readiness(target) is ObligationReadiness.EXPLICITLY_BLOCKED
    )
    if explicitly_blocked:
        return _rejected_decision(
            proposal,
            logical_tick=logical_tick,
            reason=RejectionReason.OBLIGATION_BLOCKED,
            recovery_actions=(RecoveryAction.RESOLVE_BLOCKER,),
            blocking_obligation_ids=explicitly_blocked,
            dependency_state_keys=dependency_state_keys,
        )

    dependency_blocked = tuple(
        target
        for target in proposal.target_obligation_ids
        if state.obligations.readiness(target) is ObligationReadiness.DEPENDENCY_BLOCKED
    )
    if dependency_blocked:
        blockers = tuple(
            sorted(
                {
                    dependency_id
                    for target in dependency_blocked
                    for dependency_id in state.obligations.blocking_dependency_ids(
                        target
                    )
                }
            )
        )
        return _rejected_decision(
            proposal,
            logical_tick=logical_tick,
            reason=RejectionReason.DEPENDENCY_UNSATISFIED,
            recovery_actions=(RecoveryAction.SATISFY_DEPENDENCIES,),
            blocking_obligation_ids=blockers,
            dependency_state_keys=dependency_state_keys,
        )
    return None


def _action_id(
    capability: Capability,
    proposal: ActionProposal,
    dependency_state_id: str,
) -> str:
    record: dict[str, object] = {
        "arguments": proposal.arguments,
        "capability_id": capability.capability_id,
        "dependency_state_id": dependency_state_id,
    }
    if capability.replay_safety is ReplaySafety.OCCURRENCE_SENSITIVE:
        record["occurrence_key"] = proposal.occurrence_key
    return domain_fingerprint(ACTION_ID_DOMAIN, record)


def admit_batch(
    state: OrchestrationState,
    batch: ProposalBatch,
) -> AdmissionTransition:
    """Pure deterministic proposal-to-admission transition.

    Every processed proposal advances the logical clock exactly once. A
    rejected over-size batch advances it once as a canonical batch rejection.
    No wall-clock value participates in ordering, identity, or boundedness.
    """

    if not isinstance(state, OrchestrationState):
        raise TypeError("state must be an OrchestrationState")
    if not isinstance(batch, ProposalBatch):
        raise TypeError("batch must be a ProposalBatch")

    prior_state_id = state.state_id
    if len(batch.proposals) > state.limits.max_batch_proposals:
        logical_tick = state.logical_tick + 1
        rejection = BatchRejection(
            reason=RejectionReason.BATCH_LIMIT_EXCEEDED,
            recovery_actions=(RecoveryAction.SPLIT_BATCH,),
            logical_tick=logical_tick,
            invariant_ids=_REJECTION_INVARIANTS[RejectionReason.BATCH_LIMIT_EXCEEDED],
        )
        event_id = _event_id(
            batch.batch_id,
            {"batch_rejection": rejection.canonical_record()},
        )
        next_state = state.advance(
            logical_tick=logical_tick,
            event_ids=(event_id,),
        )
        receipt = AdmissionReceipt(
            batch_id=batch.batch_id,
            strategy_id=batch.strategy.strategy_id,
            prior_state_id=prior_state_id,
            next_state_id=next_state.state_id,
            status=BatchStatus.REJECTED,
            logical_tick_start=state.logical_tick,
            logical_tick_end=logical_tick,
            batch_rejection=rejection,
        )
        return AdmissionTransition(next_state=next_state, receipt=receipt)

    decisions: list[AdmissionDecision] = []
    event_ids: list[str] = []
    replay_safe_actions: dict[str, str] = {}
    occurrence_owners: dict[str, str] = {}
    logical_tick = state.logical_tick

    for proposal in batch.ordered_proposals:
        logical_tick += 1
        capability = state.capability(proposal.capability)
        dependency_state_keys = proposal.required_state_keys
        if capability is None:
            decision = _rejected_decision(
                proposal,
                logical_tick=logical_tick,
                reason=RejectionReason.UNKNOWN_CAPABILITY,
                recovery_actions=(RecoveryAction.CHOOSE_AVAILABLE_CAPABILITY,),
                dependency_state_keys=dependency_state_keys,
            )
        elif not capability.available:
            dependency_state_keys = tuple(
                sorted(
                    set(capability.required_state_keys)
                    | set(proposal.required_state_keys)
                )
            )
            decision = _rejected_decision(
                proposal,
                logical_tick=logical_tick,
                reason=RejectionReason.CAPABILITY_UNAVAILABLE,
                recovery_actions=(RecoveryAction.CHOOSE_AVAILABLE_CAPABILITY,),
                dependency_state_keys=dependency_state_keys,
            )
        else:
            dependency_state_keys = tuple(
                sorted(
                    set(capability.required_state_keys)
                    | set(proposal.required_state_keys)
                )
            )
            decision = _validate_targets(
                state,
                proposal,
                logical_tick=logical_tick,
                dependency_state_keys=dependency_state_keys,
            )

        if decision is None:
            unresolved = state.epistemic_state.unresolved_keys(dependency_state_keys)
            if unresolved:
                decision = _rejected_decision(
                    proposal,
                    logical_tick=logical_tick,
                    reason=RejectionReason.UNKNOWN_STATE,
                    recovery_actions=(RecoveryAction.OBSERVE_REQUIRED_STATE,),
                    dependency_state_keys=dependency_state_keys,
                    unresolved_state_keys=unresolved,
                )

        if decision is None and capability is not None:
            if (
                capability.replay_safety is ReplaySafety.OCCURRENCE_SENSITIVE
                and proposal.occurrence_key is None
            ):
                decision = _rejected_decision(
                    proposal,
                    logical_tick=logical_tick,
                    reason=RejectionReason.OCCURRENCE_KEY_REQUIRED,
                    recovery_actions=(RecoveryAction.ADD_OCCURRENCE_KEY,),
                    dependency_state_keys=dependency_state_keys,
                )
            elif capability.is_replay_safe and proposal.occurrence_key is not None:
                decision = _rejected_decision(
                    proposal,
                    logical_tick=logical_tick,
                    reason=RejectionReason.UNEXPECTED_OCCURRENCE_KEY,
                    recovery_actions=(RecoveryAction.REMOVE_OCCURRENCE_KEY,),
                    dependency_state_keys=dependency_state_keys,
                )

        if decision is None and capability is not None:
            dependency_state_id = state.epistemic_state.dependency_digest(
                dependency_state_keys
            )
            action_id = _action_id(capability, proposal, dependency_state_id)
            if capability.is_replay_safe:
                equivalent = replay_safe_actions.get(action_id)
                if equivalent is None:
                    replay_safe_actions[action_id] = proposal.proposal_id
                    decision = AdmissionDecision(
                        proposal_id=proposal.proposal_id,
                        proposal_key=proposal.proposal_key,
                        status=DecisionStatus.ADMITTED,
                        logical_tick=logical_tick,
                        action_id=action_id,
                        dependency_state_keys=dependency_state_keys,
                    )
                else:
                    decision = AdmissionDecision(
                        proposal_id=proposal.proposal_id,
                        proposal_key=proposal.proposal_key,
                        status=DecisionStatus.DEDUPLICATED,
                        logical_tick=logical_tick,
                        action_id=action_id,
                        equivalent_proposal_id=equivalent,
                        dependency_state_keys=dependency_state_keys,
                    )
            else:
                assert proposal.occurrence_key is not None
                existing_owner = occurrence_owners.get(proposal.occurrence_key)
                if existing_owner is not None:
                    decision = _rejected_decision(
                        proposal,
                        logical_tick=logical_tick,
                        reason=RejectionReason.DUPLICATE_OCCURRENCE,
                        recovery_actions=(RecoveryAction.USE_DISTINCT_OCCURRENCE_KEY,),
                        dependency_state_keys=dependency_state_keys,
                    )
                else:
                    occurrence_owners[proposal.occurrence_key] = proposal.proposal_id
                    decision = AdmissionDecision(
                        proposal_id=proposal.proposal_id,
                        proposal_key=proposal.proposal_key,
                        status=DecisionStatus.ADMITTED,
                        logical_tick=logical_tick,
                        action_id=action_id,
                        dependency_state_keys=dependency_state_keys,
                    )

        assert decision is not None
        decisions.append(decision)
        event_ids.append(
            _event_id(
                batch.batch_id,
                {
                    "decision": decision.canonical_record(),
                    "strategy_id": batch.strategy.strategy_id,
                },
            )
        )

    next_state = state.advance(logical_tick=logical_tick, event_ids=event_ids)
    receipt = AdmissionReceipt(
        batch_id=batch.batch_id,
        strategy_id=batch.strategy.strategy_id,
        prior_state_id=prior_state_id,
        next_state_id=next_state.state_id,
        status=BatchStatus.PROCESSED,
        logical_tick_start=state.logical_tick,
        logical_tick_end=logical_tick,
        decisions=tuple(decisions),
    )
    return AdmissionTransition(next_state=next_state, receipt=receipt)
