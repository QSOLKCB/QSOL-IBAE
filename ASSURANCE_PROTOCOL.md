# v0.6A assurance and calibration contracts

Status: v0.6A implementation candidate. This protocol adds no execution command,
finalization path, provider connection or effect permission.

## IBAE-ASSURANCE-GRAPH-V1

`assurance_support_contract()` emits the closed machine-readable class/support
relation. `AssuranceGraph` is a bounded support manifest: at most 128 exact nodes
and 512 exact edges, unique and lexicographically ordered. Node keys are at most
128 ASCII characters; evidence references are lowercase SHA-256 identities.
Every edge must name existing nodes and match the closed support relation.
Unknown classes, edges, duplicates, self-support and cycles reject.

Permitted relations:

- Native runtime receipt may support observation or compact evidence.
- Observation may support derived fact or progress evidence.
- Derived fact may support progress evidence.
- Progress evidence may support governance decision.
- Compact evidence, conformance result and governance decision may support final
  acceptance, subject to the existing complete finalization gate.

No outgoing support relation exists for model proposal, benchmark observation,
or research claim. In particular, there is no direct or transitive promotion
from those classes into operational evidence or governance authority.

The canonical manifest declares `grants_authority=false` and
`scope=support_declaration_requires_source_validation`. Its identity uses
`ibae.assurance.graph.v1`. An evidence ID is a reference, not proof that the
referenced object exists, is authentic, is current, or satisfies a claim.
Constructing an OBSERVATION-labelled node does not create an observation.

Support is necessary structural eligibility, never sufficient acceptance.
The machine-readable contract names the additional validator obligations:
exact native runtime seal; governed admission and source binding; policy-bound
progress semantics and native lineage; or the existing complete governance
receipt chain and required gates. No graph method returns a final-acceptance
receipt. `GovernanceWrapper` remains the sole implemented finalization surface.
A serialized graph cannot replace its native source-bound inputs.

## Research claims and operational calibration

`ResearchClaim` admits only `hypothesis`, `reported`, and `externally_archived`.
All carry bounded data-plane text, a source identity, and
`operational_authority=false`. Archived provenance does not establish empirical
truth. There is deliberately no claim-side `validated_in_profile` option or
method that promotes a claim to a policy threshold.

`IBAE-CALIBRATION-BINDING-V1` references one exact existing governance policy,
continuation policy and progress contract together with a validation-method
symbol and corpus identity. `require_policy_binding` rejects drift. Its
`ibae.calibration.binding.v1` identity changes if any binding or provenance
changes. Validation method/corpus are declarations requiring audit, not a new
attestation mechanism. Operational values continue to come exclusively from
the existing governed policies, not from this record or research text.

An operational policy revision requires the existing explicit governance
construction/admission path and a newly bound identity. Automatic recalibration,
research-threshold promotion, external producer authentication and empirical
threshold validation are not implemented by this phase.

## Verification

`tests/test_assurance.py` checks the closed relation, all non-authoritative
source/target combinations, malformed and unknown fields, bounded/canonical
collections, policy drift and research-text noninterference. Supervisor tests
and the v0.6A fixture separately check the live source/authority projection.
