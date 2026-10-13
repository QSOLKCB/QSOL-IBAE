"""Structural witnesses for supervisor read-proposal feasibility.

These tests use ordinary typed admission records and never invoke a tool
operation. Eligibility describes a proposal class; individual proposals still
cross the unchanged orchestration and governance checks.
"""

from dataclasses import replace

import pytest

from ibae._records import MAX_IDENTITY_INTEGER_BITS
from ibae.epistemic import (
    EpistemicClass, EpistemicRecord, EpistemicState, ObservationProvenance,
)
from ibae.governance import (
    PrincipalAuthority, ToolAdmissionReceipt, ToolAuthorityClass, ToolPermission,
)
from ibae.obligations import Obligation, ObligationStatus
from ibae.orchestration import (
    ActionProposal, AuthorityLayer, BatchStatus, Capability, DecisionStatus,
    OccurrenceOwnership, OrchestrationLimits, OrchestrationState, ProposalBatch,
    ProposalOrdering, RejectionReason, ReplaySafety, Strategy,
    StrategyParameterSpec, StrategySchema, StrategyValueKind, admit_batch,
)
from ibae.supervisor import SupervisorProjection
from test_supervisor import _context, _id


def _state(*, schemas=None, capability=None, obligations=None, epistemic=None, limits=None):
    return OrchestrationState.create(
        (Obligation("work", "Work"),) if obligations is None else obligations,
        capabilities=(capability or Capability("read", ReplaySafety.CACHEABLE_READ, "Read"),),
        strategy_schemas=(StrategySchema("read.strategy"),) if schemas is None else schemas,
        epistemic_state=epistemic,
        limits=limits,
    )


def _proposal(state, **changes):
    fields = {
        "proposal_key": "read.proposal", "capability": "read", "arguments": {},
        "target_obligation_ids": state.obligations.ready_ids,
    }
    fields.update(changes)
    return ActionProposal(**fields)


def _batch(state, proposal, *, schema=None, parameters=None, ordering=ProposalOrdering.CANONICAL_INDEPENDENT):
    schema = schema or state.strategy_schemas[0]
    return ProposalBatch(
        "read.batch", Strategy(schema.strategy_key, parameters or {}, schema=schema),
        (proposal,), ordering=ordering,
    )


def _govern(context, decision, proposal, **changes):
    state = context.orchestration_state
    capability = state.capability(proposal.capability)
    fields = {
        "policy": context.governance_policy, "task": context.task,
        "governance": context.governance,
        "permission": context.governance_policy.permission_for(capability.name),
        "requester": PrincipalAuthority.DETERMINISTIC_ORCHESTRATOR,
        "admission_decision": decision, "proposal": proposal, "capability": capability,
        "dependency_state_id": state.epistemic_state.dependency_digest(decision.dependency_state_keys),
    }
    fields.update(changes)
    return ToolAdmissionReceipt(**fields)


def _surface(context, expected):
    surface = SupervisorProjection(context).decision_surface
    assert surface["capabilities"][0]["read_proposal_eligible"] is expected
    assert ("propose_governed_read" in surface["legal_next_action_classes"]) is expected
    # These structural fixtures deliberately have no runtime observations.
    assert not surface["capabilities"][0]["cache_reuse_proposal_eligible"]
    assert "propose_cache_reuse_subject_to_exact_key_match" not in surface["legal_next_action_classes"]
    return surface


def _witness(context, *, parameters=None, proposal=None, ordering=ProposalOrdering.CANONICAL_INDEPENDENT):
    state = context.orchestration_state
    proposal = proposal or _proposal(state)
    transition = admit_batch(state, _batch(state, proposal, parameters=parameters, ordering=ordering))
    assert transition.receipt.status is BatchStatus.PROCESSED
    decision, = transition.receipt.decisions
    assert decision.status is DecisionStatus.ADMITTED
    assert transition.next_state.logical_tick == state.logical_tick + 1
    governed = _govern(context, decision, proposal)
    assert governed.action_id == decision.action_id
    return decision, proposal, governed


