# Supervisor projection and recovery protocol (v0.6A)

Status: offline implementation candidate. No live model, network transport,
effectful execution, durable native resume, authentication, or final acceptance
is introduced by this protocol.

## Versioned records and authority boundary

- `IBAE-SUPERVISOR-PROJECTION-V1`: a deterministic observation of a verified
  live `SupervisorContext`.
- `IBAE-FRESH-CONTEXT-V1`: a bounded canonical handoff containing that projection,
  its identity, and a separately domain-separated handoff identity.
- `IBAE-RECOVERY-CLASSIFICATION-V1`: a non-authorizing classification of an
  existing live task or a separately initialized task.
- `IBAE-AUTHORITY-EPOCH-V1`: native epoch/revocation observation, defined and
  owned by Rust. Its separate identity leaves v0.2–v0.5 records unchanged.

Identity domains are `ibae.supervisor-projection-id.v1`,
`ibae.fresh-context-id.v1`, and `ibae.authority-epoch-status-id.v1`.
Every supervisor projection explicitly says `authoritative: false`. Handoffs
and recovery results explicitly say `restores_native_authority: false`.
Classification results also say `grants_authority: false` and
`final_acceptance: false`.

`CAPABILITY != AUTHORITY`. An available capability is shown independently from
its governance permission, supported runtime class, unresolved dependencies,
and bounded proposal eligibility. A serialized authority label or a caller's
`authorized: true` cannot replace the separate, exact, non-constructible native
supervisor capability. A capability from an equal-ID duplicate native runtime
does not authorize the original runtime.

## Exact live construction

`SupervisorContext` references an exact task receipt, governance receipt and
policy, continuation policy and live native-sealed state, orchestration state,
and Rust runtime. It can additionally carry the native supervisor capability
and an optional exact `CalibrationBinding`.

Projection construction:

1. Requires exact record/scalar/container types and reconstructs the existing
   governance and orchestration contracts for semantic validation.
2. Matches the task, governance, continuation receipt, policy, progress contract,
   orchestration endpoint, and runtime endpoint to the native-sealed state.
3. Invokes the existing native checkpoint-snapshot verifier against the exact
   live native session and complete actual snapshot. Retired lineage and a
   substituted equal-ID runtime fail closed.
4. Reads source-bound native epoch status. A supplied capability must belong to
   this exact native instance and lineage. Missing capability is explicit;
   having an inspectable runtime does not supply it.
5. Verifies any calibration binding against those exact active policy identities.
6. Computes the bounded supervisor decision surface directly from the sources.

No serialized record can initialize a native runtime, restore a seal, reset an
epoch, replenish budgets, or supply a request capability. Revoked live lineage
remains readable for diagnosis, while future authority-bearing actions remain
blocked by Rust.

## Decision-sufficient observation

The projection includes the entire declared v1 decision surface:

- Canonical ready, dependency-blocked, explicitly blocked, and satisfied
  obligation facts; bounded blocker counts and auditable source identities.
- Available capabilities, governance permission identities/classes, dependency
  resolution, supported read-only runtime classes, and separate cold-read and
  cache-reuse proposal facts.
- Actual remaining requests, cold executions, retries, and zero mutation
  capacity; history retained/capacity/unused slots; actual resident orchestration
  capacity; request-decision, schedule, progress-observation, and strategy-recovery
  capacity; componentwise remaining continuation ceiling.
- Live progress classification, evidence and ordered aggregate identities,
  strategy identity, pending grant, last denial, cycle evidence, continuation
  eligibility, legal recovery proposal classes, and the finite terminal-denial
  recording step when exhaustion evidence has not yet been recorded.
- Native authority epoch, revocation, explicit capability presence, control
  classification, and trusted control provenance.
- Completion eligibility for deterministic gate validation, the exact required
  gate names, and the invariant `final_acceptance: false`.
- Explicit observed, derived, proposed, and unknown epistemic classes. Unresolved
  model-proposed text does not become an admitted dependency or control policy.

History slots are rolling retention capacity, not additional tool-execution
credits. Cold execution exhaustion does not eliminate an otherwise permitted
cache-reuse candidate while requests remain. A cache-reuse proposal still needs
the exact unchanged cache/dependency key; the projection does not claim every
available tool owns a matching cache entry. Cache content is committed by the
bound runtime-state identity. A permission forbidding reuse does not prohibit
an otherwise permitted cold read.

