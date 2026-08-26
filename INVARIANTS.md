# QSOL-IBAE Invariant Registry

Version: v0.1 kernel

Violation of a MUST invariant is a system defect.

## IBAE-DET-001 — Canonical state determinism

For any supported value `x`, repeated canonical serialization of `x` produces identical UTF-8 bytes.

Enforcement: `ibae.canonical.canonical_json` uses sorted keys, fixed separators, UTF-8-safe text, and rejects NaN/Infinity.

## IBAE-DET-002 — Canonical tool identity

A read-tool request identity is derived only from its tool name, canonical arguments, and declared dependency fingerprint.

No Python `hash()`, `id()`, memory address, timestamp, or implicit process state may participate.

## IBAE-BND-001 — Finite request budget

Every executor has a finite maximum number of requested tool operations.

## IBAE-BND-002 — Finite execution budget

Every executor has a finite maximum number of actual tool executions, independent of cache hits.

## IBAE-BND-003 — Finite retry budget

Retry accounting is bounded by an explicit finite limit.

## IBAE-BND-004 — Bounded retained history

Canonical transition history is truncated to a configured finite maximum length.

## IBAE-REUSE-001 — Safe immutable observation reuse

A cached read observation may be reused only when the canonical tool identity, canonical arguments, and declared dependency fingerprint are unchanged.

## IBAE-REUSE-002 — Dependency-sensitive invalidation

If a declared dependency fingerprint changes, the prior cached observation must not satisfy the new request.

## IBAE-REUSE-003 — Cache mutation isolation

Caller mutation of a returned observation must not mutate the stored cached observation.

Enforcement: deep copy on cache store and retrieval.

## IBAE-CYC-001 — Canonical short-cycle detection

Repeated canonical state patterns with period 1, 2, or 3 are detectable without wall-clock input.

## IBAE-CYC-002 — No unbounded identical transition

The execution kernel must never rely solely on elapsed time to prevent repeated equivalent transitions. Request/execution bounds remain authoritative.

## IBAE-PROG-001 — Progress semantics are explicit

Future continuation leases must depend on an explicit progress predicate or a changed strategy. v0.1 defines the invariant but does not yet grant continuation leases.

## IBAE-PROV-001 — OpenAI-only remote proprietary inference

Any remote proprietary model provider admitted by the runtime must canonicalize to `openai`. Other proprietary remote providers are out of scope and rejected.

## IBAE-AUTH-001 — Supervisor completion authority

When model orchestration is introduced, only the OpenAI supervisor may declare overall task completion. Local workers may return candidate results only.

## Verification rule

Each implemented invariant must be enforced by at least one of:

- pure construction that makes violation unrepresentable;
- runtime assertion/exception;
- deterministic regression test;
- structural architecture rule.
