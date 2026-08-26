from __future__ import annotations

import json
from pathlib import Path

import pytest

from ibae import (
    MAX_PROPOSALS_PER_BATCH,
    ActionProposal,
    AuthorityLayer,
    BatchStatus,
    Capability,
    DecisionStatus,
    EpistemicClass,
    EpistemicRecord,
    EpistemicState,
    Obligation,
    ObligationReadiness,
    ObligationRegistry,
    ObligationStatus,
    ObservationProvenance,
    OrchestrationLimits,
    OrchestrationState,
    ProposalBatch,
    ProposalOrdering,
    RecoveryAction,
    RejectionReason,
    ReplaySafety,
    Strategy,
    StrategyParameterSpec,
    StrategySchema,
    StrategyValueKind,
    admit_batch,
    canonical_json,
    canonical_obligation_id,
    domain_fingerprint,
)
from ibae.conformance import v0_2_reference_fixture

_DEFAULT_STRATEGY_SCHEMA = StrategySchema(
    "default",
    (
        StrategyParameterSpec(
            "version",
            StrategyValueKind.BOUNDED_INTEGER,
            minimum=1,
            maximum=1,
        ),
    ),
)
_STABLE_STRATEGY_SCHEMA = StrategySchema(
    "stable",
    (
        StrategyParameterSpec(
            "steps",
            StrategyValueKind.SYMBOL_LIST,
            required=False,
            allowed_symbols=("one",),
        ),
    ),
)
_SEMANTIC_STRATEGY_SCHEMA = StrategySchema(
    "semantic",
    (
        StrategyParameterSpec(
            "algorithm",
            StrategyValueKind.SYMBOL,
            allowed_symbols=("stable",),
        ),
        StrategyParameterSpec(
            "version",
            StrategyValueKind.BOUNDED_INTEGER,
            minimum=1,
            maximum=1,
        ),
    ),
)


def _provenance(*, revision: int = 1, reused: bool = False) -> ObservationProvenance:
    return ObservationProvenance(
        source="test.read",
        source_identity=domain_fingerprint(
            "ibae.test-source.v1", {"revision": revision}
        ),
        dependency_identity=domain_fingerprint(
            "ibae.test-dependency.v1", {"revision": revision}
        ),
        reused=reused,
    )


def _ready_state(
    *,
    limits: OrchestrationLimits | None = None,
    epistemic_state: EpistemicState | None = None,
    extra_obligations: tuple[Obligation, ...] = (),
    capabilities: tuple[Capability, ...] | None = None,
    strategy_schemas: tuple[StrategySchema, ...] | None = None,
) -> tuple[OrchestrationState, Obligation]:
    obligation = Obligation("ready", "Perform ready work.")
    active_capabilities = capabilities or (
        Capability("read", ReplaySafety.CACHEABLE_READ, "Read deterministic state."),
        Capability(
            "write",
            ReplaySafety.OCCURRENCE_SENSITIVE,
            "Perform one occurrence-identified mutation.",
        ),
    )
    active_strategy_schemas = strategy_schemas or (_DEFAULT_STRATEGY_SCHEMA,)
    state = OrchestrationState.create(
        (obligation, *extra_obligations),
        limits=limits,
        epistemic_state=epistemic_state,
        capabilities=active_capabilities,
        strategy_schemas=active_strategy_schemas,
    )
    return state, obligation


def _batch(
    *proposals: ActionProposal,
    key: str = "batch",
    ordering: ProposalOrdering = ProposalOrdering.CANONICAL_INDEPENDENT,
) -> ProposalBatch:
    return ProposalBatch(
        key,
        Strategy(
            "default",
            {"version": 1},
            schema=_DEFAULT_STRATEGY_SCHEMA,
        ),
        proposals,
        ordering=ordering,
    )


def _proposal(
    obligation: Obligation,
    *,
    key: str = "proposal",
    capability: str = "read",
    arguments: object | None = None,
    required_state_keys: tuple[str, ...] = (),
    occurrence_key: str | None = None,
) -> ActionProposal:
    return ActionProposal(
        key,
        capability,
        {} if arguments is None else arguments,
        target_obligation_ids=(obligation.obligation_id,),
        required_state_keys=required_state_keys,
        occurrence_key=occurrence_key,
    )


def test_domain_fingerprints_separate_equal_payloads() -> None:
    payload = {"same": True}
    assert domain_fingerprint("ibae.test-a.v1", payload) != domain_fingerprint(
        "ibae.test-b.v1", payload
    )
    with pytest.raises(ValueError):
        domain_fingerprint("unversioned", payload)


def test_obligation_ids_are_stable_and_key_derived() -> None:
    first = Obligation("inspect", "Inspect state.")
    renamed_description = Obligation("inspect", "Inspect canonical state.")
    other = Obligation("verify", "Inspect state.")
    assert first.obligation_id == renamed_description.obligation_id
    assert first.obligation_id == canonical_obligation_id("inspect")
    assert first.obligation_id != other.obligation_id


def test_obligation_registry_ready_set_and_topology_are_deterministic() -> None:
    root = Obligation("root", "Root obligation.")
    left = Obligation("left", "Left obligation.", dependency_ids=(root.obligation_id,))
    right = Obligation(
        "right", "Right obligation.", dependency_ids=(root.obligation_id,)
    )
    registry_a = ObligationRegistry.from_iterable((right, root, left))
    registry_b = ObligationRegistry.from_iterable((left, right, root))
    assert registry_a.canonical_record() == registry_b.canonical_record()
    assert registry_a.ready_ids == (root.obligation_id,)
    assert registry_a.topological_ids == registry_b.topological_ids
    assert registry_a.readiness(left.obligation_id) is (
        ObligationReadiness.DEPENDENCY_BLOCKED
    )


