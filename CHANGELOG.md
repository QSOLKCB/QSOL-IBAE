# Changelog

All notable changes to QSOL-IBAE will be documented here.

## Unreleased

### Added

- v0.4 deterministic governance wrapper with a closed OpenAI-only provider
  authority, explicit supervisor/orchestrator/runtime/future-worker principals,
  and five fail-closed tool authority classes.
- versioned domain-separated task, governance, tool-admission, orchestration,
  execution, execution-plan, benchmark, final-acceptance, rejection, and partial
  identities/receipts with independent canonical reconstruction validators.
- exact bounded authorization manifests that bind typed v0.2 admitted
  decisions/proposals/capabilities and governed tool/cache permissions to
  matching sealed v0.3 admission/tool/argument/dependency records, with the
  current 64-action governed batch limit below the reducer's 256-entry hard
  ceiling.
- cold-execution provenance required per governed action before its cache hits
  can enter final evidence, preventing same-name capability-contract cache
  collisions without changing frozen v0.3 identities; sealed retries preserve
  known-admission accounting but cannot establish action coverage alone.
- fixed-shape execution receipts that bind exact streaming
  admission/input/result/runtime-receipt roots, authorization manifest/count,
  and strictly validated first/last v0.3 runtime receipts with continuous
  session/state boundaries rather than retaining an O(N) transition list.
- `IBAE-COMPACT-EVIDENCE-V1`, an opaque Rust streaming reducer with checked
  exact counters, one-million-case hard bound, no retained success trace, and a
  2,048-byte routine receipt ceiling independent of admitted case cardinality.
- non-constructible native runtime, aggregate-summary, and compact-receipt seals
  plus two-stage execution binding; parsed self-consistent receipts remain
  structural-only and the native seals do not claim authentication.
- bounded parent-bound failure expansion, deterministic child-before-parent
  validation, and a separate non-cryptographic regression fold excluded from
  correctness identity.
- strict adversarial validation of nested v0.3 runtime receipts without changing
  their emitted schema or the byte-stable v0.3 fixture.
- byte-stable v0.4 governance/evidence fixture and model-free 100,000-case
  compact-evidence stress summary under multiple `PYTHONHASHSEED` values.
- `IBAE-EVID-001` through `IBAE-EVID-007` evidence-plane invariants and explicit
  QEC/VE-24 pattern-level provenance with no donor implementation code or domain
  semantics imported.
- v0.3 Rust deterministic execution runtime with an opaque PyO3 session and maturin build path.
- `IBAE-RUNTIME-PROTOCOL-V1` with only `execute_read` and `record_retry` commands; future lease/finalization commands remain unimplemented.
- Rust-owned checked integer budgets, transition-derived logical ticks, bounded history/cache, dependency-sensitive reuse, cycle detection, and canonical runtime receipts.
- domain-separated runtime session, command, state, and receipt identities while preserving the v0.1 canonical tool/observation/transition identities.
- structured runtime rejection taxonomy with execution authority, relevant invariant IDs, and blocking state.
- Python/Rust canonicalization and v0.1 execution conformance tests plus a byte-stable v0.3 fixture and fresh-wheel CI gate.
- transaction-safe runtime output construction with a separately bounded receipt/snapshot envelope, exact-JSON observation forms, capability-contract rebinding, and command-bound unsupported-command rejections.
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
