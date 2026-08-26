# Changelog

All notable changes to QSOL-IBAE will be documented here.

## Unreleased

### Added

- v0.3 Rust deterministic execution runtime with an opaque PyO3 session and maturin build path.
- `IBAE-RUNTIME-PROTOCOL-V1` with only `execute_read` and `record_retry` commands; future lease/finalization commands remain unimplemented.
- Rust-owned checked integer budgets, transition-derived logical ticks, bounded history/cache, dependency-sensitive reuse, cycle detection, and canonical runtime receipts.
- domain-separated runtime session, command, state, and receipt identities while preserving the v0.1 canonical tool/observation/transition identities.
- structured runtime rejection taxonomy with execution authority, relevant invariant IDs, and blocking state.
- Python/Rust canonicalization and v0.1 execution conformance tests plus a byte-stable v0.3 fixture and fresh-wheel CI gate.
- v0.2 deterministic Python orchestration reference.
- canonical obligation registry, dependency DAG, ready-set calculation, and stable obligation IDs.
- immutable bounded batch proposals, orchestrator-owned replay classification, safe replay-only deduplication, explicit effect sequencing, and persistent bounded occurrence ownership.
- explicit observed, derived, model-proposed, and unknown state records with provenance-aware dependency identity; proposed values cannot resolve admitted dependencies or alter authoritative state identity.
- reuse-path and proposal observational metadata remain visible but cannot alter epistemic, proposal, batch, action, or orchestration correctness identity.
- versioned logical clock, capability-owned semantic argument schema, admitted typed strategy schema, proposal, action, state, event, admission receipt, rejection, and recovery records.
- structured strategy-schema and capability-argument policy-drift rejections.
- bounded consumption at every model-facing collection boundary plus incrementally measured text/canonical-value bounds and finite identity integers.
- compact AI-facing state projection with actionable obligation/blocker context and a byte-stable v0.2 conformance fixture.
- v0.1 deterministic execution kernel.
- invariant registry and architecture contract.
- canonical state/tool identity.
- dependency-sensitive, mutation-isolated observation reuse.
- finite execution budgets and short-cycle detection.
- OpenAI-only remote proprietary-provider policy.
- source-available research license with reserved productization rights for QSOL-IMC and OpenAI Parties.
- unit tests, CI, and deterministic micro-benchmark.
