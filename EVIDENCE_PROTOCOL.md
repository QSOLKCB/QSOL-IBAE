# Compact Evidence Protocol

Status: accepted v0.4 implementation contract; its schema and identities are
unchanged by v0.5.

`IBAE-COMPACT-EVIDENCE-V1` separates potentially large deterministic execution
state from routine evidence transport. It is independently implemented from
the bounded evidence-reduction pattern described by QEC/VE-24. No QEC/VE-24
implementation code, GPU kernel, geometry, lane meaning, constant, asset, or
physical/quantum claim is incorporated.

## Authority boundary

```text
Rust execution receipts / canonical case records
        |
        v
opaque Rust streaming reducer
        |
        v
bounded compact evidence receipt
        |
        v
Python governance interpretation
```

The reducer performs exact deterministic bookkeeping. It cannot grant task or
governance acceptance. Python cannot mutate its retained state directly.

## Declared profile and bounds

The implemented evidence profile is a closed versioned profile for exact case
counts, exact runtime/accounting sums, ordered canonical aggregate identities,
governed runtime-admission correspondence, continuous runtime boundaries, and
the absence or presence of reported verifier mismatches.

Its hard bounds are:

- at most 1,000,000 admitted cases;
- at most 256 governed authorization-manifest entries;
- at most 16,384 canonical UTF-8 bytes in one case/child input envelope;
- at most 32 retained failure details;
- at most 4,096 canonical bytes in one retained failure detail;
- at most 2,048 canonical UTF-8 bytes in the routine compact receipt;
- at most 262,144 canonical UTF-8 bytes in an explicit expansion response.

Successful cases are reduced immediately and are never retained as an O(N)
success list. Normal successful receipt size is therefore bounded independently
of admitted case cardinality. Failure retention is separately bounded to
131,072 canonical detail bytes plus fixed reducer metadata and container
overhead. Every count uses checked `u64` arithmetic, and attempted over-bound or
overflowing input leaves the accumulator unchanged.

Zero-case finalization is rejected. A finalized reducer is immutable.

## Two-stage execution binding

The accumulator first binds task, governance, and orchestration identities plus
the bounded governed authorization manifest, then streams canonical case
records. A live runtime case is admitted only with the non-constructible native
seal for that exact runtime receipt, and only when its action ID, tool name,
arguments identity, dependency identity, command class, governed tool-admission
receipt, and exact cache-reuse policy match one manifest entry. The manifest is
capped at 256 entries. A sealed `record_retry` may follow a known manifest
admission and participates in exact accounting and runtime continuity, but its
v0.3 receipt intentionally carries no tool/argument/dependency fields and it
cannot satisfy manifest action coverage by itself. The reducer retains only the
bounded distinct cold-proven action set, not an O(N) success list.

Because the frozen v0.1/v0.3 cache key intentionally excludes v0.2 admission
and capability identity, an action's first admitted evidence receipt must be an
accepted `cold_execution`. A `cache_hit` is admitted only after that exact
action ID has cold provenance earlier in the same continuous evidence stream.
This conservatively rejects stale same-name capability-contract cache reuse
without changing accepted v0.3 identities.

`aggregate_summary()` seals ingestion and returns fixed-shape roots, exact
counts, exact counter sums, the authorization-manifest identity/count, and the
first/last receipt/state boundary for one continuous runtime session. Governance
uses that native-sealed summary to construct the execution receipt.
`finalize(execution_identity)` then binds the resulting execution correctness
identity exactly once and emits the compact receipt with its own native seal.

This order avoids a circular identity dependency while allowing governance to
cross-check:

- governed authorization-manifest identity and count;
- ordered runtime-admission aggregate identity;
- input aggregate identity;
- result aggregate identity;
- runtime/case-receipt aggregate identity;
- total transition/case count;
- initial/final runtime receipts and states in one session;
- final execution identity.

The aggregate identities are ordered domain-separated SHA-256 chains over
canonical case identities. Reordering cases, changing a result, or changing an
effect occurrence changes the corresponding aggregate.

## Receipt shape and status

The receipt contains only fixed-shape or bounded metadata:

- protocol and sufficiency-profile identifiers;
- task, governance, orchestration, and execution identities;
- exact passed/failed/rejected/total counts;
- exact request, actual-execution, cache-hit, retry, mutation, invariant,
  canonical-mismatch, and receipt-mismatch counters;