def test_obligation_registry_rejects_unknown_dependencies_and_cycles() -> None:
    missing = domain_fingerprint("ibae.test-missing.v1", {"id": 1})
    with pytest.raises(ValueError, match="unknown dependencies"):
        ObligationRegistry.from_iterable(
            (Obligation("orphan", "Orphan.", dependency_ids=(missing,)),)
        )

    a_id = canonical_obligation_id("cycle-a")
    b_id = canonical_obligation_id("cycle-b")
    a = Obligation("cycle-a", "Cycle A.", dependency_ids=(b_id,))
    b = Obligation("cycle-b", "Cycle B.", dependency_ids=(a_id,))
    with pytest.raises(ValueError, match="dependency cycle"):
        ObligationRegistry.from_iterable((a, b))


def test_obligation_status_updates_preserve_dependency_consistency() -> None:
    root = Obligation("root-status", "Root status.")
    child = Obligation(
        "child-status", "Child status.", dependency_ids=(root.obligation_id,)
    )
    registry = ObligationRegistry.from_iterable((root, child))
    with pytest.raises(ValueError, match="unsatisfied dependencies"):
        registry.with_status(child.obligation_id, ObligationStatus.SATISFIED)

    registry = registry.with_status(root.obligation_id, ObligationStatus.SATISFIED)
    assert registry.ready_ids == (child.obligation_id,)
    registry = registry.with_status(child.obligation_id, ObligationStatus.SATISFIED)
    assert registry.ready_ids == ()


def test_blocked_obligations_require_explicit_reason() -> None:
    with pytest.raises(ValueError, match="require a block reason"):
        Obligation("blocked", "Blocked.", status=ObligationStatus.BLOCKED)
    item = Obligation(
        "blocked",
        "Blocked.",
        status=ObligationStatus.BLOCKED,
        block_reason="external gate",
    )
    registry = ObligationRegistry.from_iterable((item,))
    assert registry.readiness(item.obligation_id) is (
        ObligationReadiness.EXPLICITLY_BLOCKED
    )


def test_epistemic_classes_are_explicit_and_projected_separately() -> None:
    state = EpistemicState.from_iterable(
        (
            EpistemicRecord(
                "observed", EpistemicClass.OBSERVED, 1, provenance=_provenance()
            ),
            EpistemicRecord(
                "derived",
                EpistemicClass.DERIVED,
                2,
                dependencies=("observed",),
            ),
            EpistemicRecord(
                "proposed", EpistemicClass.MODEL_PROPOSED, {"candidate": True}
            ),
            EpistemicRecord("unknown", EpistemicClass.UNKNOWN),
        )
    )
    projection = state.projection()
    assert set(projection) == {
        "observed",
        "derived",
        "model_proposed",
        "unknown",
    }
    assert projection["unknown"][0]["key"] == "unknown"
    assert "value" not in projection["unknown"][0]
    assert projection["model_proposed"][0]["epistemic_class"] == "model_proposed"


def test_unknown_is_not_false_and_observation_provenance_is_required() -> None:
    unknown = EpistemicRecord("answer", EpistemicClass.UNKNOWN)
    with pytest.raises(ValueError, match="have no value"):
        _ = unknown.value
    with pytest.raises(ValueError, match="cannot carry a value"):
        EpistemicRecord("answer", EpistemicClass.UNKNOWN, False)
    with pytest.raises(ValueError, match="require observation provenance"):
        EpistemicRecord("observation", EpistemicClass.OBSERVED, 1)


def test_epistemic_values_are_mutation_isolated() -> None:
    source = {"items": [1, 2]}
    record = EpistemicRecord("isolated", EpistemicClass.MODEL_PROPOSED, source)
    source["items"].append(3)
    returned = record.value
    returned["items"].append(4)
    assert record.value == {"items": [1, 2]}


def test_epistemic_dependency_digest_includes_transitive_state() -> None:
    def build(revision: int) -> EpistemicState:
        return EpistemicState.from_iterable(
            (
                EpistemicRecord(
                    "source",
                    EpistemicClass.OBSERVED,
                    {"revision": revision},
                    provenance=_provenance(revision=revision),
                ),
                EpistemicRecord(
                    "derived",
                    EpistemicClass.DERIVED,
                    "same-derived-value",
                    dependencies=("source",),
                ),
            )
        )

    assert build(1).dependency_digest(("derived",)) != build(2).dependency_digest(
        ("derived",)
    )


def test_observation_reuse_path_does_not_change_correctness_identity() -> None:
    def build(reused: bool) -> tuple[EpistemicRecord, EpistemicState]:
        record = EpistemicRecord(
            "source",
            EpistemicClass.OBSERVED,
            {"revision": 1},
            provenance=_provenance(reused=reused),
        )
        return record, EpistemicState.from_iterable((record,))

    cold_record, cold_epistemic = build(False)
    reused_record, reused_epistemic = build(True)
    assert cold_record.record_id == reused_record.record_id
    assert cold_epistemic.dependency_digest(("source",)) == (
        reused_epistemic.dependency_digest(("source",))
    )
    assert cold_epistemic.identity_record() == reused_epistemic.identity_record()
    assert cold_epistemic.projection() != reused_epistemic.projection()
    assert reused_epistemic.projection()["observed"][0]["provenance"]["reused"]

    cold_state, cold_obligation = _ready_state(epistemic_state=cold_epistemic)
    reused_state, reused_obligation = _ready_state(epistemic_state=reused_epistemic)
    cold_action = admit_batch(
        cold_state,
        _batch(_proposal(cold_obligation, required_state_keys=("source",))),
    ).receipt.decisions[0].action_id
    reused_action = admit_batch(
        reused_state,
        _batch(_proposal(reused_obligation, required_state_keys=("source",))),
    ).receipt.decisions[0].action_id
    assert cold_state.state_id == reused_state.state_id
    assert cold_action == reused_action


