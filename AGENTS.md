# AGENTS.md

Machine-facing repository rules.

1. Read `INVARIANTS.md`, `ARCHITECTURE.md`, and `ROADMAP.md` before changing architecture or runtime behavior.
2. The architecture-contract gate and the v0.1-v0.3 implementation gates are accepted. PR #4 merged the exact reviewed v0.3 Rust-runtime head at merge commit `de5239b8c7980f8211da109b42bdbc3449be83ba`. The current implementation boundary is v0.4 governance and compact evidence. Do not begin v0.5 leases, OpenAI integration, GPU work, distributed/local-worker work, or another later phase until the v0.4 gate is accepted.
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
13. Python is the logic/orchestration/future-OpenAI-facing layer; Rust is the exact authority-bearing runtime/accounting layer. Do not let Python mutate authoritative Rust state directly.
14. The Rust runtime must not call remote model endpoints directly.
15. GPU/SIMD/geometry work is deferred until reference semantics and Rust conformance exist. A faster accelerator result is not a more correct result.
16. `C5 x K2 x C3`, CRT, GLUBALL sampling, and 30/32-lane layouts are optional donor patterns, not IBAE ontology. Execution adjacency does not imply orchestration meaning.
17. No optimization may alter observable/correctness semantics without a versioned contract change and updated conformance evidence.
18. Avoid new dependencies unless they materially strengthen the kernel or the narrow Python/Rust boundary.
19. External code contributions require a separate written contribution agreement.
20. Every implementation PR must list: affected invariant IDs, identity-bearing changes, benchmark-only changes, tests/conformance evidence, and any remaining architecture-only contracts.
21. Preserve `execution state != evidence transport`. Routine successful evidence must remain fixed-shape or explicitly bounded independently of admitted workload cardinality for its declared profile.
22. A fast fold/checksum is non-cryptographic regression evidence only. It cannot replace a canonical domain-separated SHA-256 receipt or establish governance acceptance.
23. Detailed evidence expansion is exceptional, explicitly requested, parent-bound, and bounded. Do not make successful per-case traces the normal model/host-visible path.
24. A canonically self-consistent receipt proves record integrity, not producer authenticity or external truth. Accepted finalization requires the declared source-bound receipt chain in addition to structural validation.
25. Hierarchical evidence may change evidence-transport identity, but it must preserve its separately bound execution correctness identity. Do not claim arbitrary chunk-plan-neutral evidence roots until a versioned composition proof enforces that property.
26. A v0.4 finalizable runtime receipt must match the exact bounded governed authorization manifest (typed v0.2 admission, tool, arguments, dependency, command class, governed receipt, and cache policy) before evidence-state mutation. Governed orchestration currently admits at most 64 actions per batch; the reducer independently enforces a 256-authorization hard ceiling. Each action needs cold provenance before its hits are admitted; a retry cannot establish coverage. Tool classification alone is not an execution authorization bypass.
27. Serialized SHA-256 consistency cannot substitute for the non-constructible native runtime/summary/receipt seals required by the in-process v0.4 finalization path. Those seals are not producer authentication or remote attestation.
28. The accepted runtime command surface remains read-only in v0.4. Governance may classify volatile reads and mutations, but must not fabricate effect execution through `execute_read`.