- governed authorization-manifest identity/count;
- ordered admission/input/result/receipt aggregate identities;
- one continuous runtime boundary containing first/last receipt IDs,
  initial/final state IDs, and session ID;
- first-failure index and bounded-detail availability counts;
- case-versus-child item counts and declared limits;
- scoped `complete_no_failures` or `complete_with_failures` status;
- canonical domain-separated receipt identity.

It never uses governance `accepted` status. Only direct-case,
`complete_no_failures`, live-source-bound evidence is admitted by v0.4 final
governance.

## Structural validation and live source binding

An independent Python validator checks exact fields, protocol/profile, canonical
types, count conservation, failure-summary consistency, declared hard bounds,
lowercase SHA-256 forms, receipt size, and the domain-separated receipt hash.
Unknown or malformed fields fail closed.

A parsed self-consistent receipt is structural-only. It is useful for transport
validation but is not sufficient for final acceptance. Live dispatch returns a
non-constructible seal bound to the exact serialized runtime receipt; the
reducer requires it before live-case mutation. Aggregate-summary and final
compact-receipt calls return separate non-constructible seals bound to those
exact records and to whether every input was live-source-bound. Constructing or
rehashing a Python record cannot create any of those seals. Child ingestion
likewise requires the exact native seal for the child receipt.

These seals prove only that the supported native dispatch/reducer path admitted
the exact records in this process. They are not signatures, remote attestation,
durable provenance, producer authentication, or proof that an external system
told the truth.

## Evidence sufficiency

For its exact declared verifier scope, a validated source-bound direct receipt
can establish:

- how many canonical case records the reducer admitted;
- their reported passed/failed/rejected classification;
- exact admitted counter totals;
- exact correspondence between the governed bounded authorization manifest and
  the distinct observed runtime action set;
- ordered commitments to the supplied admission/input/result/receipt
  identities;
- continuous first-to-last state/receipt history within one runtime session;
- whether the supplied cases reported an invariant/canonical/receipt mismatch;
- correspondence with the execution receipt manifest, roots, runtime boundary,
  count, and final execution identity.

It does not establish external truth, complete semantic correctness outside the
declared case verifier, producer identity, evidence durability, benchmark
superiority, physical truth, or cryptographic proof from a non-cryptographic
fold.

## Selective failure expansion

Only failed/rejected inputs may retain bounded detail. The normal receipt emits
counts and the first failure index, not the detail list. After finalization an
explicit request must name the exact parent receipt, start index, and bounded
maximum detail count. A wrong parent, zero/oversize request, malformed schema,
or unfinalized reducer fails closed. The response carries the parent identity
and its own domain-separated expansion identity.

Because only the first bounded failure details are retained, v0.4 implements
bounded deterministic inspection rather than arbitrary durable auditability.
`IBAE-EVID-007` therefore remains partially enforced.

## Fast regression observation

The optional FNV-1a-64 fold is returned only through a separate record with:

```text
correctness_authority: false
algorithm: fnv1a64-non-cryptographic-v1
```

It is absent from the compact receipt and every correctness/final identity.
Enabling, disabling, or changing the fold cannot change the canonical evidence
receipt. It may detect convenient regressions but cannot substitute for
SHA-256 validation.

## Hierarchical composition boundary

A live, failure-free child compact receipt can be schema/SHA/context validated
before a parent incorporates its checked counts and aggregate identities.
Children reporting failures are rejected by the v1 composition path. Child
aggregation is deterministic and bounded, but the v1 child transport root is
intentionally grouping-sensitive. It is therefore not admitted into v0.4 final
correctness identity.

Arbitrary chunk-plan-neutral hierarchical roots, range inclusion proofs, and
durable shard replay locators require a later versioned composition profile.
No distributed, worker, GPU, or execution-plan semantics are implemented here.

## Separate v0.5 continuation evidence

`IBAE-CONTINUATION-EVIDENCE-V1` is a separate fixed-shape receipt over progress
and lease-decision aggregates. It may bind this v0.4 compact receipt by ID, but
does not add fields to it, replace its native source requirements, or promote
continuation state into execution evidence. Its own 4,096-byte ceiling and
trust scope are defined in `CONTINUATION_PROTOCOL.md`.