@pytest.mark.parametrize("spec,parameters", [
    (None, {}),
    (StrategyParameterSpec("choice", StrategyValueKind.BOOLEAN), {"choice": False}),
    (StrategyParameterSpec("choice", StrategyValueKind.BOUNDED_INTEGER, minimum=3, maximum=3), {"choice": 3}),
    (StrategyParameterSpec("choice", StrategyValueKind.SYMBOL, allowed_symbols=("a",)), {"choice": "a"}),
    (StrategyParameterSpec("choice", StrategyValueKind.SYMBOL_LIST, allowed_symbols=("a",)), {"choice": []}),
    (StrategyParameterSpec("choice", StrategyValueKind.BOOLEAN, required=False), {}),
], ids=["empty", "required-boolean", "required-integer", "required-symbol", "required-list", "optional-omitted"])
def test_each_valid_strategy_domain_has_a_real_governed_read_witness(spec, parameters):
    schema = StrategySchema("read.strategy", () if spec is None else (spec,))
    context, _, _ = _context(state=_state(schemas=(schema,)))
    _surface(context, True)
    _witness(context, parameters=parameters)


@pytest.mark.parametrize("registered", [False, True])
def test_empty_registry_blocks_reads_and_exact_schema_identity_still_matters(registered):
    admitted = StrategySchema("read.strategy")
    state = _state(schemas=(admitted,) if registered else ())
    context, _, _ = _context(state=state)
    _surface(context, registered)
    proposed = replace(admitted, contract_version=2) if registered else admitted
    transition = admit_batch(state, _batch(state, _proposal(state), schema=proposed))
    assert transition.receipt.status is BatchStatus.REJECTED
    assert transition.receipt.batch_rejection.reason is RejectionReason.STRATEGY_SCHEMA_NOT_ADMITTED
    assert transition.receipt.decisions == ()


@pytest.mark.parametrize("tick", [0, (1 << MAX_IDENTITY_INTEGER_BITS) - 2, (1 << MAX_IDENTITY_INTEGER_BITS) - 1])
def test_clock_headroom_matches_one_proposal_admission(tick):
    state = replace(_state(), logical_tick=tick)
    context, _, _ = _context(state=state)
    possible = tick < (1 << MAX_IDENTITY_INTEGER_BITS) - 1
    _surface(context, possible)
    if possible:
        _witness(context)
    else:
        with pytest.raises(ValueError, match="maximum bit length"):
            admit_batch(state, _batch(state, _proposal(state)))


@pytest.mark.parametrize("case,expected", [
    ("empty", False), ("ready", True), ("satisfied", False),
    ("blocked", False), ("dependency-blocked", False), ("mixed", True),
])
def test_readiness_requires_one_ready_target_not_all_registered_targets(case, expected):
    ready = Obligation("work", "Work")
    blocked = Obligation("blocked", "Blocked", status=ObligationStatus.BLOCKED, block_reason="Await input")
    obligations = {
        "empty": (), "ready": (ready,),
        "satisfied": (ready.with_status(ObligationStatus.SATISFIED),),
        "blocked": (blocked,),
        "dependency-blocked": (blocked, Obligation("dependent", "Dependent", (blocked.obligation_id,))),
        "mixed": (ready, blocked),
    }[case]
    context, _, _ = _context(state=_state(obligations=obligations))
    _surface(context, expected)
    if expected:
        _witness(context)


@pytest.mark.parametrize("authority_class", [ToolAuthorityClass.PURE_READ, ToolAuthorityClass.SNAPSHOT_READ])
@pytest.mark.parametrize("mandatory", [False, True])
@pytest.mark.parametrize("epistemic_class", [None, *EpistemicClass])
def test_dependency_class_feasibility_matches_real_admission(authority_class, mandatory, epistemic_class):
    if epistemic_class is None:
        records = ()
    elif epistemic_class is EpistemicClass.UNKNOWN:
        records = (EpistemicRecord("input", epistemic_class),)
    elif epistemic_class is EpistemicClass.OBSERVED:
        records = (EpistemicRecord("input", epistemic_class, "value", provenance=ObservationProvenance(
            "fixture", _id("source"), _id("dependency"))),)
    else:
        records = (EpistemicRecord("input", epistemic_class, "value"),)
    resolved = epistemic_class in {EpistemicClass.OBSERVED, EpistemicClass.DERIVED}
    capability = Capability("read", ReplaySafety.CACHEABLE_READ, "Read", required_state_keys=("input",) if mandatory else ())
    state = _state(capability=capability, epistemic=EpistemicState(records))
    context, _, _ = _context(state=state, permissions=(ToolPermission("read", authority_class, False, True),))
    possible = not mandatory if authority_class is ToolAuthorityClass.PURE_READ else resolved
    _surface(context, possible)
    proposal = _proposal(state, required_state_keys=("input",) if authority_class is ToolAuthorityClass.SNAPSHOT_READ else ())
    transition = admit_batch(state, _batch(state, proposal))
    decision, = transition.receipt.decisions
    if possible:
        assert decision.status is DecisionStatus.ADMITTED
        assert _govern(context, decision, proposal).authority_class is authority_class
    elif decision.status is DecisionStatus.ADMITTED:
        with pytest.raises(ValueError, match="read authority class"):
            _govern(context, decision, proposal)
    else:
        assert decision.rejection_reason is RejectionReason.UNKNOWN_STATE


