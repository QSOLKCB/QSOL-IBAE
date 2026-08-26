"""Deterministic reference fixtures for implemented IBAE contracts."""

from __future__ import annotations

from .canonical import domain_fingerprint
from .epistemic import (
    EpistemicClass,
    EpistemicRecord,
    EpistemicState,
    ObservationProvenance,
)
from .obligations import Obligation, ObligationStatus
from .orchestration import (
    ActionProposal,
    Capability,
    OrchestrationState,
    ProposalBatch,
    ProposalOrdering,
    ReplaySafety,
    Strategy,
    StrategyParameterSpec,
    StrategySchema,
    StrategyValueKind,
    admit_batch,
)


def v0_2_reference_fixture() -> dict[str, object]:
    """Build the byte-stable, model-free v0.2 orchestration fixture."""

    inspect = Obligation(
        "inspect-source",
        "Inspect the canonical source state.",
        status=ObligationStatus.SATISFIED,
    )
    tests = Obligation(
        "repair-tests",
        "Repair the failing deterministic tests.",
        dependency_ids=(inspect.obligation_id,),
    )
    ci = Obligation(
        "verify-ci",
        "Verify the repaired state in continuous integration.",
        dependency_ids=(tests.obligation_id,),
    )
    review = Obligation(
        "review-gate",
        "Wait for an external review gate.",
        status=ObligationStatus.BLOCKED,
        block_reason="external review has not completed",
    )

    provenance = ObservationProvenance(
        source="github.read",
        source_identity=domain_fingerprint(
            "ibae.fixture-source.v1", {"commit": "76016db"}
        ),
        dependency_identity=domain_fingerprint(
            "ibae.fixture-dependency.v1", {"ref": "main"}
        ),
        reused=False,
    )
    epistemic_state = EpistemicState.from_iterable(
        (
            EpistemicRecord(
                "repo-head",
                EpistemicClass.OBSERVED,
                {"commit": "76016db", "tree_clean": True},
                provenance=provenance,
            ),
            EpistemicRecord(
                "failing-tests",
                EpistemicClass.DERIVED,
                2,
                dependencies=("repo-head",),
            ),
            EpistemicRecord(
                "patch-plan",
                EpistemicClass.MODEL_PROPOSED,
                {"files": ["src/ibae/orchestration.py"]},
            ),
            EpistemicRecord("review-state", EpistemicClass.UNKNOWN),
        )
    )
    strategy_schema = StrategySchema(
        "repair-reference",
        (
            StrategyParameterSpec(
                "ordering",
                StrategyValueKind.SYMBOL,
                allowed_symbols=("declared_sequence",),
            ),
            StrategyParameterSpec(
                "version",
                StrategyValueKind.BOUNDED_INTEGER,
                minimum=1,
                maximum=1,
            ),
        ),
    )
    state = OrchestrationState.create(
        (ci, review, tests, inspect),
        epistemic_state=epistemic_state,
        capabilities=(
            Capability(
                "read.file",
                ReplaySafety.CACHEABLE_READ,
                "Read a file from an admitted source revision.",
                required_state_keys=("repo-head",),
            ),
            Capability(
                "write.patch",
                ReplaySafety.OCCURRENCE_SENSITIVE,
                "Apply one occurrence-identified patch mutation.",
                required_state_keys=("failing-tests", "repo-head"),
            ),
            Capability(
                "ci.remote",
                ReplaySafety.CACHEABLE_READ,
                "Inspect remote continuous-integration state.",
                available=False,
                required_state_keys=("repo-head",),
            ),
        ),
        strategy_schemas=(strategy_schema,),
    )

    proposals = (
        ActionProposal(
            "read-primary",
            "read.file",
            {"path": "src/ibae/orchestration.py"},
            target_obligation_ids=(tests.obligation_id,),
            required_state_keys=("repo-head",),
        ),
        ActionProposal(
            "read-duplicate",
            "read.file",
            {"path": "src/ibae/orchestration.py"},
            target_obligation_ids=(tests.obligation_id,),
            required_state_keys=("repo-head",),
        ),
        ActionProposal(
            "patch-first",
            "write.patch",
            {"patch": "repair-a"},
            target_obligation_ids=(tests.obligation_id,),
            required_state_keys=("failing-tests", "repo-head"),
            occurrence_key="patch-occurrence-1",
        ),
        ActionProposal(
            "patch-second",
            "write.patch",
            {"patch": "repair-a"},
            target_obligation_ids=(tests.obligation_id,),
            required_state_keys=("failing-tests", "repo-head"),
            occurrence_key="patch-occurrence-2",
        ),
        ActionProposal(
            "needs-review-state",
            "read.file",
            {"path": "review.json"},
            target_obligation_ids=(tests.obligation_id,),
            required_state_keys=("review-state",),
        ),
        ActionProposal(
            "premature-ci",
            "read.file",
            {"ref": "main"},
            target_obligation_ids=(ci.obligation_id,),
        ),
        ActionProposal(
            "blocked-review",
            "read.file",
            {"path": "review.json"},
            target_obligation_ids=(review.obligation_id,),
        ),
        ActionProposal(
            "unavailable-ci",
            "ci.remote",
            {"ref": "main"},
            target_obligation_ids=(tests.obligation_id,),
        ),
        ActionProposal(
            "unknown-capability",
            "missing.tool",
            {},
            target_obligation_ids=(tests.obligation_id,),
        ),
    )
    batch = ProposalBatch(
        "reference-batch",
        Strategy(
            "repair-reference",
            {"ordering": "declared_sequence", "version": 1},
            schema=strategy_schema,
        ),
        proposals,
        ordering=ProposalOrdering.DECLARED_SEQUENCE,
    )
    transition = admit_batch(state, batch)
    return {
        "batch_id": batch.batch_id,
        "input_state_id": state.state_id,
        "next_state_projection": transition.next_state.compact_projection(),
        "ordered_proposal_ids": [
            proposal.proposal_id for proposal in batch.ordered_proposals
        ],
        "receipt": transition.receipt.canonical_record(),
        "receipt_id": transition.receipt.receipt_id,
    }
