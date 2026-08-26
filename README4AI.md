# QSOL-IBAE — Machine Context

## PROJECT PURPOSE

QSOL-IBAE is an invariant-bounded execution kernel intended to sit beneath an OpenAI supervisory agent. Its purpose is to reduce redundant tool work while preserving deterministic, auditable execution semantics.

## CURRENT PHASE

v0.1 kernel only. No OpenAI SDK integration and no local-model integration yet.

## ARCHITECTURAL AUTHORITY

1. `INVARIANTS.md`
2. `ARCHITECTURE.md`
3. Tests
4. Runtime implementation
5. Documentation

If code conflicts with an invariant, the code is defective unless the invariant is explicitly versioned and changed.

## MUST PRESERVE

- deterministic canonicalization;
- content-derived identity, never object identity;
- bounded execution resources;
- cache invalidation when declared dependencies change;
- mutation isolation for cached results;
- cycle detection independent of wall-clock time;
- remote proprietary inference restricted to OpenAI;
- no generic remote proprietary-provider abstraction.

## FORBIDDEN WITHOUT EXPLICIT VERSIONED DESIGN CHANGE

- unseeded randomness;
- Python `hash()` for persistent/canonical identity;
- `id()` or memory address identity;
- cache keys that omit declared dependency fingerprints;
- caller-visible mutable references to cached values;
- disabling budget checks;
- adding Anthropic, xAI, Google, or other proprietary remote model endpoints;
- allowing a future local worker to declare task completion or extend its own budget.

## CHANGE PROCEDURE

Before modifying runtime behavior:

1. identify affected invariant IDs;
2. update or add tests;
3. prove deterministic behavior for deterministic paths;
4. update benchmark expectations if measured behavior changes;
5. document any semantic contract change.
