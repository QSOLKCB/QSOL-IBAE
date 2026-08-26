from __future__ import annotations

import json
from pathlib import Path

import pytest

from ibae import (
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
    RecoveryAction,
    RejectionReason,
    ReplaySafety,
    Strategy,
    admit_batch,
    canonical_json,
    canonical_obligation_id,
    domain_fingerprint,
)
from ibae.conformance import v0_2_reference_fixture


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
    state = OrchestrationState.create(
        (obligation, *extra_obligations),
        limits=limits,
        epistemic_state=epistemic_state,
        capabilities=active_capabilities,
    )
    return state, obligation


def _batch(*proposals: ActionProposal, key: str = "batch") -> ProposalBatch:
    return ProposalBatch(key, Strategy("default", {"version": 1}), proposals)


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


def test_derived_state_cannot_claim_known_value_from_unknown_input() -> None:
    with pytest.raises(ValueError, match="unknown dependencies"):
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


def test_strategy_and_proposal_payloads_are_mutation_isolated() -> None:
    state, obligation = _ready_state()
    arguments = {"items": [1]}
    parameters = {"order": [1]}
    strategy = Strategy("stable", parameters)
    proposal = _proposal(obligation, arguments=arguments)
    proposal_id = proposal.proposal_id
    strategy_id = strategy.strategy_id

    arguments["items"].append(2)
    parameters["order"].append(2)
    proposal.arguments["items"].append(3)
    strategy.parameters["order"].append(3)
    assert proposal.arguments == {"items": [1]}
    assert strategy.parameters == {"order": [1]}
    assert proposal.proposal_id == proposal_id
    assert strategy.strategy_id == strategy_id
    assert state.logical_tick == 0


def test_proposal_batch_normalizes_caller_owned_sequence() -> None:
    _, obligation = _ready_state()
    first = _proposal(obligation, key="first")
    proposals = [first]
    batch = ProposalBatch("isolated-batch", Strategy("stable", {}), proposals)
    proposals.append(_proposal(obligation, key="second", arguments={"n": 2}))
    assert batch.proposals == (first,)


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
    )
    state_b = OrchestrationState.create(
        (child, root),
        epistemic_state=EpistemicState.from_iterable((proposed, observed)),
        capabilities=(write, read),
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
    decisions = admit_batch(state, _batch(first, second)).receipt.decisions
    assert all(item.status is DecisionStatus.ADMITTED for item in decisions)
    assert len({item.action_id for item in decisions}) == 2


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
    decisions = admit_batch(state, _batch(first, second)).receipt.decisions
    assert [item.status for item in decisions].count(DecisionStatus.ADMITTED) == 1
    rejected = next(
        item for item in decisions if item.status is DecisionStatus.REJECTED
    )
    assert rejected.rejection_reason is RejectionReason.DUPLICATE_OCCURRENCE
    assert RecoveryAction.USE_DISTINCT_OCCURRENCE_KEY in rejected.recovery_actions


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
    decision = admit_batch(state, _batch(proposal)).receipt.decisions[0]
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
    blocked = Obligation(
        "projection-child",
        "Projection child.",
        dependency_ids=(root.obligation_id,),
    )
    state = OrchestrationState.create(
        (blocked, root),
        capabilities=(Capability("read", ReplaySafety.CACHEABLE_READ, "Read state."),),
    )
    projection = state.compact_projection()
    assert projection["canonical_state_identity"] == state.state_id
    assert projection["logical_clock"]["tick"] == 0
    assert projection["obligations"]["ready"][0]["obligation_id"] == (
        root.obligation_id
    )
    assert projection["obligations"]["blocked"][0]["blocking_dependency_ids"] == [
        root.obligation_id
    ]
    assert projection["capabilities"][0]["name"] == "read"
    assert projection["capacity"]["obligation_slots_remaining"] == 126


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
