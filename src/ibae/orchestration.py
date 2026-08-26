"""Deterministic Python orchestration reference semantics for IBAE v0.2."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any

from ._records import (
    CanonicalValue,
    materialize_bounded_iterable,
    require_bounded_positive_int,
    require_fingerprint,
    require_invariant_id,
    require_nonnegative_int,
    require_positive_int,
    require_symbol,
    require_text,
)
from .canonical import domain_fingerprint
from .epistemic import MAX_EPISTEMIC_RECORDS, EpistemicState
from .obligations import (
    MAX_OBLIGATIONS,
    Obligation,
    ObligationReadiness,
    ObligationRegistry,
)

AGENT_PROTOCOL = "IBAE-AGENT-PROTOCOL-V1"
LOGICAL_CLOCK_PROFILE = "IBAE-LOGICAL-CLOCK-V1"
STRATEGY_PARAMETER_SCHEMA = "IBAE-STRATEGY-PARAMETERS-V1"
CAPABILITY_ARGUMENT_SCHEMA = "IBAE-CAPABILITY-ARGUMENTS-V1"
MAX_CAPABILITIES = 64
MAX_CAPABILITY_ARGUMENTS = 32
MAX_PROPOSALS_PER_BATCH = 64
MAX_HISTORY_EVENTS = 256
MAX_OCCURRENCE_OWNERS = 256
MAX_STATE_KEYS_PER_DECLARATION = MAX_EPISTEMIC_RECORDS // 2
MAX_STRATEGY_PARAMETERS = 32
MAX_STRATEGY_SCHEMAS = 32
MAX_STRATEGY_SYMBOL_LIST_ITEMS = 64
MAX_INVARIANT_IDS_PER_REJECTION = 64

CAPABILITY_ID_DOMAIN = "ibae.capability-id.v1"
STRATEGY_ID_DOMAIN = "ibae.strategy-id.v1"
STRATEGY_SCHEMA_ID_DOMAIN = "ibae.strategy-parameter-schema.v1"
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


class ProposalOrdering(str, Enum):
    CANONICAL_INDEPENDENT = "canonical_independent"
    DECLARED_SEQUENCE = "declared_sequence"


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
    STRATEGY_SCHEMA_NOT_ADMITTED = "IBAE-REJECT-STRATEGY-SCHEMA-NOT-ADMITTED"
    UNKNOWN_CAPABILITY = "IBAE-REJECT-UNKNOWN-CAPABILITY"
    CAPABILITY_UNAVAILABLE = "IBAE-REJECT-CAPABILITY-UNAVAILABLE"
    ARGUMENT_SCHEMA_MISMATCH = "IBAE-REJECT-ARGUMENT-SCHEMA-MISMATCH"
    UNKNOWN_OBLIGATION = "IBAE-REJECT-UNKNOWN-OBLIGATION"
    OBLIGATION_SATISFIED = "IBAE-REJECT-OBLIGATION-SATISFIED"
    OBLIGATION_BLOCKED = "IBAE-REJECT-OBLIGATION-BLOCKED"
    DEPENDENCY_UNSATISFIED = "IBAE-REJECT-DEPENDENCY-UNSATISFIED"
    UNKNOWN_STATE = "IBAE-REJECT-UNKNOWN-STATE"
    OCCURRENCE_KEY_REQUIRED = "IBAE-REJECT-OCCURRENCE-KEY-REQUIRED"
    UNEXPECTED_OCCURRENCE_KEY = "IBAE-REJECT-UNEXPECTED-OCCURRENCE-KEY"
    DUPLICATE_OCCURRENCE = "IBAE-REJECT-DUPLICATE-OCCURRENCE"
    OCCURRENCE_REGISTRY_FULL = "IBAE-REJECT-OCCURRENCE-REGISTRY-FULL"
    ORDERING_CONTRACT_REQUIRED = "IBAE-REJECT-ORDERING-CONTRACT-REQUIRED"


class RecoveryAction(str, Enum):
    SPLIT_BATCH = "IBAE-RECOVERY-SPLIT-BATCH"
    USE_ADMITTED_STRATEGY_SCHEMA = "IBAE-RECOVERY-USE-ADMITTED-STRATEGY-SCHEMA"
    CHOOSE_AVAILABLE_CAPABILITY = "IBAE-RECOVERY-CHOOSE-AVAILABLE-CAPABILITY"
    USE_ADMITTED_ARGUMENT_SCHEMA = "IBAE-RECOVERY-USE-ADMITTED-ARGUMENT-SCHEMA"
    CHOOSE_KNOWN_OBLIGATION = "IBAE-RECOVERY-CHOOSE-KNOWN-OBLIGATION"
    TARGET_UNSATISFIED_OBLIGATION = "IBAE-RECOVERY-TARGET-UNSATISFIED-OBLIGATION"
    RESOLVE_BLOCKER = "IBAE-RECOVERY-RESOLVE-BLOCKER"
    SATISFY_DEPENDENCIES = "IBAE-RECOVERY-SATISFY-DEPENDENCIES"
    OBSERVE_REQUIRED_STATE = "IBAE-RECOVERY-OBSERVE-REQUIRED-STATE"
    ADD_OCCURRENCE_KEY = "IBAE-RECOVERY-ADD-OCCURRENCE-KEY"
    REMOVE_OCCURRENCE_KEY = "IBAE-RECOVERY-REMOVE-OCCURRENCE-KEY"
    USE_DISTINCT_OCCURRENCE_KEY = "IBAE-RECOVERY-USE-DISTINCT-OCCURRENCE-KEY"
    REQUEST_NEW_BOUNDED_SCOPE = "IBAE-RECOVERY-REQUEST-NEW-BOUNDED-SCOPE"
    USE_DECLARED_SEQUENCE = "IBAE-RECOVERY-USE-DECLARED-SEQUENCE"


_REJECTION_INVARIANTS: dict[RejectionReason, tuple[str, ...]] = {
    RejectionReason.BATCH_LIMIT_EXCEEDED: ("IBAE-BND-008", "IBAE-ORCH-006"),
    RejectionReason.STRATEGY_SCHEMA_NOT_ADMITTED: (
        "IBAE-AI-002",
        "IBAE-CLK-002",
        "IBAE-PROG-005",
    ),
    RejectionReason.UNKNOWN_CAPABILITY: ("IBAE-GOV-006", "IBAE-ORCH-001"),
    RejectionReason.CAPABILITY_UNAVAILABLE: ("IBAE-ORCH-001",),
    RejectionReason.ARGUMENT_SCHEMA_MISMATCH: (
        "IBAE-CLK-002",
        "IBAE-ORCH-001",
        "IBAE-ORCH-003",
    ),
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
    RejectionReason.OCCURRENCE_REGISTRY_FULL: (
        "IBAE-BND-008",
        "IBAE-ORCH-006",
        "IBAE-ORCH-007",
    ),
    RejectionReason.ORDERING_CONTRACT_REQUIRED: (
        "IBAE-DET-004",
        "IBAE-ORCH-004",
        "IBAE-ORCH-007",
    ),
}


class StrategyValueKind(str, Enum):
    BOOLEAN = "boolean"
    BOUNDED_INTEGER = "bounded_integer"
    SYMBOL = "symbol"
    SYMBOL_LIST = "symbol_list"


@dataclass(frozen=True, slots=True)
class StrategyParameterSpec:
    """One typed, allowlisted semantic strategy parameter."""

    name: str
    value_kind: StrategyValueKind
    required: bool = True
    minimum: int | None = None
    maximum: int | None = None
    allowed_symbols: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_symbol("strategy parameter name", self.name)
        if not isinstance(self.value_kind, StrategyValueKind):
            raise TypeError("value_kind must be a StrategyValueKind")
        if not isinstance(self.required, bool):
            raise TypeError("required must be a boolean")
        symbols = tuple(
            sorted(
                materialize_bounded_iterable(
                    "allowed strategy symbols",
                    self.allowed_symbols,
                    limit=MAX_STRATEGY_SYMBOL_LIST_ITEMS,
                )
            )
        )
        if len(symbols) != len(set(symbols)):
            raise ValueError("allowed strategy symbols must be unique")
        for symbol in symbols:
            require_symbol("allowed strategy symbol", symbol)
        object.__setattr__(self, "allowed_symbols", symbols)

        if self.value_kind is StrategyValueKind.BOUNDED_INTEGER:
            if self.minimum is None or self.maximum is None:
                raise ValueError("bounded integer parameters require minimum and maximum")
            require_nonnegative_int("strategy parameter minimum", self.minimum)
            require_nonnegative_int("strategy parameter maximum", self.maximum)
            if self.minimum > self.maximum:
                raise ValueError("strategy parameter minimum exceeds maximum")
            if symbols:
                raise ValueError("bounded integer parameters cannot allow symbols")
        elif self.value_kind in {
            StrategyValueKind.SYMBOL,
            StrategyValueKind.SYMBOL_LIST,
        }:
            if not symbols:
                raise ValueError("symbol parameters require a finite symbol allowlist")
            if self.minimum is not None or self.maximum is not None:
                raise ValueError("symbol parameters cannot carry integer bounds")
        elif (
            symbols
            or self.minimum is not None
            or self.maximum is not None
        ):
            raise ValueError("boolean parameters cannot carry value constraints")

    def normalize(self, value: Any) -> object:
        if self.value_kind is StrategyValueKind.BOOLEAN:
            if not isinstance(value, bool):
                raise TypeError(f"strategy parameter {self.name} must be boolean")
            return value
        if self.value_kind is StrategyValueKind.BOUNDED_INTEGER:
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(
                    f"strategy parameter {self.name} must be an integer"
                )
            assert self.minimum is not None and self.maximum is not None
            if value < self.minimum or value > self.maximum:
                raise ValueError(
                    f"strategy parameter {self.name} must be between "
                    f"{self.minimum} and {self.maximum}"
                )
            return value
        if self.value_kind is StrategyValueKind.SYMBOL:
            require_symbol(f"strategy parameter {self.name}", value)
            if value not in self.allowed_symbols:
                raise ValueError(
                    f"strategy parameter {self.name} is not an allowed symbol"
                )
            return value

        values = materialize_bounded_iterable(
            f"strategy parameter {self.name}",
            value,
            limit=MAX_STRATEGY_SYMBOL_LIST_ITEMS,
        )
        for item in values:
            require_symbol(f"strategy parameter {self.name} item", item)
            if item not in self.allowed_symbols:
                raise ValueError(
                    f"strategy parameter {self.name} contains a disallowed symbol"
                )
        return list(values)

    def canonical_record(self) -> dict[str, object]:
        return {
            "allowed_symbols": list(self.allowed_symbols),
            "maximum": self.maximum,
            "minimum": self.minimum,
            "name": self.name,
            "required": self.required,
            "value_kind": self.value_kind.value,
        }


@dataclass(frozen=True, slots=True)
class StrategySchema:
    """Orchestrator-owned allowlist for one strategy's semantic parameters."""

    strategy_key: str
    parameter_specs: tuple[StrategyParameterSpec, ...] = ()
    contract_version: int = 1

    def __post_init__(self) -> None:
        require_symbol("strategy schema key", self.strategy_key)
        require_positive_int("strategy schema contract version", self.contract_version)
        supplied = materialize_bounded_iterable(
            "strategy parameter specs",
            self.parameter_specs,
            limit=MAX_STRATEGY_PARAMETERS,
        )
        if any(not isinstance(item, StrategyParameterSpec) for item in supplied):
            raise TypeError(
                "parameter_specs must contain StrategyParameterSpec records"
            )
        specs = tuple(sorted(supplied, key=lambda item: item.name))
        names = [item.name for item in specs]
        if len(names) != len(set(names)):
            raise ValueError("strategy parameter spec names must be unique")
        object.__setattr__(self, "parameter_specs", specs)

    @property
    def schema_id(self) -> str:
        return domain_fingerprint(STRATEGY_SCHEMA_ID_DOMAIN, self.canonical_record())

    def normalize_parameters(self, parameters: Mapping[str, Any]) -> dict[str, object]:
        if not isinstance(parameters, Mapping):
            raise TypeError("strategy parameters must be a semantic mapping")
        supplied = materialize_bounded_iterable(
            "strategy parameters",
            parameters.items(),
            limit=MAX_STRATEGY_PARAMETERS,
        )
        raw: dict[str, Any] = {}
        for item in supplied:
            if not isinstance(item, tuple) or len(item) != 2:
                raise TypeError("strategy parameter items must be key/value pairs")
            name, value = item
            if not isinstance(name, str):
                raise TypeError("strategy parameter keys must be strings")
            if name in raw:
                raise ValueError("strategy parameter keys must be unique")
            raw[name] = value

        specs = {item.name: item for item in self.parameter_specs}
        unknown = tuple(sorted(set(raw) - set(specs)))
        if unknown:
            raise ValueError(
                "strategy parameters are not allowed by the schema: "
                + ",".join(unknown)
            )
        missing = tuple(
            item.name
            for item in self.parameter_specs
            if item.required and item.name not in raw
        )
        if missing:
            raise ValueError(
                "strategy parameters are missing required keys: "
                + ",".join(missing)
            )
        return {
            name: specs[name].normalize(raw[name]) for name in sorted(raw)
        }

    def canonical_record(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "parameter_schema": STRATEGY_PARAMETER_SCHEMA,
            "parameter_specs": [
                item.canonical_record() for item in self.parameter_specs
            ],
            "strategy_key": self.strategy_key,
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
    semantic_argument_keys: tuple[str, ...] = ()
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
                materialize_bounded_iterable(
                    "capability required state keys",
                    self.required_state_keys,
                    limit=MAX_STATE_KEYS_PER_DECLARATION,
                )
            )
        )
        if len(required_state_keys) != len(set(required_state_keys)):
            raise ValueError("capability required state keys must be unique")
        for state_key in required_state_keys:
            require_symbol("capability required state key", state_key)
        object.__setattr__(self, "required_state_keys", required_state_keys)

        semantic_argument_keys = tuple(
            sorted(
                materialize_bounded_iterable(
                    "capability semantic argument keys",
                    self.semantic_argument_keys,
                    limit=MAX_CAPABILITY_ARGUMENTS,
                )
            )
        )
        if len(semantic_argument_keys) != len(set(semantic_argument_keys)):
            raise ValueError("capability semantic argument keys must be unique")
        for argument_key in semantic_argument_keys:
            require_symbol("capability semantic argument key", argument_key)
        object.__setattr__(
            self,
            "semantic_argument_keys",
            semantic_argument_keys,
        )
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
                "argument_schema": CAPABILITY_ARGUMENT_SCHEMA,
                "name": self.name,
                "replay_evidence_id": self.replay_evidence_id,
                "replay_safety": self.replay_safety.value,
                "required_state_keys": list(self.required_state_keys),
                "semantic_argument_keys": list(self.semantic_argument_keys),
            },
        )

    def normalize_arguments(self, arguments: Any) -> dict[str, Any]:
        """Validate capability-owned semantic arguments for action identity."""

        if not isinstance(arguments, Mapping):
            raise TypeError("capability arguments must be a semantic mapping")
        supplied = materialize_bounded_iterable(
            "capability arguments",
            arguments.items(),
            limit=MAX_CAPABILITY_ARGUMENTS,
        )
        normalized: dict[str, Any] = {}
        for item in supplied:
            if not isinstance(item, tuple) or len(item) != 2:
                raise TypeError("capability argument items must be key/value pairs")
            name, value = item
            if not isinstance(name, str):
                raise TypeError("capability argument keys must be strings")
            require_symbol("capability argument key", name)
            if name in normalized:
                raise ValueError("capability argument keys must be unique")
            normalized[name] = value
        unknown = tuple(sorted(set(normalized) - set(self.semantic_argument_keys)))
        if unknown:
            raise ValueError(
                "capability arguments are not admitted by the schema: "
                + ",".join(unknown)
            )
        return CanonicalValue.from_value(normalized).to_value()

    def canonical_record(self) -> dict[str, object]:
        return {
            "argument_schema": CAPABILITY_ARGUMENT_SCHEMA,
            "available": self.available,
            "capability_id": self.capability_id,
            "contract_version": self.contract_version,
            "description": self.description,
            "name": self.name,
            "replay_evidence_id": self.replay_evidence_id,
            "replay_safety": self.replay_safety.value,
            "required_state_keys": list(self.required_state_keys),
            "semantic_argument_keys": list(self.semantic_argument_keys),
        }


