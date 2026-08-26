# QSOL-IBAE — Machine Context

## PROJECT PURPOSE

QSOL-IBAE is an invariant-bounded execution substrate intended to sit beneath an OpenAI supervisory model. Its purpose is to reduce redundant tool work, make bounded continuation auditable, preserve deterministic execution semantics, and move deterministic bookkeeping out of the model's cognitive workload.

## CURRENT PHASE

Merged v0.1 deterministic kernel and architecture contract, the accepted **v0.2 deterministic Python orchestration reference**, and the **v0.3 Rust deterministic runtime implementation candidate**.

v0.2 implements canonical obligations/DAG readiness, proposal/admission separation, replay-safe-only batch deduplication, persistent bounded effect occurrence ownership, explicit independent-versus-declared batch ordering, explicit epistemic state classes with reuse-path- and unadmitted-proposal-neutral correctness identity, admitted typed strategy-specific parameter allowlists, capability-owned semantic argument allowlists with non-correctness observational metadata, bounded model-facing collections/text/integers and canonical payload traversal, canonical state/receipt identities, structured rejection/recovery records, and `IBAE-LOGICAL-CLOCK-V1` reference semantics.

PR #3 was merged after its exact reviewed head passed the v0.2 gate. The v0.3 candidate keeps orchestration semantics in Python and moves the implemented v0.1 read-execution mechanics into a private Rust session reached through PyO3/maturin and `IBAE-RUNTIME-PROTOCOL-V1`. The only admitted runtime commands are `execute_read` and `record_retry`; future lease/finalization commands are not implemented. No OpenAI SDK integration, GPU execution, continuation lease implementation, governance receipt layer, or local-worker integration is claimed.

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

benchmark/performance observations remain outside correctness authority
```

Normative boundary:

```text
governance != orchestration != execution != benchmark
```

## IMPLEMENTATION SPLIT

```text
Python logic core
    governance configuration
    orchestration semantics
    obligation/DAG construction
    AI-facing compact state
    OpenAI integration
    future local-worker adapters

        | narrow versioned protocol
        v

Rust runtime
    exact state transitions
    integer budget accounting
    logical execution clock
    canonical identities
    cache/cycle machinery
    receipts
    CPU reference execution
    future accelerator adapters
```

Python decides what should be attempted. Rust proves what was admitted and executed.

The Rust runtime must not directly call remote model providers.

The v0.3 runtime owns exact counters, cache/history, logical runtime ticks, command/state/transition identities, and execution receipts. Python receives copies of observations and snapshots and has no supported setter or cache-insertion surface. The retained Python v0.1 executor exists only as an independent conformance oracle.

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
- adding Anthropic, xAI, Google, or other proprietary remote model endpoints;
- creating a generic proprietary-provider abstraction;
- allowing a local worker to declare final task completion, alter governance policy, or extend its own budget;
- treating worker/chunk/device placement or benchmark timing as correctness evidence when semantics are unchanged;
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
8. do not implement a later roadmap phase before its prerequisite gate is satisfied.