@pytest.mark.parametrize("available", [False, True])
@pytest.mark.parametrize("replay_safety", list(ReplaySafety))
@pytest.mark.parametrize("authority_class", [None, *ToolAuthorityClass])
def test_availability_replay_and_permission_are_independent_requirements(available, replay_safety, authority_class):
    capability = Capability("read", replay_safety, "Read", available=available,
        replay_evidence_id=_id("replay") if replay_safety is ReplaySafety.PROVEN_REPLAY_SAFE else None)
    permissions = () if authority_class is None else (ToolPermission(
        "read", authority_class, authority_class.is_mutation,
        authority_class in {ToolAuthorityClass.PURE_READ, ToolAuthorityClass.SNAPSHOT_READ}),)
    # One selectable dependency makes both supported read classes possible.
    state = _state(capability=capability, epistemic=EpistemicState((EpistemicRecord("input", EpistemicClass.DERIVED, 1),)))
    context, _, _ = _context(state=state, permissions=permissions)
    possible = available and replay_safety is ReplaySafety.CACHEABLE_READ and authority_class in {
        ToolAuthorityClass.PURE_READ, ToolAuthorityClass.SNAPSHOT_READ}
    _surface(context, possible)
    if possible:
        _witness(context, proposal=_proposal(state, required_state_keys=("input",) if authority_class is ToolAuthorityClass.SNAPSHOT_READ else ()))


@pytest.mark.parametrize("reuse", [False, True])
@pytest.mark.parametrize("ordering", list(ProposalOrdering))
def test_reuse_permission_and_ordering_do_not_hide_cold_read_proposals(reuse, ordering):
    context, _, _ = _context(state=_state(), permissions=(ToolPermission("read", ToolAuthorityClass.PURE_READ, False, reuse),))
    surface = _surface(context, True)
    assert surface["capabilities"][0]["cache_reuse_granted"] is reuse
    assert _witness(context, ordering=ordering)[2].cache_reuse_permitted is reuse


@pytest.mark.parametrize("case,reason", [
    ("unknown-capability", RejectionReason.UNKNOWN_CAPABILITY),
    ("extra-argument", RejectionReason.ARGUMENT_SCHEMA_MISMATCH),
    ("nonmapping-arguments", RejectionReason.ARGUMENT_SCHEMA_MISMATCH),
    ("unknown-target", RejectionReason.UNKNOWN_OBLIGATION),
    ("satisfied-target", RejectionReason.OBLIGATION_SATISFIED),
    ("blocked-target", RejectionReason.OBLIGATION_BLOCKED),
    ("dependency-blocked-target", RejectionReason.DEPENDENCY_UNSATISFIED),
    ("unknown-dependency", RejectionReason.UNKNOWN_STATE),
    ("occurrence-key", RejectionReason.UNEXPECTED_OCCURRENCE_KEY),
])
def test_possible_class_does_not_admit_invalid_individual_proposals(case, reason):
    ready = Obligation("work", "Work")
    satisfied = Obligation("done", "Done", status=ObligationStatus.SATISFIED)
    blocked = Obligation("blocked", "Blocked", status=ObligationStatus.BLOCKED, block_reason="Await input")
    dependent = Obligation("dependent", "Dependent", (blocked.obligation_id,))
    state = _state(obligations=(ready, satisfied, blocked, dependent))
    context, _, _ = _context(state=state)
    _surface(context, True)
    changes = {
        "unknown-capability": {"capability": "missing"},
        "extra-argument": {"arguments": {"not.allowed": 1}},
        "nonmapping-arguments": {"arguments": []},
        "unknown-target": {"target_obligation_ids": (ready.obligation_id, _id("unknown"))},
        "satisfied-target": {"target_obligation_ids": (ready.obligation_id, satisfied.obligation_id)},
        "blocked-target": {"target_obligation_ids": (ready.obligation_id, blocked.obligation_id)},
        "dependency-blocked-target": {"target_obligation_ids": (ready.obligation_id, dependent.obligation_id)},
        "unknown-dependency": {"required_state_keys": ("missing",)},
        "occurrence-key": {"occurrence_key": "unnecessary"},
    }[case]
    proposal = _proposal(state, **changes)
    decision, = admit_batch(state, _batch(state, proposal)).receipt.decisions
    assert decision.status is DecisionStatus.REJECTED
    assert decision.rejection_reason is reason