def test_derived_state_cannot_claim_known_value_from_unknown_input() -> None:
    with pytest.raises(ValueError, match="unresolved dependencies"):
        EpistemicState.from_iterable(
            (
                EpistemicRecord("source", EpistemicClass.UNKNOWN),
                EpistemicRecord(
                    "derived",
                    EpistemicClass.DERIVED,
                    1,
                    dependencies=("source",),
                ),
            )
        )


def test_model_proposed_state_cannot_resolve_admission_dependencies() -> None:
    epistemic = EpistemicState.from_iterable(
        (
            EpistemicRecord(
                "candidate", EpistemicClass.MODEL_PROPOSED, {"approved": True}
            ),
        )
    )
    state, obligation = _ready_state(epistemic_state=epistemic)
    proposal = _proposal(obligation, required_state_keys=("candidate",))
    decision = admit_batch(state, _batch(proposal)).receipt.decisions[0]
    assert decision.rejection_reason is RejectionReason.UNKNOWN_STATE
    assert decision.unresolved_state_keys == ("candidate",)

    with pytest.raises(ValueError, match="unresolved dependencies"):
        EpistemicState.from_iterable(
            (
                EpistemicRecord(
                    "candidate", EpistemicClass.MODEL_PROPOSED, {"approved": True}
                ),
                EpistemicRecord(
                    "derived-from-candidate",
                    EpistemicClass.DERIVED,
                    True,
                    dependencies=("candidate",),
                ),
            )
        )


def test_strategy_and_proposal_payloads_are_mutation_isolated() -> None:
    state, obligation = _ready_state()
    arguments = {"items": [1]}
    parameters = {"steps": ["one"]}
    strategy = Strategy(
        "stable",
        parameters,
        schema=_STABLE_STRATEGY_SCHEMA,
    )
    proposal = _proposal(obligation, arguments=arguments)
    proposal_id = proposal.proposal_id
    strategy_id = strategy.strategy_id

    arguments["items"].append(2)
    parameters["steps"].append("two")
    proposal.arguments["items"].append(3)
    strategy.parameters["steps"].append("two")
    assert proposal.arguments == {"items": [1]}
    assert strategy.parameters == {"steps": ["one"]}
    assert proposal.proposal_id == proposal_id
    assert strategy.strategy_id == strategy_id
    assert state.logical_tick == 0


@pytest.mark.parametrize(
    "parameters",
    (
        {"elapsed": 1.5},
        {"runtime": {"wall_clock": "2026-08-26T10:00:00Z"}},
        {"started-at": "2026-08-26T10:00:00Z"},
        {"elapsedSeconds": 3},
        {"run_started": "2026-08-26T10:00:00Z"},
        {"epoch": 1787720400},
        {"utc_now": "2026-08-26T10:00:00Z"},
    ),
)
def test_strategy_identity_rejects_observational_timing_metadata(
    parameters: object,
) -> None:
    with pytest.raises(ValueError, match="not allowed by the schema"):
        Strategy(
            "invalid-timing",
            parameters,
            schema=StrategySchema("invalid-timing"),
        )

    strategy = Strategy(
        "semantic",
        {"algorithm": "stable", "version": 1},
        schema=_SEMANTIC_STRATEGY_SCHEMA,
    )
    assert strategy.canonical_record()["parameter_schema"] == (
        "IBAE-STRATEGY-PARAMETERS-V1"
    )
    assert strategy.canonical_record()["parameter_schema_id"] == (
        _SEMANTIC_STRATEGY_SCHEMA.schema_id
    )


def test_strategy_schema_identity_and_value_constraints_are_authoritative() -> None:
    revised = StrategySchema(
        "semantic",
        _SEMANTIC_STRATEGY_SCHEMA.parameter_specs,
        contract_version=2,
    )
    first = Strategy(
        "semantic",
        {"algorithm": "stable", "version": 1},
        schema=_SEMANTIC_STRATEGY_SCHEMA,
    )
    second = Strategy(
        "semantic",
        {"algorithm": "stable", "version": 1},
        schema=revised,
    )
    assert first.strategy_id != second.strategy_id
    with pytest.raises(ValueError, match="between 1 and 1"):
        Strategy(
            "semantic",
            {"algorithm": "stable", "version": 1787720400},
            schema=_SEMANTIC_STRATEGY_SCHEMA,
        )


def test_strategy_schema_must_be_admitted_before_any_batch_identity_is_used() -> None:
    state, obligation = _ready_state()
    forged_schema = StrategySchema(
        "default",
        (
            StrategyParameterSpec(
                "epoch",
                StrategyValueKind.BOUNDED_INTEGER,
                minimum=0,
                maximum=2_000_000_000,
            ),
        ),
    )
    batch = ProposalBatch(
        "forged-strategy-schema",
        Strategy(
            "default",
            {"epoch": 1_787_720_400},
            schema=forged_schema,
        ),
        (_proposal(obligation),),
    )
    with pytest.raises(ValueError, match="not admitted by the orchestration state"):
        admit_batch(state, batch)
    assert state.logical_tick == 0
    assert state.history == ()
    assert state.strategy_schema("default") is _DEFAULT_STRATEGY_SCHEMA


def test_proposal_batch_normalizes_caller_owned_sequence() -> None:
    _, obligation = _ready_state()
    first = _proposal(obligation, key="first")
    proposals = [first]
    batch = ProposalBatch(
        "isolated-batch",
        Strategy("stable", {}, schema=_STABLE_STRATEGY_SCHEMA),
        proposals,
    )
    proposals.append(_proposal(obligation, key="second", arguments={"n": 2}))
    assert batch.proposals == (first,)


