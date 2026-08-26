# AGENTS.md

Machine-facing repository rules.

1. Read `INVARIANTS.md`, `ARCHITECTURE.md`, and `ROADMAP.md` before changing architecture or runtime behavior.
2. The architecture-contract exit gate was accepted by merged PR #2. The current implementation boundary is the v0.2 deterministic Python orchestration reference. Do not begin v0.3 Rust authority work or any OpenAI/GPU/local-worker phase until the v0.2 conformance gate is accepted.
3. Identify every invariant affected by a change and preserve each invariant's status (`ENFORCED MUST`, `ARCHITECTURE MUST`, `ARCHITECTURE SHOULD`, `CANDIDATE`). Do not present an architecture-only invariant as implemented.
4. Preserve the authority separation `governance != orchestration != execution != benchmark`.
5. Lower layers must not promote themselves upward: runtime cannot rewrite orchestration/governance policy; workers cannot become supervisors; benchmark speed cannot become correctness evidence.
6. Preserve deterministic canonicalization and content-derived/domain-separated identity. Never use Python `hash()`, `id()`, memory address, or wall-clock timestamp for canonical correctness identity.
7. Add or update deterministic tests/conformance fixtures for every implemented invariant affected by a code change.
8. Never introduce a proprietary remote inference provider other than OpenAI. Do not create a generic proprietary-provider abstraction.
9. Future local open-weight models are candidate-only workers, not supervisors. They may not declare final task completion, alter provider policy, grant leases, or extend their own execution budget.
10. Cached observations must be validated before insertion, mutation-isolated, and invalidated when declared dependencies change. Reuse must preserve canonical cycle/history semantics.
11. Normal execution boundedness must not depend solely on elapsed wall-clock time. Wall-clock watchdogs are catastrophic-hang failsafes/benchmark observations, not normal completion authority.
12. Deterministic bookkeeping belongs in software, not model prose. Agent-facing state must structurally expose relevant budgets, obligation readiness, rejection reasons, and observed/derived/proposed/unknown distinctions.
13. Python is the planned logic/orchestration/OpenAI-facing layer; Rust is the planned exact authority-bearing runtime/accounting layer. Do not let Python mutate authoritative Rust state directly when that runtime exists.
14. The Rust runtime must not call remote model endpoints directly.
15. GPU/SIMD/geometry work is deferred until reference semantics and Rust conformance exist. A faster accelerator result is not a more correct result.
16. `C5 x K2 x C3`, CRT, GLUBALL sampling, and 30/32-lane layouts are optional donor patterns, not IBAE ontology. Execution adjacency does not imply orchestration meaning.
17. No optimization may alter observable/correctness semantics without a versioned contract change and updated conformance evidence.
18. Avoid new dependencies unless they materially strengthen the kernel or the narrow Python/Rust boundary.
19. External code contributions require a separate written contribution agreement.
20. Every implementation PR must list: affected invariant IDs, identity-bearing changes, benchmark-only changes, tests/conformance evidence, and any remaining architecture-only contracts.
