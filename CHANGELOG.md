# Changelog

All notable changes to QSOL-IBAE will be documented here.

## Unreleased

### Added

- `IBAE-OBJECTIVE-PROGRESS-V1`, with exact versioned progress dimensions over
  canonical obligation state or task/governance-bound observed/derived
  counters. Classification and completion are derived from exact bound
  prior/current sources, and external counters require matching governed tool
  admission plus a source-bound native observation; activity, confidence, wall
  time, and strategy rephrasing remain non-authoritative. The built-in
  obligation contract counts both unsatisfied and blocked work, preventing a
  newly blocked obligation from being misclassified as progress, and context
  observation refreshes stalled/progressing/complete control state immediately.
  Governed external values also form receipt-independent semantic endpoints;
  each new prior endpoint must equal the live endpoint, preventing replay with
  freshly rotated evidence receipts.
- structured strategy-material and strategy-change receipts that bind admitted
  strategy identity, capability frontier, target obligations, dependency path,
  recovery mode, and period-1/2/3 cycle-breaking evidence. Receipts revalidate
  their exact material, while continuation admission derives live cycles from
  native history even when optional caller evidence is omitted.
- `IBAE-CONTINUATION-LEASE-V1`, with governance-precommitted initial budgets,
  finite indexed lease schedules, exact cumulative ceilings, request caps,
  strategy-recovery caps, one task/session continuation ledger, and closed
  grant/deny receipts. Initial history retains the complete six-transition
  period-1/2/3 window, and every request cap reserves a terminal decision beyond
  the lease schedule.
- opt-in Rust `apply_lease` authority that independently validates complete
  governance grant/receipt identities, policy/session/state lineage, schedule,
  replay index, and checked ceiling before changing exact limits. Accepted
  application consumes one runtime logical tick and no tool counters/history;
  rejection is state-neutral. Continuation-session creation pins the evaluator,
  context observer, and application committer in a Rust-private per-instance
  authority and returns a separate once-issued, session-scoped supervisor
  request capability. The principal
  label alone cannot authorize a request; the resulting exact request seal is
  the only path to native evaluation and grant-seal issuance. Rust independently validates the
  authorized request and complete grant, and a duplicate session with equal
  canonical IDs cannot use its distinct native authority against the original
  session. There is no raw exported grant issuer or mutable Python capability
  validator. Native integrity checks cover the captured callable code, every
  reachable mutable Python function dependency regardless of module, functions
  behind class/static method and property descriptors, referenced globals and
  default/closure bindings, and reachable IBAE helpers/classes at session
  creation and every evaluator/observer/committer entry. Native request entry
  requires the exact trusted type before callbacks and rechecks integrity after
  them. The complete initial zero-decision state receives a one-shot native
  session seal only after Rust derives its exact decision/progress aggregate
  seeds. Every reseal advances one live native generation and retires its
  predecessor.
  Context observation and application commit require the exact live native
  session snapshot and reseal the resulting full continuation state.
- single-use measurable-progress endpoints: one exact progress identity may
  justify at most one progress-based grant, after which another such grant
  requires freshly observed progress. External evidence is paired with
  dimensions in canonical key order. Native decision lineage now binds the
  last decision/denial, progress identity/classification/state, consumed
  endpoint, full ordered progress count/aggregate, grant ledger, and recovery
  accounting; legitimate context changes are resealed only through pinned
  native observer/committer paths. Compact evidence rejects a suffix even when
  it reaches the live endpoint. Compact
  recovery state no longer advertises material strategy change without a live
  prior strategy identity.
- structural in-process `IBAE-CONTINUATION-CHECKPOINT-V1`, fixed-shape
  continuation evidence capped at 4,096 bytes, semantic continuation partial
  receipts, and non-authoritative watchdog observations that cannot establish
  completion or lease exhaustion. Exact progress-contract and prior/current
  endpoints, live evidence/checkpoint endpoints, actual partial-denial causes,
  evaluator-bound recovery counters, exact live strategy/status/evidence
  bindings, effective request/schedule capacity, and watchdog
  orchestration/runtime/lease-exhaustion identity fail closed. Semantic partial
  reasons are validated against the actual denial and exhausted counters when
  the checkpoint itself is constructed.
- exact experimental `tiny`, `standard`, `extended`, and `repository`
  continuation profiles plus a model-free benchmark of fixed, front-loaded,
  geometric-candidate, and bounded-recovery schedules without a promoted
  winner or correctness claim. Exact unmet base demand is reported as a
  `base_budget_deficit` and cannot be clipped into a false completion.
- byte-stable v0.5 Python/Rust progress/continuation and budget-profile fixtures
  under multiple `PYTHONHASHSEED` values while preserving all frozen v0.2-v0.4
  fixture bytes.
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
- accepted v0.3 `IBAE-RUNTIME-PROTOCOL-V1` read/retry semantics with
  `execute_read` and `record_retry`; v0.5 adds only the opt-in exact
  `apply_lease` extension, while request/finalization/effect commands remain
  unimplemented.
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