def test_proposal_batch_stops_consuming_at_the_protocol_hard_limit() -> None:
    _, obligation = _ready_state()
    consumed = 0

    def proposals() -> object:
        nonlocal consumed
        for index in range(MAX_PROPOSALS_PER_BATCH + 100):
            consumed += 1
            yield _proposal(
                obligation,
                key=f"bounded-{index}",
                arguments={"index": index},
            )

    with pytest.raises(ValueError, match="hard limit"):
        ProposalBatch(
            "bounded",
            Strategy("stable", {}, schema=_STABLE_STRATEGY_SCHEMA),
            proposals(),
        )
    assert consumed == MAX_PROPOSALS_PER_BATCH + 1

    with pytest.raises(ValueError, match="protocol hard limit"):
        OrchestrationLimits(max_batch_proposals=MAX_PROPOSALS_PER_BATCH + 1)


def test_all_model_facing_collection_boundaries_use_bounded_consumption() -> None:
    consumed: dict[str, int] = {}

    def stream(name: str, count: int, factory: object) -> object:
        for index in range(count):
            consumed[name] = consumed.get(name, 0) + 1
            yield factory(index)

    obligation_id = canonical_obligation_id("bounded-target")
    with pytest.raises(ValueError, match="hard limit"):
        Obligation(
            "bounded-dependencies",
            "Bound dependency input.",
            dependency_ids=stream(
                "obligation-dependencies",
                200,
                lambda index: domain_fingerprint(
                    "ibae.test-obligation-dependency.v1", {"index": index}
                ),
            ),
        )
    assert consumed["obligation-dependencies"] == 128

    with pytest.raises(ValueError, match="hard limit"):
        EpistemicRecord(
            "bounded-derived",
            EpistemicClass.DERIVED,
            True,
            dependencies=stream(
                "epistemic-dependencies",
                300,
                lambda index: f"dependency-{index}",
            ),
        )
    assert consumed["epistemic-dependencies"] == 256

    with pytest.raises(ValueError, match="hard limit"):
        Capability(
            "bounded-capability",
            ReplaySafety.CACHEABLE_READ,
            "Bound capability dependencies.",
            required_state_keys=stream(
                "capability-state-keys",
                200,
                lambda index: f"state-{index}",
            ),
        )
    assert consumed["capability-state-keys"] == 129

    with pytest.raises(ValueError, match="hard limit"):
        ActionProposal(
            "bounded-targets",
            "read",
            {},
            target_obligation_ids=stream(
                "proposal-targets",
                200,
                lambda index: domain_fingerprint(
                    "ibae.test-proposal-target.v1", {"index": index}
                ),
            ),
        )
    assert consumed["proposal-targets"] == 129

    with pytest.raises(ValueError, match="hard limit"):
        ActionProposal(
            "bounded-state",
            "read",
            {},
            target_obligation_ids=(obligation_id,),
            required_state_keys=stream(
                "proposal-state-keys",
                200,
                lambda index: f"state-{index}",
            ),
        )
    assert consumed["proposal-state-keys"] == 129

    with pytest.raises(ValueError, match="hard limit"):
        ObligationRegistry.from_iterable(
            stream(
                "obligation-registry",
                10,
                lambda index: Obligation(
                    f"registry-{index}", f"Registry obligation {index}."
                ),
            ),
            max_obligations=2,
        )
    assert consumed["obligation-registry"] == 3

    with pytest.raises(ValueError, match="hard limit"):
        EpistemicState.from_iterable(
            stream(
                "epistemic-registry",
                10,
                lambda index: EpistemicRecord(
                    f"record-{index}", EpistemicClass.MODEL_PROPOSED, index
                ),
            ),
            max_records=2,
        )
    assert consumed["epistemic-registry"] == 3

    with pytest.raises(ValueError, match="hard limit"):
        OrchestrationState.create(
            (Obligation("bounded-state-root", "Bound state registry."),),
            capabilities=stream(
                "capability-registry",
                10,
                lambda index: Capability(
                    f"capability-{index}",
                    ReplaySafety.CACHEABLE_READ,
                    f"Capability {index}.",
                ),
            ),
            limits=OrchestrationLimits(max_capabilities=2),
        )
    assert consumed["capability-registry"] == 3

    with pytest.raises(ValueError, match="hard limit"):
        OrchestrationState.create(
            (Obligation("bounded-schema-root", "Bound schema registry."),),
            strategy_schemas=stream(
                "strategy-schema-registry",
                10,
                lambda index: StrategySchema(f"schema-{index}"),
            ),
            limits=OrchestrationLimits(max_strategy_schemas=2),
        )
    assert consumed["strategy-schema-registry"] == 3

    with pytest.raises(ValueError, match="hard limit"):
        StrategySchema(
            "bounded-schema",
            stream(
                "strategy-specs",
                100,
                lambda index: StrategyParameterSpec(
                    f"parameter-{index}",
                    StrategyValueKind.BOOLEAN,
                    required=False,
                ),
            ),
        )
    assert consumed["strategy-specs"] == 33

    with pytest.raises(ValueError, match="hard limit"):
        Strategy(
            "stable",
            {f"parameter-{index}": True for index in range(40)},
            schema=_STABLE_STRATEGY_SCHEMA,
        )
    with pytest.raises(ValueError, match="hard limit"):
        Strategy(
            "stable",
            {"steps": ["one"] * 65},
            schema=_STABLE_STRATEGY_SCHEMA,
        )


