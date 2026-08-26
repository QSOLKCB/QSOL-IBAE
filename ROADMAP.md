# Roadmap

## v0.1 — Deterministic Execution Kernel

- [x] Canonical JSON serialization.
- [x] SHA-256 content fingerprints.
- [x] Canonical read-tool identity.
- [x] Dependency-sensitive observation cache.
- [x] Cache mutation isolation.
- [x] Finite request/execution/retry/history budgets.
- [x] Deterministic period-1/2/3 cycle detection.
- [x] OpenAI-only remote provider policy.
- [x] Unit tests.
- [x] Deterministic micro-benchmark.
- [x] CI and byte-repeat determinism workflow.
- [ ] Establish benchmark corpus beyond micro-fixtures.
- [ ] Freeze v0.1 semantics after external review.

## v0.2 — Progress Semantics

- [ ] Define measurable progress records.
- [ ] Distinguish progress from activity.
- [ ] Add strategy identity.
- [ ] Require progress or strategy change before continuation.

## v0.3 — Bounded Continuation Leases

- [ ] Explicit finite lease extension.
- [ ] Extension denial on cycles/non-progress.
- [ ] Deterministic continuation checkpoint schema.

## v0.4 — Execution DAG

- [ ] Dependency graph for independent observations.
- [ ] Safe batching/parallel-read eligibility.
- [ ] Selective cache invalidation by dependency.

## v0.5 — OpenAI Supervisor Integration

- [ ] OpenAI Agents SDK adapter.
- [ ] Supervisor-only completion authority.
- [ ] Trace OpenAI model turns separately from tool executions.

## v0.6 — Local Worker Protocol

- [ ] Local open-weight worker request/result schema.
- [ ] No supervisory authority.
- [ ] No provider-selection authority.
- [ ] No budget-extension authority.
- [ ] OpenAI verification of candidate outputs.

## v1.0 — Benchmark-backed Stable Runtime

- [ ] Reproducible baseline vs invariant-aware benchmark corpus.
- [ ] No semantic divergence in accepted deterministic cases.
- [ ] Published efficiency and failure-mode report.