@pytest.mark.parametrize("parameters", [{}, {"choice": "no"}, {"choice": 2}, {"choice": True, "extra": 1}])
def test_invalid_strategy_parameters_remain_constructor_rejections(parameters):
    schema = StrategySchema("read.strategy", (StrategyParameterSpec("choice", StrategyValueKind.BOOLEAN),))
    context, _, _ = _context(state=_state(schemas=(schema,)))
    _surface(context, True)
    with pytest.raises((TypeError, ValueError)):
        Strategy(schema.strategy_key, parameters, schema=schema)


def test_single_proposal_witness_fits_minimal_limit_and_deduplication_stays_batch_local():
    state = _state(limits=OrchestrationLimits(max_batch_proposals=1))
    context, _, _ = _context(state=state)
    _surface(context, True)
    _witness(context)
    first, second = _proposal(state), _proposal(state, proposal_key="second")
    batch = replace(_batch(state, first), proposals=(first, second))
    rejection = admit_batch(state, batch).receipt
    assert rejection.batch_rejection.reason is RejectionReason.BATCH_LIMIT_EXCEEDED
    larger = replace(state, limits=replace(state.limits, max_batch_proposals=2))
    receipt = admit_batch(larger, batch).receipt
    assert [item.status for item in receipt.decisions] == [DecisionStatus.ADMITTED, DecisionStatus.DEDUPLICATED]
    # A new batch admits its own representative, even after prior admission.
    next_state = admit_batch(state, _batch(state, first)).next_state
    assert admit_batch(next_state, _batch(next_state, first)).receipt.decisions[0].status is DecisionStatus.ADMITTED


def test_full_registries_and_rolling_history_do_not_prevent_using_existing_read():
    limits = OrchestrationLimits(max_obligations=1, max_capabilities=1, max_epistemic_records=1,
        max_occurrence_owners=1, max_strategy_schemas=1, max_history=1, max_batch_proposals=1)
    state = replace(_state(limits=limits, epistemic=EpistemicState(
        (EpistemicRecord("input", EpistemicClass.DERIVED, 1),), max_records=1)),
        history=(_id("history"),), occurrence_owners=(OccurrenceOwnership("used", _id("action"), _id("proposal")),))
    context, _, _ = _context(state=state)
    surface = _surface(context, True)
    capacity = surface["budgets"]["orchestration_capacity"]
    assert all(capacity[key] == 0 for key in ("obligations", "capabilities", "epistemic_records", "occurrence_owners", "strategy_schemas"))
    _witness(context)


@pytest.mark.parametrize("case", [
    "requester", "foreign-permission", "proposal-identity", "capability-identity",
    "dependency-fingerprint", "decision-action", "decision-dependencies",
    "decision-authority", "decision-blockers", "deduplicated",
])
def test_governance_revalidates_exact_structural_witness(case):
    context, _, _ = _context(state=_state())
    _surface(context, True)
    decision, proposal, _ = _witness(context)
    changes = {
        "requester": {"requester": PrincipalAuthority.OPENAI_SUPERVISOR},
        "foreign-permission": {"permission": ToolPermission("other", ToolAuthorityClass.PURE_READ, False, True)},
        "proposal-identity": {"proposal": _proposal(context.orchestration_state, proposal_key="different")},
        "capability-identity": {"capability": Capability("other", ReplaySafety.CACHEABLE_READ, "Other")},
        "dependency-fingerprint": {"dependency_state_id": _id("wrong-dependencies")},
        "decision-action": {"admission_decision": replace(decision, action_id=_id("wrong-action"))},
        "decision-dependencies": {"admission_decision": replace(decision, dependency_state_keys=("input",))},
        "decision-authority": {"admission_decision": replace(decision, authority_layer=AuthorityLayer.EXECUTION)},
        "decision-blockers": {"admission_decision": replace(decision, blocking_obligation_ids=(_id("blocker"),))},
        "deduplicated": {"admission_decision": replace(decision, status=DecisionStatus.DEDUPLICATED, equivalent_proposal_id=_id("representative"))},
    }[case]
    with pytest.raises((TypeError, ValueError)):
        _govern(context, decision, proposal, **changes)


@pytest.mark.parametrize("case", ["missing-authority", "revoked", "complete"])
def test_supervisor_control_can_hide_a_structurally_admissible_read(case):
    context, _, _ = _context(complete=case == "complete")
    if case == "missing-authority":
        context = replace(context, supervisor_authority=None)
    elif case == "revoked":
        context.supervisor_authority.revoke_all()
    _surface(context, False)
