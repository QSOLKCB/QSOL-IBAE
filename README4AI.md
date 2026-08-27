# QSOL-IBAE — Machine Context

## PROJECT PURPOSE

QSOL-IBAE is an invariant-bounded execution substrate intended to sit beneath an OpenAI supervisory model. Its purpose is to reduce redundant tool work, make bounded continuation auditable, preserve deterministic execution semantics, and move deterministic bookkeeping out of the model's cognitive workload.

## CURRENT PHASE

Merged v0.1 deterministic kernel and architecture contract, the accepted
**v0.2 deterministic Python orchestration reference**, the accepted **v0.3 Rust
deterministic runtime**, the accepted **v0.4 deterministic governance/compact
evidence implementation**, and the **v0.5 objective-progress/bounded-
continuation implementation candidate**.

v0.2 implements canonical obligations/DAG readiness, proposal/admission separation, replay-safe-only batch deduplication, persistent bounded effect occurrence ownership, explicit independent-versus-declared batch ordering, explicit epistemic state classes with reuse-path- and unadmitted-proposal-neutral correctness identity, admitted typed strategy-specific parameter allowlists, capability-owned semantic argument allowlists with non-correctness observational metadata, bounded model-facing collections/text/integers and canonical payload traversal, canonical state/receipt identities, structured rejection/recovery records, and `IBAE-LOGICAL-CLOCK-V1` reference semantics.

PR #4 merged exact reviewed head
`a3009000998aba90375eceba7b0dfa2e8fba1551` at merge commit
`de5239b8c7980f8211da109b42bdbc3449be83ba` after the v0.3 gate passed.
The accepted runtime keeps orchestration semantics in Python and moves the
implemented v0.1 read-execution mechanics into a private Rust session reached
through PyO3/maturin and `IBAE-RUNTIME-PROTOCOL-V1`. Its only admitted runtime
commands are `execute_read` and `record_retry` for legacy sessions.

PR #5 merged exact reviewed head
`7a4fb416a45d0e0e43354007d869573bfec3129f` at merge commit
`849b188fcc826184e3afa2617dd1362b475a4cd3` after the v0.4 gate passed.
v0.4 adds a Python governance wrapper with a closed OpenAI-only provider class,
explicit tool authority, an exact bounded authorization manifest linking typed
v0.2 admissions to matching v0.3 read receipts and cache policy, and
separate canonical receipt classes. A Rust streaming reducer emits
`IBAE-COMPACT-EVIDENCE-V1` records capped
at 2,048 bytes for the declared profile, independent of admitted case
cardinality. The current governed batch ceiling is 64 actions; the reducer's
defensive authorization ceiling is 256. Bounded failure expansion is
exceptional. Structural receipt
validation proves canonical consistency only; non-constructible native seals
bind exact live runtime, summary, and compact-receipt records for final
acceptance, and neither mechanism authenticates a producer or proves external
truth. The finalizable v1 execution profile is cacheable reads plus optional
sealed known-admission retry-accounting transitions; retries cannot establish
read coverage alone.