Both read branches share the structural admission prerequisites: an admitted
strategy schema, a representable next logical tick, a ready target, an available
cacheable capability, resolved mandatory dependencies, an owned compatible
permission, active supervisor control, and remaining request budget. Valid
strategy parameter schemas have inhabited domains; exact parameter values,
arguments, target selections, dependency digests, ordering, batch bounds and
receipt identities still pass the unchanged concrete admission gates. Full
registries and rolling histories do not themselves exhaust read capacity.

Read eligibility follows the actual governed dependency class: mandatory
capability dependencies rule out PURE_READ, while SNAPSHOT_READ requires a
mandatory dependency or a resolved record available for proposal selection.
An initial state without bound progress cannot advertise continuation request
eligibility; observing exact bound progress is a separate admissible step.

Admission-parity boundary (checked by ordinary contract witnesses):

| Existing admission predicate | Projection treatment |
| --- | --- |
| Admitted strategy key and exact schema | At least one admitted schema; concrete key, schema and typed parameters checked on proposal |
| Batch count and deduplication | A singleton fits every valid positive batch limit and has no batch-local duplicate |
| Capability lookup, availability and argument allowlist | Registry membership and availability required; concrete arguments checked on proposal (empty mapping is valid) |
| Cacheable replay and ordering | Only cacheable reads advertised; effect/volatile ordering and occurrence registries are outside this surface |
| Known ready targets | At least one ready target required; every selected target still validated |
| Mandatory and selected dependencies | Mandatory resolution and possible read class required; selected keys and exact digest still validated |
| Logical clock advance | One next tick must fit the existing identity integer bound |
| Governance permission and requester | Owned compatible permission required; deterministic requester, identities and receipt binding checked at admission |
| Native execution resources | Requests required for both branches; executions for cold reads; reuse permission and candidate cache for cache branch |
| Native lineage and supervisor control | Exact bound source, active authority, no governance block, no pending grant and incomplete state required |

Exhausted retry/continuation/observation/recovery capacity, full rolling history,
full record registries, and cycle evidence do not independently invalidate an
otherwise admissible read. Concrete invalid arguments, extra unresolved selected
dependencies, an occurrence key, oversized batches, mixed invalid targets, or
mismatched strategy/receipt identity remain rejected even when the existential
proposal class is available. No projection field is an admission receipt.

Legal next-action classes describe the bounded supervisor proposal/control
surface. They do not replace normalized concrete proposal admission, exact
cache-key matching, progress/strategy receipt validation, or final gate checks.
In particular, proposing a material strategy does not imply that it will be
admitted. Completion eligibility does not assert accepted finalization.
`record_terminal_continuation_denial` is separately exposed when an active,
unblocked, incomplete context with exact progress and no pending grant has
exhausted continuation capacity but lacks exhaustion-denial evidence. It is not
a lease grant or recovery extension. With request decisions already exhausted,
the existing native v0.5 terminal marker consumes no additional resource or
continuation tick; after recording it the proposal disappears. A current
governance block suppresses this proposal until independently cleared.

The decision-sufficiency claim is:

```
P(S1) = P(S2) => the declared v1 next-action decision surfaces agree.
```

The exact surface is explicitly present in the projection; live actions still
revalidate their native authority and sources. Equality does not imply full
state reconstruction, producer authenticity, remote attestation, or an ability
to interchange two native capabilities. Tests cover equal independently bound
contexts, differing decision-relevant state, and omitted non-authoritative
model-proposed data. Larger semantic contracts require a new projection version.

## Data plane and provenance

`SupervisorData` carries a closed origin class, source fingerprint, and bounded
text. Supported origins cover model, worker, tool, repository, document, web,
download, OCR/UI, benchmark, and externally supplied receipt content. Every
entry has `control_authority: false`.

The text may contain imperatives or purported authorizations. Projection logic
does not parse it for permissions, change thresholds from it, or pass it into
the governance decision. A source fingerprint proves only selected content
identity, not source authenticity. Research and benchmark text cannot promote
itself into operational calibration. Tests vary hostile content across every
origin while comparing both the actual decision surface and actual governed
continuation decisions.

Descriptions, full values, dense dependency edges, detailed argument schemas,
and full histories remain in the bound source records. Their compact identities,
counts, and readiness are retained where relevant. Source details remain
inspectable from the live context. This protocol does not promise durable
storage or arbitrary evidence retrieval after those sources are lost.

## Bounds and strict transport validation

