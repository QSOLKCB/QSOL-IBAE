"""Bounded assurance declarations; graph integrity is never execution authority.

Edges describe permitted *support*, not sufficiency or verified external truth.
Only the existing source-bound governance finalizer can accept execution.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ._records import require_fingerprint, require_symbol, require_text
from .canonical import domain_fingerprint

ASSURANCE_GRAPH_VERSION = "IBAE-ASSURANCE-GRAPH-V1"
CALIBRATION_PROFILE_VERSION = "IBAE-CALIBRATION-BINDING-V1"
MAX_ASSURANCE_NODES = 128
MAX_ASSURANCE_EDGES = 512


class AssuranceClass(str, Enum):
    MODEL_PROPOSAL = "model_proposal"
    OBSERVATION = "observation"
    DERIVED_FACT = "derived_fact"
    RUNTIME_RECEIPT = "runtime_receipt"
    CONFORMANCE_RESULT = "conformance_result"
    COMPACT_EVIDENCE = "compact_evidence"
    PROGRESS_EVIDENCE = "progress_evidence"
    BENCHMARK_OBSERVATION = "benchmark_observation"
    RESEARCH_CLAIM = "research_claim"
    GOVERNANCE_DECISION = "governance_decision"
    FINAL_ACCEPTANCE = "final_acceptance"


# Closed, versioned support relation. In particular, no path starts from model,
# benchmark or research text and ends in an authoritative evidence class.
_SUPPORT = frozenset({
    (AssuranceClass.RUNTIME_RECEIPT, AssuranceClass.OBSERVATION),
    (AssuranceClass.RUNTIME_RECEIPT, AssuranceClass.COMPACT_EVIDENCE),
    (AssuranceClass.OBSERVATION, AssuranceClass.DERIVED_FACT),
    (AssuranceClass.OBSERVATION, AssuranceClass.PROGRESS_EVIDENCE),
    (AssuranceClass.DERIVED_FACT, AssuranceClass.PROGRESS_EVIDENCE),
    (AssuranceClass.PROGRESS_EVIDENCE, AssuranceClass.GOVERNANCE_DECISION),
    (AssuranceClass.COMPACT_EVIDENCE, AssuranceClass.FINAL_ACCEPTANCE),
    (AssuranceClass.CONFORMANCE_RESULT, AssuranceClass.FINAL_ACCEPTANCE),
    (AssuranceClass.GOVERNANCE_DECISION, AssuranceClass.FINAL_ACCEPTANCE),
})


def _exact_text(name: str, value: str, validator=require_symbol) -> str:
    if type(value) is not str:
        raise TypeError(f"{name} must be an exact string")
    return validator(name, value)


@dataclass(frozen=True, slots=True)
class AssuranceNode:
    key: str
    evidence_class: AssuranceClass
    evidence_id: str

    def __post_init__(self) -> None:
        _exact_text("node key", self.key)
        if type(self.evidence_class) is not AssuranceClass:
            raise TypeError("evidence class must be an exact AssuranceClass")
        _exact_text("evidence id", self.evidence_id, require_fingerprint)

    def canonical_record(self) -> dict:
        self.__post_init__()
        return {"key": self.key, "evidence_class": self.evidence_class.value,
                "evidence_id": self.evidence_id}


@dataclass(frozen=True, slots=True)
class AssuranceEdge:
    source: str
    target: str

    def __post_init__(self) -> None:
        _exact_text("source", self.source)
        _exact_text("target", self.target)
        if self.source == self.target:
            raise ValueError("self support is forbidden")


@dataclass(frozen=True, slots=True)
class AssuranceGraph:
    """A support manifest, not an evidence validator or finalization receipt.

    An evidence_id is a reference requiring the corresponding source validator.
    Constructing a node labelled observation cannot produce an observation.
    """
    nodes: tuple[AssuranceNode, ...]
    edges: tuple[AssuranceEdge, ...]

    def __post_init__(self) -> None:
        if type(self.nodes) is not tuple or type(self.edges) is not tuple:
            raise TypeError("graph collections must be exact tuples")
        if len(self.nodes) > MAX_ASSURANCE_NODES or len(self.edges) > MAX_ASSURANCE_EDGES:
            raise ValueError("assurance graph exceeds bounded profile")
        for node in self.nodes:
            if type(node) is not AssuranceNode:
                raise TypeError("graph nodes must have exact type")
            node.__post_init__()
        for edge in self.edges:
            if type(edge) is not AssuranceEdge:
                raise TypeError("graph edges must have exact type")
            edge.__post_init__()
        keys = tuple(n.key for n in self.nodes)
        pairs = tuple((e.source, e.target) for e in self.edges)
        if keys != tuple(sorted(set(keys))) or pairs != tuple(sorted(set(pairs))):
            raise ValueError("graph members must be unique and canonically ordered")
        by_key = {n.key: n for n in self.nodes}
        for edge in self.edges:
            if edge.source not in by_key or edge.target not in by_key:
                raise ValueError("support endpoints must exist")
            if (by_key[edge.source].evidence_class, by_key[edge.target].evidence_class) not in _SUPPORT:
                raise ValueError("forbidden assurance promotion")
        # _SUPPORT is a DAG of classes; this also forbids graph cycles.

    def canonical_record(self) -> dict:
        self.__post_init__()
        return {"protocol_version": ASSURANCE_GRAPH_VERSION,
                "scope": "support_declaration_requires_source_validation",
                "grants_authority": False,
                "nodes": [n.canonical_record() for n in self.nodes],
                "edges": [{"source": e.source, "target": e.target} for e in self.edges]}

    @property
    def graph_id(self) -> str:
        return domain_fingerprint("ibae.assurance.graph.v1", self.canonical_record())


def assurance_support_contract() -> dict:
    """Machine-readable closed support rules, including verifier obligations."""
    return {"protocol_version": ASSURANCE_GRAPH_VERSION,
            "classes": sorted(c.value for c in AssuranceClass),
            "allowed_support": [{"source": a.value, "target": b.value}
                                for a, b in sorted(_SUPPORT, key=lambda p: (p[0].value, p[1].value))],
            "unknown_edges": "deny",
            "integrity_is_authenticity": False,
            "graph_is_final_acceptance": False,
            "required_validation": {
                "runtime_receipt": "exact_native_source_seal",
                "observation": "governed_admission_and_native_source",
                "derived_fact": "validated_dependency_dag_and_governed_source_records",
                "compact_evidence": "exact_native_reducer_seal_and_authorization_manifest",
                "conformance_result": "independently_replayed_frozen_fixture_and_source_commit",
                "governance_decision": "exact_policy_binding_and_native_decision_lineage",
                "progress_evidence": "policy_bound_progress_contract_and_native_lineage",
                "final_acceptance": "existing_governance_receipt_chain_and_required_gates"}}


class ResearchClaimStatus(str, Enum):
    HYPOTHESIS = "hypothesis"
    REPORTED = "reported"
    EXTERNALLY_ARCHIVED = "externally_archived"


@dataclass(frozen=True, slots=True)
class ResearchClaim:
    claim_key: str
    status: ResearchClaimStatus
    source_id: str
    text: str

    def __post_init__(self) -> None:
        _exact_text("claim key", self.claim_key)
        if type(self.status) is not ResearchClaimStatus:
            raise TypeError("research status must be exact and non-operational")
        _exact_text("source id", self.source_id, require_fingerprint)
        _exact_text("claim text", self.text, require_text)

    def canonical_record(self) -> dict:
        self.__post_init__()
        return {"claim_key": self.claim_key, "status": self.status.value,
                "source_id": self.source_id, "text": self.text,
                "operational_authority": False}


@dataclass(frozen=True, slots=True)
class CalibrationBinding:
    """References an already governed profile; it cannot promote a claim.

    Validation method/corpus are provenance references, not attestations.
    Operational values continue to live only in the bound governance and
    continuation policy. Policy changes necessarily change this identity.
    """
    governance_id: str
    continuation_policy_id: str
    progress_contract_id: str
    validation_method: str
    validation_corpus_id: str

    def __post_init__(self) -> None:
        for name in ("governance_id", "continuation_policy_id", "progress_contract_id", "validation_corpus_id"):
            _exact_text(name, getattr(self, name), require_fingerprint)
        _exact_text("validation method", self.validation_method)

    def canonical_record(self) -> dict:
        self.__post_init__()
        return {"protocol_version": CALIBRATION_PROFILE_VERSION,
                "governance_id": self.governance_id,
                "continuation_policy_id": self.continuation_policy_id,
                "progress_contract_id": self.progress_contract_id,
                "validation_method": self.validation_method,
                "validation_corpus_id": self.validation_corpus_id,
                "promotes_research_claims": False}

    @property
    def profile_id(self) -> str:
        return domain_fingerprint("ibae.calibration.binding.v1", self.canonical_record())

    def require_policy_binding(self, governance_id: str, continuation_policy_id: str,
                               progress_contract_id: str) -> None:
        self.__post_init__()
        for name, value in (("governance_id", governance_id),
                            ("continuation_policy_id", continuation_policy_id),
                            ("progress_contract_id", progress_contract_id)):
            _exact_text(name, value, require_fingerprint)
            if value != getattr(self, name):
                raise ValueError("calibration profile drift")