def test_canonical_model_payloads_have_shape_depth_and_byte_bounds() -> None:
    obligation = Obligation("payload-bound", "Bound canonical payloads.")
    targets = (obligation.obligation_id,)

    with pytest.raises(ValueError, match="canonical sequence items.*hard limit"):
        ActionProposal(
            "oversized-sequence",
            "read",
            [0] * 1_025,
            target_obligation_ids=targets,
        )
    with pytest.raises(ValueError, match="canonical mapping items.*hard limit"):
        ActionProposal(
            "oversized-mapping",
            "read",
            {f"key-{index}": index for index in range(1_025)},
            target_obligation_ids=targets,
        )

    deep: object = None
    for _ in range(34):
        deep = [deep]
    with pytest.raises(ValueError, match="maximum depth"):
        EpistemicRecord("deep-value", EpistemicClass.MODEL_PROPOSED, deep)

    with pytest.raises(ValueError, match="maximum node count"):
        EpistemicRecord(
            "many-nodes",
            EpistemicClass.MODEL_PROPOSED,
            [[0, 1, 2, 3] for _ in range(1_024)],
        )
    with pytest.raises(ValueError, match="maximum UTF-8 bytes 65536"):
        EpistemicRecord(
            "long-string",
            EpistemicClass.MODEL_PROPOSED,
            "x" * 65_537,
        )
    with pytest.raises(ValueError, match="maximum UTF-8 bytes 262144"):
        EpistemicRecord(
            "large-value",
            EpistemicClass.MODEL_PROPOSED,
            {f"chunk-{index}": "x" * 65_000 for index in range(5)},
        )
    with pytest.raises(ValueError, match="maximum bit length 256"):
        EpistemicRecord(
            "large-integer",
            EpistemicClass.MODEL_PROPOSED,
            1 << 256,
        )


def test_admission_is_byte_identical_across_input_orderings() -> None:
    state, obligation = _ready_state()
    first = _proposal(obligation, key="first", arguments={"b": 2, "a": 1})
    second = _proposal(obligation, key="second", arguments={"path": "b"})
    batch_a = _batch(first, second, key="order-independent")
    batch_b = _batch(second, first, key="order-independent")

    transition_a = admit_batch(state, batch_a)
    transition_b = admit_batch(state, batch_b)
    assert batch_a.batch_id == batch_b.batch_id
    assert canonical_json(transition_a.receipt.canonical_record()) == canonical_json(
        transition_b.receipt.canonical_record()
    )
    assert transition_a.next_state.state_id == transition_b.next_state.state_id
    proposal_ids = [decision.proposal_id for decision in transition_a.receipt.decisions]
    assert proposal_ids == sorted(proposal_ids)


def test_state_identity_ignores_registry_and_policy_insertion_order() -> None:
    root = Obligation("state-root", "State root.")
    child = Obligation(
        "state-child", "State child.", dependency_ids=(root.obligation_id,)
    )
    observed = EpistemicRecord(
        "source", EpistemicClass.OBSERVED, 1, provenance=_provenance()
    )
    proposed = EpistemicRecord(
        "candidate", EpistemicClass.MODEL_PROPOSED, {"b": 2, "a": 1}
    )
    read = Capability("read", ReplaySafety.CACHEABLE_READ, "Read state.")
    write = Capability("write", ReplaySafety.OCCURRENCE_SENSITIVE, "Write state.")
    state_a = OrchestrationState.create(
        (root, child),
        epistemic_state=EpistemicState.from_iterable((observed, proposed)),
        capabilities=(read, write),
        strategy_schemas=(_DEFAULT_STRATEGY_SCHEMA,),
    )
    state_b = OrchestrationState.create(
        (child, root),
        epistemic_state=EpistemicState.from_iterable((proposed, observed)),
        capabilities=(write, read),
        strategy_schemas=(_DEFAULT_STRATEGY_SCHEMA,),
    )
    assert state_a.state_id == state_b.state_id
    assert canonical_json(state_a.compact_projection()) == canonical_json(
        state_b.compact_projection()
    )


def test_replay_safe_duplicates_coalesce_but_keep_proposal_decisions() -> None:
    other = Obligation("other-ready", "Other ready work.")
    state, obligation = _ready_state(extra_obligations=(other,))
    first = _proposal(obligation, key="duplicate-a", arguments={"path": "x"})
    second = ActionProposal(
        "duplicate-b",
        "read",
        {"path": "x"},
        target_obligation_ids=(other.obligation_id,),
    )
    receipt = admit_batch(state, _batch(first, second)).receipt
    statuses = [decision.status for decision in receipt.decisions]
    assert statuses.count(DecisionStatus.ADMITTED) == 1
    assert statuses.count(DecisionStatus.DEDUPLICATED) == 1
    assert len({decision.action_id for decision in receipt.decisions}) == 1
    duplicate = next(
        decision
        for decision in receipt.decisions
        if decision.status is DecisionStatus.DEDUPLICATED
    )
    assert duplicate.equivalent_proposal_id is not None


def test_dependency_state_changes_replay_safe_action_identity() -> None:
    obligation = Obligation("state-bound", "State-bound work.")

    def build(revision: int) -> tuple[OrchestrationState, ActionProposal]:
        epistemic = EpistemicState.from_iterable(
            (
                EpistemicRecord(
                    "source",
                    EpistemicClass.OBSERVED,
                    revision,
                    provenance=_provenance(revision=revision),
                ),
            )
        )
        state = OrchestrationState.create(
            (obligation,),
            epistemic_state=epistemic,
            capabilities=(
                Capability(
                    "read", ReplaySafety.CACHEABLE_READ, "Read deterministic state."
                ),
            ),
            strategy_schemas=(_DEFAULT_STRATEGY_SCHEMA,),
        )
        proposal = _proposal(
            obligation,
            required_state_keys=("source",),
            arguments={"path": "same"},
        )
        return state, proposal

    state_a, proposal_a = build(1)
    state_b, proposal_b = build(2)
    action_a = admit_batch(state_a, _batch(proposal_a)).receipt.decisions[0].action_id
    action_b = admit_batch(state_b, _batch(proposal_b)).receipt.decisions[0].action_id
    assert action_a != action_b


