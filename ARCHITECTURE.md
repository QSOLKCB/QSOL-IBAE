# Architecture

## Design goal

QSOL-IBAE is a small invariant layer, not a general-purpose multi-provider agent framework.

The v0.1 kernel separates four concerns:

1. **Canonicalization** — deterministic identities for values and tool requests.
2. **Observation reuse** — content-addressed reuse with dependency-sensitive invalidation.
3. **Execution bounds** — explicit finite budgets independent of wall-clock timing.
4. **Policy** — structural rejection of non-OpenAI proprietary remote inference.

## State transition model

Conceptually:

```text
S_t + A_t -> invariant gate -> cached or executed observation O_t -> S_(t+1)
```

`S_t` is represented by immutable execution counters and bounded canonical history. Runtime services may maintain internal mutable containers, but they may not expose mutable cache state to callers.

## Why dependency fingerprints are explicit

A read call such as `read_file(path)` is not safe to reuse merely because the path is unchanged. The underlying repository revision may have changed.

Therefore reuse identity includes a caller-supplied dependency fingerprint, for example a commit SHA, working-tree hash, immutable object version, or other canonical state identifier.

## Why no generic provider interface

Remote proprietary inference is intentionally asymmetric:

```text
remote supervisor = OpenAI
local computation = future worker
```

A generic `ModelProvider` abstraction would weaken that structural constraint and make unsupported proprietary endpoints trivial to add. QSOL-IBAE therefore models the allowed remote provider as policy, not as a pluggable vendor interface.

## Future layers

Only after v0.1 invariants are benchmarked:

- explicit progress metrics;
- bounded continuation leases;
- dependency DAG scheduling;
- OpenAI Agents SDK integration;
- local open-weight worker protocol;
- OpenAI supervisor verification of worker candidates.