v0.5 adds `IBAE-OBJECTIVE-PROGRESS-V1` and
`IBAE-CONTINUATION-LEASE-V1`. Progress is an exact comparison of declared
obligation/evidence measures; activity, confidence, and wall time are not
progress authority. Classification and completion are derived from exact bound
prior/current sources; external counters require a source-bound native
observation matched to its governed tool admission and a contiguous semantic
value/basis endpoint that excludes receipt identity. Policy, state, and native
context bind the exact admitted progress contract and its orchestration
lineage; the built-in contract counts both unsatisfied and blocked obligations,
and observation refreshes live control state. Structured strategy changes
revalidate admitted strategy, capability
frontier, targets, dependency path, recovery mode, and runtime-derived cycle
evidence; paraphrase is excluded from identity. Governance precommits an exact
initial budget, finite indexed schedule, cumulative ceiling, request cap, and
strategy-recovery cap; initial history retains six transitions and the request
cap reserves ordinary denial capacity beyond the schedule. If ordinary
decisions are consumed before the schedule, one canonical terminal
request-limit receipt marker enters native lineage without increasing the
ordinary ledger; if both ledgers are exhausted, it cites the lease-ceiling
denial instead. Repeats are state-neutral. The supervisor requests, governance grants or denies,
and an opt-in Rust session applies only a full validated governance-issued
grant. Trusted module initialization captures the exact evaluator, context
observer, and application committer once in native storage and removes the
bootstrap entrypoint. Session creation clones only those originals into a
non-serialized per-instance native authority and
returns a separate once-issued, session-scoped supervisor request capability;
a native integrity graph detects in-place mutation of their bound code, all
reachable mutable Python function dependencies regardless of module, and
descriptor-backed functions. Exact request typing precedes callbacks and native
integrity is rechecked immediately after evaluation, before output is read or
sealed. Authority-bearing request, progress, and strategy canonical fields,
including the progress contract and measures, are restricted to exact
callback-free scalar/container/record types before the first governance
comparison; after evaluation Rust rederives the exact progress
and optional admitted-strategy identities and predicate before issuing a grant
seal. The complete initial zero-decision state accepts only exact registered
context types and rederived progress bound to the native authority, then is
sealed only after Rust derives its exact decision/progress seeds; each reseal
advances the sole live native generation and retires its predecessor; and
context observation/application commit and checkpoint construction/resume
require the matching live native session and complete snapshot. Observer entry
validates callback-free exact progress before comparison, and Rust permits only
the closed observation endpoints to differ between prior and resulting
lineages; consumed-progress and other decision authority must remain identical.
Benchmark objects are not inspected or forwarded into governance evaluation;
a public principal label,
reconstructed record, mutable Python validator, or equal-ID duplicate session
is insufficient. An exact
request seal enters the pinned evaluator, then Rust validates the request and
grant against the live session before issuing the grant seal used by
`apply_lease`. Native lineage protects recovery and decision/progress semantics,
including the full ordered progress count/aggregate, live strategy identity,
and terminal ceiling marker. Context observation cannot rewind strategy
lineage; only an admitted strategy-change grant advances it. Each measurable
progress identity is single-use for progress-based admission. An accepted
application changes exact limits plus one runtime logical tick while consuming no
tool/runtime resource counter or history; rejection is state-neutral. The
compact state exposes effective remaining request and schedule decisions plus
remaining progress-observation capacity, suppressing objective-progress
recovery when that evidence bound is full.
Structural in-process checkpoints require live status, strategy, and that same
effective capacity and reject a false semantic partial reason at checkpoint
construction; semantic partial evidence derives from the
checkpoint, terminal ceiling partials cite the exact lineage marker receipt,
and partial construction revalidates that marker against the live state even
if a frozen checkpoint was mutated. Request-cap exhaustion with ungranted
schedule slots also binds this one-shot terminal marker and has the same normal
non-watchdog partial path. Watchdog lease exhaustion is identity-bearing, checked against
effective checkpoint capacity, but
non-authoritative. Existing v0.2-v0.4 schemas and fixture bytes remain
unchanged.

No OpenAI SDK integration, effect execution, durable cross-process runtime
reconstruction, GPU execution, distributed runtime, or local-worker
integration is claimed.

## ARCHITECTURAL AUTHORITY

1. `INVARIANTS.md`
2. `ARCHITECTURE.md`
3. `ROADMAP.md`
4. Tests/conformance fixtures for implemented invariants
5. Runtime implementation
6. Other documentation

If code conflicts with a MUST invariant, the code is defective unless the invariant is explicitly versioned and changed.

## CORE LAYER MODEL

```text
OpenAI supervisor
    -> governance wrapper
        -> deterministic orchestration
            -> execution runtime
                -> deterministic compact-evidence reduction

benchmark/performance observations remain outside correctness authority
```

Normative boundary:

```text
governance != orchestration != execution != benchmark

execution state != evidence transport
```

## IMPLEMENTATION SPLIT

```text
Python logic core
    governance configuration
    orchestration semantics
    obligation/DAG construction
    objective progress and strategy materiality
    continuation grant/deny decisions
    structural checkpoint/partial records
    AI-facing compact state
    future OpenAI integration
    future local-worker adapters

        | narrow versioned protocol
        v

Rust runtime
    exact state transitions
    integer budget accounting
    logical execution clock
    canonical identities
    cache/cycle machinery
    exact application of pre-granted leases
    receipts
    CPU reference execution
    future accelerator adapters

Rust compact evidence reducer
    exact checked aggregate counters
    governed authorization-manifest checks
    ordered admission/input/result/receipt identities
    continuous first/last runtime boundary
    opaque native source seals
    fixed-ceiling routine receipt
    bounded retained failure detail
    no retained per-case success trace
```

Python decides what should be attempted. Rust proves what was admitted and executed.

The Rust runtime must not directly call remote model providers.

The v0.3 runtime owns exact counters, cache/history, logical runtime ticks, command/state/transition identities, and execution receipts. Python receives copies of observations and snapshots and has no supported setter or cache-insertion surface. The retained Python v0.1 executor exists only as an independent conformance oracle.

The v0.4 governance wrapper interprets whether validated evidence satisfies the
declared policy; the Rust evidence reducer cannot grant governance acceptance.
Compact receipt identity, a self-consistent SHA-256 record, or a fast fold alone
is insufficient for accepted finalization. The optional fast fold is an
untrusted, non-cryptographic regression observation excluded from correctness
identity.