def test_effectful_occurrences_are_never_content_deduplicated() -> None:
    state, obligation = _ready_state()
    first = _proposal(
        obligation,
        key="effect-a",
        capability="write",
        arguments={"payload": "same"},
        occurrence_key="effect-occurrence-a",
    )
    second = _proposal(
        obligation,
        key="effect-b",
        capability="write",
        arguments={"payload": "same"},
        occurrence_key="effect-occurrence-b",
    )
    decisions = admit_batch(
        state,
        _batch(
            first,
            second,
            ordering=ProposalOrdering.DECLARED_SEQUENCE,
        ),
    ).receipt.decisions
    assert all(item.status is DecisionStatus.ADMITTED for item in decisions)
    assert len({item.action_id for item in decisions}) == 2


def test_effectful_batch_requires_an_explicit_declared_sequence() -> None:
    state, obligation = _ready_state()
    proposal = _proposal(
        obligation,
        capability="write",
        occurrence_key="ordered-effect",
    )
    decision = admit_batch(state, _batch(proposal)).receipt.decisions[0]
    assert decision.rejection_reason is RejectionReason.ORDERING_CONTRACT_REQUIRED
    assert decision.recovery_actions == (RecoveryAction.USE_DECLARED_SEQUENCE,)
    assert state.occurrence_owners == ()


def test_declared_effect_order_is_identity_bearing_and_preserved() -> None:
    state, obligation = _ready_state()
    first = _proposal(
        obligation,
        key="ordered-first",
        capability="write",
        occurrence_key="ordered-occurrence-first",
    )
    second = _proposal(
        obligation,
        key="ordered-second",
        capability="write",
        occurrence_key="ordered-occurrence-second",
    )
    declared = (first, second)
    if first.proposal_id < second.proposal_id:
        declared = (second, first)

    batch = _batch(
        *declared,
        key="declared-order",
        ordering=ProposalOrdering.DECLARED_SEQUENCE,
    )
    reversed_batch = _batch(
        *reversed(declared),
        key="declared-order",
        ordering=ProposalOrdering.DECLARED_SEQUENCE,
    )
    transition = admit_batch(state, batch)
    assert [item.proposal_key for item in transition.receipt.decisions] == [
        item.proposal_key for item in declared
    ]
    assert batch.batch_id != reversed_batch.batch_id
    assert transition.receipt.proposal_ordering is (
        ProposalOrdering.DECLARED_SEQUENCE
    )


def test_duplicate_effect_occurrence_is_rejected_not_deduplicated() -> None:
    state, obligation = _ready_state()
    first = _proposal(
        obligation,
        key="effect-one",
        capability="write",
        occurrence_key="same-occurrence",
    )
    second = _proposal(
        obligation,
        key="effect-two",
        capability="write",
        occurrence_key="same-occurrence",
    )
    decisions = admit_batch(
        state,
        _batch(
            first,
            second,
            ordering=ProposalOrdering.DECLARED_SEQUENCE,
        ),
    ).receipt.decisions
    assert [item.status for item in decisions].count(DecisionStatus.ADMITTED) == 1
    rejected = next(
        item for item in decisions if item.status is DecisionStatus.REJECTED
    )
    assert rejected.rejection_reason is RejectionReason.DUPLICATE_OCCURRENCE
    assert RecoveryAction.USE_DISTINCT_OCCURRENCE_KEY in rejected.recovery_actions


def test_effect_occurrence_ownership_persists_across_batches() -> None:
    state, obligation = _ready_state()
    first = _proposal(
        obligation,
        key="cross-batch-first",
        capability="write",
        occurrence_key="cross-batch-occurrence",
    )
    first_transition = admit_batch(
        state,
        _batch(first, ordering=ProposalOrdering.DECLARED_SEQUENCE),
    )
    assert len(first_transition.next_state.occurrence_owners) == 1

    repeated = _proposal(
        obligation,
        key="cross-batch-repeat",
        capability="write",
        arguments={"changed": True},
        occurrence_key="cross-batch-occurrence",
    )
    second_transition = admit_batch(
        first_transition.next_state,
        _batch(repeated, ordering=ProposalOrdering.DECLARED_SEQUENCE),
    )
    decision = second_transition.receipt.decisions[0]
    assert decision.rejection_reason is RejectionReason.DUPLICATE_OCCURRENCE
    assert second_transition.next_state.occurrence_owners == (
        first_transition.next_state.occurrence_owners
    )


def test_occurrence_registry_fails_closed_at_its_bound() -> None:
    limits = OrchestrationLimits(max_occurrence_owners=1)
    state, obligation = _ready_state(limits=limits)
    first = _proposal(
        obligation,
        key="capacity-first",
        capability="write",
        occurrence_key="capacity-occurrence-first",
    )
    first_transition = admit_batch(
        state,
        _batch(first, ordering=ProposalOrdering.DECLARED_SEQUENCE),
    )
    second = _proposal(
        obligation,
        key="capacity-second",
        capability="write",
        occurrence_key="capacity-occurrence-second",
    )
    second_transition = admit_batch(
        first_transition.next_state,
        _batch(second, ordering=ProposalOrdering.DECLARED_SEQUENCE),
    )
    decision = second_transition.receipt.decisions[0]
    assert decision.rejection_reason is RejectionReason.OCCURRENCE_REGISTRY_FULL
    assert decision.recovery_actions == (RecoveryAction.REQUEST_NEW_BOUNDED_SCOPE,)
    assert len(second_transition.next_state.occurrence_owners) == 1