@dataclass(frozen=True, slots=True)
class OrchestrationLimits:
    max_obligations: int = MAX_OBLIGATIONS
    max_epistemic_records: int = MAX_EPISTEMIC_RECORDS
    max_capabilities: int = MAX_CAPABILITIES
    max_batch_proposals: int = MAX_PROPOSALS_PER_BATCH
    max_history: int = MAX_HISTORY_EVENTS
    max_occurrence_owners: int = MAX_OCCURRENCE_OWNERS
    max_strategy_schemas: int = MAX_STRATEGY_SCHEMAS

    def __post_init__(self) -> None:
        for name, value, hard_limit in (
            ("max_obligations", self.max_obligations, MAX_OBLIGATIONS),
            (
                "max_epistemic_records",
                self.max_epistemic_records,
                MAX_EPISTEMIC_RECORDS,
            ),
            ("max_capabilities", self.max_capabilities, MAX_CAPABILITIES),
            (
                "max_batch_proposals",
                self.max_batch_proposals,
                MAX_PROPOSALS_PER_BATCH,
            ),
            ("max_history", self.max_history, MAX_HISTORY_EVENTS),
            (
                "max_occurrence_owners",
                self.max_occurrence_owners,
                MAX_OCCURRENCE_OWNERS,
            ),
            (
                "max_strategy_schemas",
                self.max_strategy_schemas,
                MAX_STRATEGY_SCHEMAS,
            ),
        ):
            require_bounded_positive_int(name, value, hard_limit)

    def canonical_record(self) -> dict[str, int]:
        return {
            "max_batch_proposals": self.max_batch_proposals,
            "max_capabilities": self.max_capabilities,
            "max_epistemic_records": self.max_epistemic_records,
            "max_history": self.max_history,
            "max_obligations": self.max_obligations,
            "max_occurrence_owners": self.max_occurrence_owners,
            "max_strategy_schemas": self.max_strategy_schemas,
        }