The v0.5 continuation layer does not move governance into Rust. Python
governance emits a canonical grant; Rust only validates and applies that exact
grant. A request, progress claim, benchmark observation, or runtime state can
never manufacture a grant. See `CONTINUATION_PROTOCOL.md` for exact decision,
accounting, checkpoint, and trust-scope semantics.

## MUST PRESERVE

- deterministic canonicalization;
- content-derived and domain-separated identity, never object identity;
- bounded execution resources;
- logical execution progression independent of normal wall-clock timeout semantics;
- cache validation before insertion and invalidation when declared dependencies change;
- mutation isolation for cached results;
- cycle detection independent of wall-clock time;
- layer/authority separation;
- proposal versus admitted-state separation;
- correctness identity separate from execution-plan and benchmark identity;
- large execution state separate from bounded routine evidence transport;
- exact streaming evidence aggregates and a declared evidence-sufficiency profile;
- exact bounded governed-action manifest coverage before sealed runtime evidence admission;
- first/last runtime receipt and state continuity within one session;
- objective progress separate from activity, confidence, and elapsed time;
- one finite precommitted continuation ceiling and no self-extension;
- supervisor request, governance grant/deny, and Rust exact-application separation;
- rejected lease application is state/tick/resource neutral;
- continuation checkpoints remain structural in-process lineage, not authentication;
- remote proprietary inference restricted to OpenAI;
- no generic remote proprietary-provider abstraction;
- local open-weight workers remain candidate-only subordinate workers;
- accelerator performance cannot become correctness authority by speed alone.

## AI-FACING DESIGN RULES

The supervisor should not be required to reconstruct deterministic runtime state from prose.

Agent-visible state should structurally expose, where relevant:

```text
task/obligation status
ready/blocking obligations
remaining budgets
logical execution state
cycle/progress state
capabilities
cached-observation provenance/validity
canonical rejection reason
legal recovery actions
canonical state identity
```

Keep these epistemic classes separate:

```text
observed
derived
model_proposed
unknown
```

Unknown is not false. A model proposal is not an observation and cannot satisfy an admitted action dependency or alter authoritative orchestration-state identity until separately admitted as observed or valid derived state. Capability arguments are semantic only when their top-level keys are admitted by the capability contract; wall-clock/latency observations belong in `observational_metadata`, which is excluded from correctness identity.

## FORBIDDEN WITHOUT EXPLICIT VERSIONED DESIGN CHANGE

- unseeded randomness in authority-bearing deterministic paths;
- Python `hash()` for persistent/canonical identity;
- `id()` or memory-address identity;
- wall-clock timestamps inside normal correctness identity;
- cache keys that omit declared dependency fingerprints;
- caller-visible mutable references to authoritative cached values;
- caching a value before it passes canonical validation;
- disabling finite budget checks;
- allowing any component to self-grant unbounded continuation;
- minting a native lease seal without the complete governance evaluator's
  exact decision capability;
- treating a lease request, strategy paraphrase, model confidence, or activity as progress authority;
- accepting a self-asserted external counter or caller-omitted live cycle;
- letting Rust enlarge, reorder, replay, or manufacture a governance grant;
- treating watchdog expiry as normal completion or independent proof of lease exhaustion;
- treating a structural checkpoint hash as producer authentication or cross-process runtime reconstruction;
- adding Anthropic, xAI, Google, or other proprietary remote model endpoints;
- creating a generic proprietary-provider abstraction;
- allowing a local worker to declare final task completion, alter governance policy, or extend its own budget;
- treating worker/chunk/device placement or benchmark timing as correctness evidence when semantics are unchanged;
- using a compact hash or non-cryptographic fold as producer authentication or as proof of external truth;
- returning an unbounded successful per-case trace through the normal evidence path;
- promoting IGM/GLUBALL donor geometry into IBAE semantics without a separately reviewed contract.

## DONOR-PATTERN BOUNDARY

IGM and GLUBALL may contribute execution ideas such as bounded chunking, exact addressing, worker-independent correctness identity, 30/32 GPU-shaped layout experiments, or exact logical sampling.

These are donor patterns only.

> Execution adjacency does not imply orchestration meaning.

## CHANGE PROCEDURE

Before modifying architecture or runtime behavior:

1. read `INVARIANTS.md`, `ARCHITECTURE.md`, and `ROADMAP.md`;
2. identify affected invariant IDs and their implementation status;
3. classify identity-bearing versus benchmark-only changes;
4. update/add deterministic tests or cross-language conformance fixtures for implemented behavior;
5. prove deterministic behavior for deterministic paths;
6. preserve layer and authority boundaries;
7. document any semantic contract change;
8. do not implement v0.6 or another later roadmap phase before the exact v0.5
   gate is accepted.