@pytest.mark.parametrize(
    ("capability", "occurrence_key", "reason", "recovery"),
    (
        (
            "write",
            None,
            RejectionReason.OCCURRENCE_KEY_REQUIRED,
            RecoveryAction.ADD_OCCURRENCE_KEY,
        ),
        (
            "read",
            "unexpected-occurrence",
            RejectionReason.UNEXPECTED_OCCURRENCE_KEY,
            RecoveryAction.REMOVE_OCCURRENCE_KEY,
        ),
    ),
)
def test_occurrence_contract_rejections_are_structural(
    capability: str,
    occurrence_key: str | None,
    reason: RejectionReason,
    recovery: RecoveryAction,
) -> None:
    state, obligation = _ready_state()
    proposal = _proposal(
        obligation,
        capability=capability,
        occurrence_key=occurrence_key,
    )
    decision = admit_batch(
        state,
        _batch(proposal, ordering=ProposalOrdering.DECLARED_SEQUENCE),
    ).receipt.decisions[0]
    assert decision.rejection_reason is reason
    assert recovery in decision.recovery_actions


def test_model_cannot_self_classify_unknown_capability_as_replay_safe() -> None:
    state, obligation = _ready_state()
    proposal = _proposal(obligation, capability="model.claims.safe")
    decision = admit_batch(state, _batch(proposal)).receipt.decisions[0]
    assert decision.status is DecisionStatus.REJECTED
    assert decision.rejection_reason is RejectionReason.UNKNOWN_CAPABILITY
    assert decision.action_id is None
    assert decision.authority_layer is AuthorityLayer.ORCHESTRATION
    assert decision.invariant_ids == ("IBAE-GOV-006", "IBAE-ORCH-001")


def test_unavailable_capability_fails_closed_with_recovery() -> None:
    capabilities = (
        Capability(
            "offline", ReplaySafety.CACHEABLE_READ, "Unavailable read.", available=False
        ),
    )
    state, obligation = _ready_state(capabilities=capabilities)
    proposal = _proposal(obligation, capability="offline")
    decision = admit_batch(state, _batch(proposal)).receipt.decisions[0]
    assert decision.rejection_reason is RejectionReason.CAPABILITY_UNAVAILABLE
    assert decision.recovery_actions == (RecoveryAction.CHOOSE_AVAILABLE_CAPABILITY,)


def test_capability_owned_dependencies_cannot_be_omitted_by_model() -> None:
    capabilities = (
        Capability(
            "policy-read",
            ReplaySafety.CACHEABLE_READ,
            "Read state with a policy-owned dependency.",
            required_state_keys=("required-by-policy",),
        ),
    )
    state, obligation = _ready_state(capabilities=capabilities)
    proposal = _proposal(obligation, capability="policy-read")
    decision = admit_batch(state, _batch(proposal)).receipt.decisions[0]
    assert proposal.required_state_keys == ()
    assert decision.dependency_state_keys == ("required-by-policy",)
    assert decision.rejection_reason is RejectionReason.UNKNOWN_STATE
    assert decision.unresolved_state_keys == ("required-by-policy",)


def test_capability_contract_version_and_dependencies_are_identity_bearing() -> None:
    base = Capability("versioned", ReplaySafety.CACHEABLE_READ, "Versioned action.")
    next_version = Capability(
        "versioned",
        ReplaySafety.CACHEABLE_READ,
        "Versioned action.",
        contract_version=2,
    )
    with_dependency = Capability(
        "versioned",
        ReplaySafety.CACHEABLE_READ,
        "Versioned action.",
        required_state_keys=("source",),
    )
    assert (
        len(
            {
                base.capability_id,
                next_version.capability_id,
                with_dependency.capability_id,
            }
        )
        == 3
    )


def test_non_read_replay_safety_requires_explicit_evidence_identity() -> None:
    with pytest.raises(ValueError, match="require replay evidence"):
        Capability(
            "proven-action",
            ReplaySafety.PROVEN_REPLAY_SAFE,
            "Replay-safe action with missing evidence.",
        )

    evidence_id = domain_fingerprint(
        "ibae.test-replay-evidence.v1", {"proof": "fixture"}
    )
    capability = Capability(
        "proven-action",
        ReplaySafety.PROVEN_REPLAY_SAFE,
        "Replay-safe action with evidence.",
        replay_evidence_id=evidence_id,
    )
    assert capability.is_replay_safe
    assert capability.canonical_record()["replay_evidence_id"] == evidence_id

    with pytest.raises(ValueError, match="only proven replay-safe"):
        Capability(
            "read-with-proof",
            ReplaySafety.CACHEABLE_READ,
            "Cacheable read cannot masquerade as proven action.",
            replay_evidence_id=evidence_id,
        )


def test_unknown_obligation_is_rejected_with_stable_reason() -> None:
    state, _ = _ready_state()
    unknown_id = domain_fingerprint("ibae.unknown-obligation.v1", {"key": "x"})
    proposal = ActionProposal(
        "unknown-target",
        "read",
        {},
        target_obligation_ids=(unknown_id,),
    )
    decision = admit_batch(state, _batch(proposal)).receipt.decisions[0]
    assert decision.rejection_reason is RejectionReason.UNKNOWN_OBLIGATION
    assert decision.blocking_obligation_ids == (unknown_id,)


def test_satisfied_blocked_and_dependency_blocked_targets_are_distinct() -> None:
    satisfied = Obligation("done", "Already done.", status=ObligationStatus.SATISFIED)
    blocked = Obligation(
        "external",
        "External gate.",
        status=ObligationStatus.BLOCKED,
        block_reason="waiting for review",
    )
    dependent = Obligation(
        "dependent", "Dependent work.", dependency_ids=(satisfied.obligation_id,)
    )
    root = Obligation("unsatisfied-root", "Unsatisfied root.")
    waiting = Obligation(
        "waiting", "Waiting work.", dependency_ids=(root.obligation_id,)
    )
    state = OrchestrationState.create(
        (satisfied, blocked, dependent, root, waiting),
        capabilities=(Capability("read", ReplaySafety.CACHEABLE_READ, "Read state."),),
        strategy_schemas=(_DEFAULT_STRATEGY_SCHEMA,),
    )
    proposals = (
        _proposal(satisfied, key="target-done"),
        _proposal(blocked, key="target-blocked"),
        _proposal(waiting, key="target-waiting"),
    )
    decisions = admit_batch(state, _batch(*proposals)).receipt.decisions
    reasons = {item.proposal_key: item.rejection_reason for item in decisions}
    assert reasons == {
        "target-done": RejectionReason.OBLIGATION_SATISFIED,
        "target-blocked": RejectionReason.OBLIGATION_BLOCKED,
        "target-waiting": RejectionReason.DEPENDENCY_UNSATISFIED,
    }