@dataclass(frozen=True, slots=True, init=False)
class Strategy:
    key: str
    schema: StrategySchema
    _parameters: CanonicalValue

    def __init__(
        self,
        key: str,
        parameters: Mapping[str, Any],
        *,
        schema: StrategySchema,
    ) -> None:
        require_symbol("strategy key", key)
        if not isinstance(schema, StrategySchema):
            raise TypeError("schema must be an orchestrator-owned StrategySchema")
        if schema.strategy_key != key:
            raise ValueError("strategy key must match its admitted schema")
        normalized_parameters = schema.normalize_parameters(parameters)
        object.__setattr__(self, "key", key)
        object.__setattr__(self, "schema", schema)
        object.__setattr__(
            self,
            "_parameters",
            CanonicalValue.from_value(normalized_parameters),
        )

    @property
    def parameters(self) -> Any:
        return self._parameters.to_value()

    @property
    def strategy_id(self) -> str:
        return domain_fingerprint(STRATEGY_ID_DOMAIN, self.canonical_record())

    def canonical_record(self) -> dict[str, object]:
        return {
            "key": self.key,
            "parameter_schema": STRATEGY_PARAMETER_SCHEMA,
            "parameter_schema_id": self.schema.schema_id,
            "parameters": self._parameters.to_value(),
        }