The projection is capped at 1,048,576 canonical UTF-8 bytes; a handoff is capped
at that limit plus 1,024 bytes. The declared output profile covers 128 compact
obligations, 64 compact capabilities, 256 epistemic references, the existing
bounded strategy-schema registry, and at most 16 data entries of 4,096 UTF-8
bytes each. Even sixfold JSON escaping of every data character is included.
Dense DAG edges, arbitrary canonical payload values, and long descriptions do
not expand the output. Maximum-registry/dense-DAG tests verify no clipping.

Transport copying validates exact inert JSON types, depth, node and collection
bounds, bounded integers, valid UTF-8, and incrementally charges aggregate JSON
bytes including escaping before serialization. Parsing enforces closed nested
schemas, exact booleans/u64/enums, sorted unique sets, identities, native status
identity and source correspondence. Unknown fields and malformed authority
shapes reject even if outer hashes have been recomputed.

Returned records are isolated copies. Structural parsing of a self-consistent
record establishes record integrity only. It never establishes current native
authority or truth of the historical claims inside it.

## Fresh-context equivalence

`FreshContextHandoff(SupervisorProjection(context))` requires no conversation
transcript. Projection and handoff objects retain a private original native
lineage/runtime witness that is never serialized or part of canonical identity.
`FreshContextHandoff.from_record(...)` alone performs bounded structural
validation only and cannot resume an existing task. Supplying
`source_handoff=original` additionally retains the original witness only after
complete canonical correspondence with that original is checked.
`fresh_session_surface(handoff, context)` requires this original in-process
witness, independently
reprojects the exact supplied live authorities, compares the complete canonical
handoff, and returns only the equal decision surface.

An advanced runtime, retired continuation generation, changed governance or
orchestration, missing/replaced capability, changed policy profile, and changed
authority epoch cannot silently reuse the old handoff. In particular, revoking
authority makes the earlier handoff stale even though frozen legacy snapshot
bytes and already applied limits remain unchanged. A new handoff may describe
the revoked state, but it cannot resume revoked authority.

## Four recovery classifications

1. `resume_verified_live_task`: the entire handoff matches the exact current
   live source context, its retained original native witness, and its genuine
   active supervisor capability. An independently constructed equal-ID context
   cannot substitute for that original witness. This
   establishes eligibility to continue that existing task through ordinary
   governed transitions, not permission to bypass a blocker or final gate.
2. `start_fresh_authorized_task`: a different task and runtime have already
   been independently established with their own verified native capability.
   Their exact task acceptance contract must select both
   `recovery_evidence_id = handoff.handoff_id` and
   `recovery_source_task_id = handoff.projection.sources.task_id`. The classifier
   neither creates this task nor grants its authority. The selected old handoff
   is integrity-checked historical observation only; it does not authenticate
   the old producer or prove old claims/current truth. This path can operate
   without the old runtime because all task authority and budgets come from the
   separately authorized new context. No old limits, native seals, progress
   endpoints, or acceptance status are transferred.
3. `ask_human_authorization`: the existing live context is verified but has no
   usable supervisor capability, or a proposed fresh task lacks the distinct
   exact authority/evidence binding. Human prose inside source data does not
   satisfy this requirement. The caller must obtain actual separately granted
   authority and invoke classification again.
4. `stop_unverifiable`: no exact live source can be verified and no independently
   authorized fresh task selects the bounded historical evidence, or existing
   live replay mismatches/stales. No guessing or record-only native resume is
   attempted. Malformed input records reject before classification.

The classifier is diagnostic and performs no execution, network call, effect,
grant, new-task creation, or finalization. Cross-process restoration of old
native authority remains unsupported.

## Invariants and compatibility

This implementation affects the v0.6A projection/authority/control contracts
and existing IBAE-LAY-001/002/003, DET-001/003/005, BND-005/006/007/008,
PROG-001/002/003/004, GOV-004/005/006/007, ORCH-002/005/006, RT-001/002/003,
AI-001/003/004/005/006/008, ID-001/002/003/007 and EVID-001/002/007 boundaries.
The new context contracts are scoped to this declared offline in-process
surface; broader architecture-only statuses are not promoted by this file.
Frozen legacy v0.2–v0.5 canonical schemas and fixtures are unchanged. New
projection, handoff, and epoch records have new identity domains. No benchmark
value enters authority or correctness, and no performance claim is introduced.

Evidence: `tests/test_supervisor.py`, `tests/test_authority_epoch.py`, the
versioned model-free v0.6A fixture, and the existing continuation/governance/
runtime conformance suites.