def test_unknown_epistemic_state_is_rejected_not_treated_as_false() -> None:
    epistemic = EpistemicState.from_iterable(
        (EpistemicRecord("feature-enabled", EpistemicClass.UNKNOWN),)
    )
    state, obligation = _ready_state(epistemic_state=epistemic)
    proposal = _proposal(
        obligation, required_state_keys=("feature-enabled", "missing-key")
    )
    decision = admit_batch(state, _batch(proposal)).receipt.decisions[0]
    assert decision.rejection_reason is RejectionReason.UNKNOWN_STATE
    assert decision.unresolved_state_keys == ("feature-enabled", "missing-key")
    assert decision.recovery_actions == (RecoveryAction.OBSERVE_REQUIRED_STATE,)


def test_logical_clock_is_transition_derived_and_history_is_bounded() -> None:
    limits = OrchestrationLimits(max_history=1)
    state, obligation = _ready_state(limits=limits)
    first = admit_batch(state, _batch(_proposal(obligation), key="first"))
    second = admit_batch(
        first.next_state,
        _batch(_proposal(obligation, key="next", arguments={"n": 2}), key="second"),
    )
    assert first.next_state.logical_tick == 1
    assert second.next_state.logical_tick == 2
    assert len(second.next_state.history) == 1
    assert "elapsed" not in canonical_json(second.next_state.canonical_record())
    assert "wall_clock" not in canonical_json(second.next_state.canonical_record())


def test_oversized_batch_is_rejected_once_and_exposes_split_recovery() -> None:
    limits = OrchestrationLimits(max_batch_proposals=1)
    state, obligation = _ready_state(limits=limits)
    batch = _batch(
        _proposal(obligation, key="one"),
        _proposal(obligation, key="two", arguments={"n": 2}),
    )
    transition = admit_batch(state, batch)
    receipt = transition.receipt
    assert receipt.status is BatchStatus.REJECTED
    assert receipt.decisions == ()
    assert receipt.batch_rejection is not None
    assert receipt.batch_rejection.reason is RejectionReason.BATCH_LIMIT_EXCEEDED
    assert receipt.batch_rejection.authority_layer is AuthorityLayer.ORCHESTRATION
    assert receipt.batch_rejection.invariant_ids == (
        "IBAE-BND-008",
        "IBAE-ORCH-006",
    )
    assert receipt.batch_rejection.recovery_actions == (RecoveryAction.SPLIT_BATCH,)
    assert transition.next_state.logical_tick == 1
    assert len(transition.next_state.history) == 1


def test_compact_state_projection_exposes_ready_blocked_and_capabilities() -> None:
    root = Obligation("projection-root", "Projection root.")
    dependency_blocked = Obligation(
        "projection-child",
        "Projection child.",
        dependency_ids=(root.obligation_id,),
    )
    explicitly_blocked = Obligation(
        "projection-external",
        "Wait for external approval.",
        status=ObligationStatus.BLOCKED,
        block_reason="approval has not arrived",
    )
    state = OrchestrationState.create(
        (dependency_blocked, explicitly_blocked, root),
        capabilities=(Capability("read", ReplaySafety.CACHEABLE_READ, "Read state."),),
        strategy_schemas=(_DEFAULT_STRATEGY_SCHEMA,),
    )
    projection = state.compact_projection()
    assert projection["canonical_state_identity"] == state.state_id
    assert projection["logical_clock"]["tick"] == 0
    assert projection["obligations"]["ready"][0]["obligation_id"] == (
        root.obligation_id
    )
    blocked_records = projection["obligations"]["blocked"]
    dependency_record = next(
        item for item in blocked_records if item["key"] == "projection-child"
    )
    explicit_record = next(
        item for item in blocked_records if item["key"] == "projection-external"
    )
    assert dependency_record["blocking_dependency_ids"] == [root.obligation_id]
    assert dependency_record["description"] == "Projection child."
    assert dependency_record["block_reason"] is None
    assert explicit_record["description"] == "Wait for external approval."
    assert explicit_record["block_reason"] == "approval has not arrived"
    assert projection["capabilities"][0]["name"] == "read"
    assert projection["capacity"]["obligation_slots_remaining"] == 125
    assert projection["capacity"]["occurrence_owner_slots_remaining"] == 256
    assert projection["capacity"]["strategy_schema_slots_remaining"] == 31
    assert projection["strategy_schemas"][0]["strategy_key"] == "default"


def test_state_identity_changes_with_authoritative_transition_state() -> None:
    state, obligation = _ready_state()
    transition = admit_batch(state, _batch(_proposal(obligation)))
    assert state.state_id != transition.next_state.state_id
    assert transition.receipt.prior_state_id == state.state_id
    assert transition.receipt.next_state_id == transition.next_state.state_id


def test_v0_2_reference_fixture_matches_checked_in_canonical_bytes() -> None:
    fixture_path = (
        Path(__file__).parents[1] / "fixtures/v0.2/orchestration-reference.json"
    )
    checked_in = fixture_path.read_text(encoding="utf-8")
    assert checked_in.endswith("\n")
    assert checked_in == canonical_json(v0_2_reference_fixture()) + "\n"
    assert json.loads(checked_in)["receipt"]["protocol"] == ("IBAE-AGENT-PROTOCOL-V1")