@dataclass(frozen=True, slots=True, init=False)
class ActionProposal:
    """A model proposal, kept distinct from an admitted action."""

    proposal_key: str
    capability: str
    target_obligation_ids: tuple[str, ...]
    required_state_keys: tuple[str, ...]
    occurrence_key: str | None
    _arguments: CanonicalValue
    _observational_metadata: CanonicalValue | None

    def __init__(
        self,
        proposal_key: str,
        capability: str,
        arguments: Any,
        *,
        target_obligation_ids: Iterable[str],
        required_state_keys: Iterable[str] = (),
        occurrence_key: str | None = None,
        observational_metadata: Any | None = None,
    ) -> None:
        require_symbol("proposal key", proposal_key)
        require_symbol("capability", capability)

        targets = tuple(
            sorted(
                materialize_bounded_iterable(
                    "target obligation ids",
                    target_obligation_ids,
                    limit=MAX_OBLIGATIONS,
                )
            )
        )
        if not targets:
            raise ValueError("an action proposal must target at least one obligation")
        if len(targets) != len(set(targets)):
            raise ValueError("target obligation ids must be unique")
        for target in targets:
            require_fingerprint("target obligation id", target)

        state_keys = tuple(
            sorted(
                materialize_bounded_iterable(
                    "required state keys",
                    required_state_keys,
                    limit=MAX_STATE_KEYS_PER_DECLARATION,
                )
            )
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
        object.__setattr__(
            self,
            "_observational_metadata",
            (
                None
                if observational_metadata is None
                else CanonicalValue.from_value(observational_metadata)
            ),
        )

    @property
    def arguments(self) -> Any:
        return self._arguments.to_value()

    @property
    def observational_metadata(self) -> Any | None:
        if self._observational_metadata is None:
            return None
        return self._observational_metadata.to_value()

    @property
    def proposal_id(self) -> str:
        return domain_fingerprint(PROPOSAL_ID_DOMAIN, self.canonical_record())

    def canonical_record(self) -> dict[str, object]:
        """Correctness-bearing proposal data; observations are excluded."""

        return {
            "arguments": self._arguments.to_value(),
            "capability": self.capability,
            "epistemic_class": "model_proposed",
            "occurrence_key": self.occurrence_key,
            "proposal_key": self.proposal_key,
            "required_state_keys": list(self.required_state_keys),
            "target_obligation_ids": list(self.target_obligation_ids),
        }

    def agent_record(self) -> dict[str, object]:
        """Agent-facing proposal data including non-correctness observations."""

        return {
            **self.canonical_record(),
            "observational_metadata": self.observational_metadata,
        }


@dataclass(frozen=True, slots=True)
class ProposalBatch:
    batch_key: str
    strategy: Strategy
    proposals: tuple[ActionProposal, ...]
    ordering: ProposalOrdering = ProposalOrdering.CANONICAL_INDEPENDENT

    def __post_init__(self) -> None:
        require_symbol("batch key", self.batch_key)
        if not isinstance(self.strategy, Strategy):
            raise TypeError("strategy must be a Strategy")
        if not isinstance(self.ordering, ProposalOrdering):
            raise TypeError("ordering must be a ProposalOrdering")
        proposals = materialize_bounded_iterable(
            "proposals",
            self.proposals,
            limit=MAX_PROPOSALS_PER_BATCH,
        )
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
        if self.ordering is ProposalOrdering.DECLARED_SEQUENCE:
            return self.proposals
        return tuple(sorted(self.proposals, key=lambda item: item.proposal_id))

    @property
    def batch_id(self) -> str:
        return domain_fingerprint(BATCH_ID_DOMAIN, self.canonical_record())

    def canonical_record(self) -> dict[str, object]:
        return {
            "batch_key": self.batch_key,
            "epistemic_class": "model_proposed",
            "ordering": self.ordering.value,
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
        supplied_recoveries = materialize_bounded_iterable(
            "recovery actions",
            self.recovery_actions,
            limit=len(RecoveryAction),
        )
        if any(not isinstance(action, RecoveryAction) for action in supplied_recoveries):
            raise TypeError("recovery_actions must contain RecoveryAction values")

        recoveries = tuple(
            sorted(
                set(supplied_recoveries),
                key=lambda action: action.value,
            )
        )
        blocking_ids = tuple(
            sorted(
                materialize_bounded_iterable(
                    "blocking obligation ids",
                    self.blocking_obligation_ids,
                    limit=MAX_OBLIGATIONS,
                )
            )
        )
        dependency_keys = tuple(
            sorted(
                materialize_bounded_iterable(
                    "dependency state keys",
                    self.dependency_state_keys,
                    limit=MAX_EPISTEMIC_RECORDS,
                )
            )
        )
        unresolved_keys = tuple(
            sorted(
                materialize_bounded_iterable(
                    "unresolved state keys",
                    self.unresolved_state_keys,
                    limit=MAX_EPISTEMIC_RECORDS,
                )
            )
        )
        invariant_ids = tuple(
            sorted(
                materialize_bounded_iterable(
                    "invariant ids",
                    self.invariant_ids,
                    limit=MAX_INVARIANT_IDS_PER_REJECTION,
                )
            )
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
        supplied_recoveries = materialize_bounded_iterable(
            "recovery actions",
            self.recovery_actions,
            limit=len(RecoveryAction),
        )
        if any(not isinstance(action, RecoveryAction) for action in supplied_recoveries):
            raise TypeError("recovery_actions must contain RecoveryAction values")
        require_nonnegative_int("logical_tick", self.logical_tick)
        object.__setattr__(
            self,
            "recovery_actions",
            tuple(
                sorted(
                    set(
                        supplied_recoveries
                    ),
                    key=lambda action: action.value,
                )
            ),
        )
        invariant_ids = tuple(
            sorted(
                materialize_bounded_iterable(
                    "invariant ids",
                    self.invariant_ids,
                    limit=MAX_INVARIANT_IDS_PER_REJECTION,
                )
            )
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
class OccurrenceOwnership:
    """Persistent ownership of an admitted occurrence-sensitive action key."""

    occurrence_key: str
    action_id: str
    proposal_id: str

    def __post_init__(self) -> None:
        require_symbol("occurrence key", self.occurrence_key)
        require_fingerprint("occurrence action id", self.action_id)
        require_fingerprint("occurrence proposal id", self.proposal_id)

    def canonical_record(self) -> dict[str, str]:
        return {
            "action_id": self.action_id,
            "occurrence_key": self.occurrence_key,
            "proposal_id": self.proposal_id,
        }


@dataclass(frozen=True, slots=True)
class AdmissionReceipt:
    batch_id: str
    strategy_id: str
    prior_state_id: str
    next_state_id: str
    status: BatchStatus
    proposal_ordering: ProposalOrdering
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
        if not isinstance(self.proposal_ordering, ProposalOrdering):
            raise TypeError("proposal_ordering must be a ProposalOrdering")
        require_nonnegative_int("logical_tick_start", self.logical_tick_start)
        require_nonnegative_int("logical_tick_end", self.logical_tick_end)
        if self.logical_tick_end < self.logical_tick_start:
            raise ValueError("logical tick cannot move backwards")
        decisions = materialize_bounded_iterable(
            "decisions",
            self.decisions,
            limit=MAX_PROPOSALS_PER_BATCH,
        )
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
            if (
                self.proposal_ordering is ProposalOrdering.CANONICAL_INDEPENDENT
                and tuple(item.proposal_id for item in decisions)
                != tuple(sorted(item.proposal_id for item in decisions))
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
            "proposal_ordering": self.proposal_ordering.value,
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
    occurrence_owners: tuple[OccurrenceOwnership, ...] = ()
    strategy_schemas: tuple[StrategySchema, ...] = ()

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

        supplied_capabilities = materialize_bounded_iterable(
            "capabilities",
            self.capabilities,
            limit=self.limits.max_capabilities,
        )
        if any(not isinstance(item, Capability) for item in supplied_capabilities):
            raise TypeError("capabilities must contain Capability records")
        capabilities = tuple(sorted(supplied_capabilities, key=lambda item: item.name))
        if len(capabilities) > self.limits.max_capabilities:
            raise ValueError("capability registry exceeds max_capabilities")
        names = [item.name for item in capabilities]
        if len(names) != len(set(names)):
            raise ValueError("capability names must be unique")
        object.__setattr__(self, "capabilities", capabilities)

        history = materialize_bounded_iterable(
            "history",
            self.history,
            limit=self.limits.max_history,
        )
        if len(history) > self.limits.max_history:
            raise ValueError("orchestration history exceeds max_history")
        for event_id in history:
            require_fingerprint("history event id", event_id)
        object.__setattr__(self, "history", history)

        supplied_owners = materialize_bounded_iterable(
            "occurrence owners",
            self.occurrence_owners,
            limit=self.limits.max_occurrence_owners,
        )
        if any(not isinstance(item, OccurrenceOwnership) for item in supplied_owners):
            raise TypeError(
                "occurrence_owners must contain OccurrenceOwnership records"
            )
        owners = tuple(sorted(supplied_owners, key=lambda item: item.occurrence_key))
        if len(owners) > self.limits.max_occurrence_owners:
            raise ValueError("occurrence ownership exceeds max_occurrence_owners")
        occurrence_keys = [item.occurrence_key for item in owners]
        if len(occurrence_keys) != len(set(occurrence_keys)):
            raise ValueError("occurrence ownership keys must be unique")
        object.__setattr__(self, "occurrence_owners", owners)

        supplied_schemas = materialize_bounded_iterable(
            "strategy schemas",
            self.strategy_schemas,
            limit=self.limits.max_strategy_schemas,
        )
        if any(not isinstance(item, StrategySchema) for item in supplied_schemas):
            raise TypeError("strategy_schemas must contain StrategySchema records")
        schemas = tuple(sorted(supplied_schemas, key=lambda item: item.strategy_key))
        schema_keys = [item.strategy_key for item in schemas]
        if len(schema_keys) != len(set(schema_keys)):
            raise ValueError("strategy schema keys must be unique")
        object.__setattr__(self, "strategy_schemas", schemas)

    @classmethod
    def create(
        cls,
        obligations: Iterable[Obligation],
        *,
        epistemic_state: EpistemicState | None = None,
        capabilities: Iterable[Capability] = (),
        strategy_schemas: Iterable[StrategySchema] = (),
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
            capabilities=materialize_bounded_iterable(
                "capabilities",
                capabilities,
                limit=active_limits.max_capabilities,
            ),
            strategy_schemas=materialize_bounded_iterable(
                "strategy schemas",
                strategy_schemas,
                limit=active_limits.max_strategy_schemas,
            ),
            limits=active_limits,
        )

    @property
    def state_id(self) -> str:
        return domain_fingerprint(STATE_ID_DOMAIN, self.canonical_record())

    def capability(self, name: str) -> Capability | None:
        require_symbol("capability name", name)
        return next((item for item in self.capabilities if item.name == name), None)

    def strategy_schema(self, key: str) -> StrategySchema | None:
        require_symbol("strategy key", key)
        return next(
            (item for item in self.strategy_schemas if item.strategy_key == key),
            None,
        )

    def canonical_record(self) -> dict[str, object]:
        return {
            "capabilities": [item.canonical_record() for item in self.capabilities],
            "epistemic_state": self.epistemic_state.identity_record(),
            "history": list(self.history),
            "limits": self.limits.canonical_record(),
            "logical_clock": {
                "profile": LOGICAL_CLOCK_PROFILE,
                "tick": self.logical_tick,
            },
            "obligations": self.obligations.canonical_record(),
            "occurrence_owners": [
                item.canonical_record() for item in self.occurrence_owners
            ],
            "protocol": AGENT_PROTOCOL,
            "strategy_schemas": [
                item.canonical_record() for item in self.strategy_schemas
            ],
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
                "block_reason": obligation.block_reason,
                "description": obligation.description,
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
                "occurrence_owner_slots_remaining": (
                    self.limits.max_occurrence_owners - len(self.occurrence_owners)
                ),
                "strategy_schema_slots_remaining": (
                    self.limits.max_strategy_schemas - len(self.strategy_schemas)
                ),
            },
            "canonical_state_identity": self.state_id,
            "epistemic_state": self.epistemic_state.projection(),
            "logical_clock": {
                "profile": LOGICAL_CLOCK_PROFILE,
                "tick": self.logical_tick,
            },
            "obligations": obligation_groups,
            "occurrence_owners": [
                item.canonical_record() for item in self.occurrence_owners
            ],
            "protocol": AGENT_PROTOCOL,
            "strategy_schemas": [
                item.canonical_record() for item in self.strategy_schemas
            ],
        }

    def advance(
        self,
        *,
        logical_tick: int,
        event_ids: Iterable[str],
        occurrence_owners: Iterable[OccurrenceOwnership] | None = None,
    ) -> OrchestrationState:
        require_nonnegative_int("logical_tick", logical_tick)
        if logical_tick < self.logical_tick:
            raise ValueError("logical tick cannot move backwards")
        additions = materialize_bounded_iterable(
            "event ids",
            event_ids,
            limit=MAX_PROPOSALS_PER_BATCH,
        )
        for event_id in additions:
            require_fingerprint("event id", event_id)
        if logical_tick - self.logical_tick != len(additions):
            raise ValueError("each orchestration event must consume one logical tick")
        history = (*self.history, *additions)[-self.limits.max_history :]
        next_occurrence_owners = (
            self.occurrence_owners
            if occurrence_owners is None
            else materialize_bounded_iterable(
                "occurrence owners",
                occurrence_owners,
                limit=self.limits.max_occurrence_owners,
            )
        )
        return replace(
            self,
            logical_tick=logical_tick,
            history=history,
            occurrence_owners=next_occurrence_owners,
        )


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


def _rejected_batch_transition(
    state: OrchestrationState,
    batch: ProposalBatch,
    *,
    reason: RejectionReason,
    recovery_actions: tuple[RecoveryAction, ...],
) -> AdmissionTransition:
    """Consume one logical tick for a canonical batch-level rejection."""

    prior_state_id = state.state_id
    logical_tick = state.logical_tick + 1
    rejection = BatchRejection(
        reason=reason,
        recovery_actions=recovery_actions,
        logical_tick=logical_tick,
        invariant_ids=_REJECTION_INVARIANTS[reason],
    )
    batch_id = batch.batch_id
    event_id = _event_id(
        batch_id,
        {"batch_rejection": rejection.canonical_record()},
    )
    next_state = state.advance(
        logical_tick=logical_tick,
        event_ids=(event_id,),
    )
    receipt = AdmissionReceipt(
        batch_id=batch_id,
        strategy_id=batch.strategy.strategy_id,
        prior_state_id=prior_state_id,
        next_state_id=next_state.state_id,
        status=BatchStatus.REJECTED,
        proposal_ordering=batch.ordering,
        logical_tick_start=state.logical_tick,
        logical_tick_end=logical_tick,
        batch_rejection=rejection,
    )
    return AdmissionTransition(next_state=next_state, receipt=receipt)


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
    semantic_arguments: Mapping[str, Any],
    occurrence_key: str | None,
    dependency_state_id: str,
) -> str:
    record: dict[str, object] = {
        "arguments": dict(semantic_arguments),
        "capability_id": capability.capability_id,
        "dependency_state_id": dependency_state_id,
    }
    if capability.replay_safety is ReplaySafety.OCCURRENCE_SENSITIVE:
        record["occurrence_key"] = occurrence_key
    return domain_fingerprint(ACTION_ID_DOMAIN, record)


def admit_batch(
    state: OrchestrationState,
    batch: ProposalBatch,
) -> AdmissionTransition:
    """Pure deterministic proposal-to-admission transition.

    Every processed proposal advances the logical clock exactly once. A
    rejected batch-level policy check advances it once as a canonical batch
    rejection. No wall-clock value participates in admitted action identity.
    """

    if not isinstance(state, OrchestrationState):
        raise TypeError("state must be an OrchestrationState")
    if not isinstance(batch, ProposalBatch):
        raise TypeError("batch must be a ProposalBatch")

    admitted_strategy_schema = state.strategy_schema(batch.strategy.key)
    if (
        admitted_strategy_schema is None
        or admitted_strategy_schema.schema_id != batch.strategy.schema.schema_id
    ):
        return _rejected_batch_transition(
            state,
            batch,
            reason=RejectionReason.STRATEGY_SCHEMA_NOT_ADMITTED,
            recovery_actions=(RecoveryAction.USE_ADMITTED_STRATEGY_SCHEMA,),
        )

    prior_state_id = state.state_id
    if len(batch.proposals) > state.limits.max_batch_proposals:
        return _rejected_batch_transition(
            state,
            batch,
            reason=RejectionReason.BATCH_LIMIT_EXCEEDED,
            recovery_actions=(RecoveryAction.SPLIT_BATCH,),
        )

    decisions: list[AdmissionDecision] = []
    event_ids: list[str] = []
    replay_safe_actions: dict[str, str] = {}
    occurrence_owners = {
        item.occurrence_key: item for item in state.occurrence_owners
    }
    logical_tick = state.logical_tick

    for proposal in batch.ordered_proposals:
        logical_tick += 1
        capability = state.capability(proposal.capability)
        dependency_state_keys = proposal.required_state_keys
        semantic_arguments: dict[str, Any] | None = None
        decision: AdmissionDecision | None = None
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
            try:
                semantic_arguments = capability.normalize_arguments(
                    proposal.arguments
                )
            except (TypeError, ValueError):
                decision = _rejected_decision(
                    proposal,
                    logical_tick=logical_tick,
                    reason=RejectionReason.ARGUMENT_SCHEMA_MISMATCH,
                    recovery_actions=(RecoveryAction.USE_ADMITTED_ARGUMENT_SCHEMA,),
                    dependency_state_keys=dependency_state_keys,
                )
            if decision is None and (
                capability.replay_safety is not ReplaySafety.CACHEABLE_READ
                and batch.ordering is not ProposalOrdering.DECLARED_SEQUENCE
            ):
                decision = _rejected_decision(
                    proposal,
                    logical_tick=logical_tick,
                    reason=RejectionReason.ORDERING_CONTRACT_REQUIRED,
                    recovery_actions=(RecoveryAction.USE_DECLARED_SEQUENCE,),
                    dependency_state_keys=dependency_state_keys,
                )
            if decision is None:
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
            assert semantic_arguments is not None
            dependency_state_id = state.epistemic_state.dependency_digest(
                dependency_state_keys
            )
            action_id = _action_id(
                capability,
                semantic_arguments,
                proposal.occurrence_key,
                dependency_state_id,
            )
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
                elif (
                    len(occurrence_owners)
                    == state.limits.max_occurrence_owners
                ):
                    decision = _rejected_decision(
                        proposal,
                        logical_tick=logical_tick,
                        reason=RejectionReason.OCCURRENCE_REGISTRY_FULL,
                        recovery_actions=(RecoveryAction.REQUEST_NEW_BOUNDED_SCOPE,),
                        dependency_state_keys=dependency_state_keys,
                    )
                else:
                    occurrence_owners[proposal.occurrence_key] = OccurrenceOwnership(
                        occurrence_key=proposal.occurrence_key,
                        action_id=action_id,
                        proposal_id=proposal.proposal_id,
                    )
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

    next_state = state.advance(
        logical_tick=logical_tick,
        event_ids=event_ids,
        occurrence_owners=occurrence_owners.values(),
    )
    receipt = AdmissionReceipt(
        batch_id=batch.batch_id,
        strategy_id=batch.strategy.strategy_id,
        prior_state_id=prior_state_id,
        next_state_id=next_state.state_id,
        status=BatchStatus.PROCESSED,
        proposal_ordering=batch.ordering,
        logical_tick_start=state.logical_tick,
        logical_tick_end=logical_tick,
        decisions=tuple(decisions),
    )
    return AdmissionTransition(next_state=next_state, receipt=receipt)
