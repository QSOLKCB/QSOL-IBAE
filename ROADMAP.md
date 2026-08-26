# QSOL-IBAE Roadmap

Status: v0.2 deterministic Python orchestration reference implemented for review.

QSOL-IBAE is intentionally developed **invariant-first**. The architecture-contract exit gate was accepted by merged PR #2. Each later phase remains blocked on the preceding phase gate.

The project goal is not to create another generic agent framework. It is to create a small OpenAI-exclusive governed execution substrate that reduces redundant work, makes bounded continuation auditable, and moves deterministic bookkeeping out of the model's cognitive workload.

---

## Core architectural thesis

```text
                    USER
                      |
                      v
              OPENAI SUPERVISOR
                      |
                      v
+--------------------------------------------------+
|               GOVERNANCE WRAPPER                 |
| provider policy | authority | lease ceilings     |
| tool permissions | receipt admission | audit     |
|                                                  |
|  +--------------------------------------------+  |
|  |       DETERMINISTIC ORCHESTRATION          |  |
|  | obligations | DAG | canonical scheduling   |  |
|  | dedup | progress | leases | work admission |  |
|  |                                            |  |
|  |  +--------------------------------------+  |  |
|  |  |          EXECUTION RUNTIME           |  |  |
|  |  | canonical state | cache | budgets    |  |  |
|  |  | logical clock | cycles | receipts    |  |  |
|  |  | CPU reference | future accelerators |  |  |
|  |  +--------------------------------------+  |  |
|  +--------------------------------------------+  |
+--------------------------------------------------+
                      |
                      v
                 FINAL RECEIPT
```

The intended implementation split is:

```text
Python logic core
    governance policy
    orchestration semantics
    obligation/DAG construction
    OpenAI integration
    AI-facing state projection
    future local-worker adapters

        | versioned narrow protocol
        v

Rust runtime
    exact state transitions
    integer budget accounting
    canonical identity
    observation cache
    cycle detection
    logical execution clock
    receipts
    deterministic CPU execution
    future accelerator adapters
```

**Python decides what should be attempted. Rust proves what was admitted and executed.**

Rust MUST NOT directly own remote model-provider integration. OpenAI integration remains above the runtime boundary so model/API changes cannot destabilize the deterministic execution substrate.

---

# Completed foundation

## v0.1 — Deterministic Execution Kernel

Merged in PR #1.

- [x] Canonical JSON serialization.
- [x] SHA-256 content fingerprints.
- [x] Canonical read-tool identity.
- [x] Reject non-string JSON mapping keys before canonical hashing.
- [x] Dependency-sensitive observation cache.
- [x] Cache mutation isolation.
- [x] Reject invalid/non-canonical observations before cache insertion.
- [x] Finite request/execution/retry/history budgets.
- [x] Deterministic period-1/2/3 cycle detection.
- [x] Cache-hit/cold-execution transition equivalence for cycle history.
- [x] OpenAI-only remote-provider policy.
- [x] Unit tests and review-hardening regressions.
- [x] Deterministic micro-benchmark.
- [x] CI and byte-repeat determinism workflow.
- [ ] Establish benchmark corpus beyond micro-fixtures.
- [x] Freeze v0.1 behavioral semantics after architecture review.

The current Python kernel is a reference prototype. Future Rust implementation must preserve its admitted semantics unless a versioned contract explicitly changes them.

---

# Architecture contract gate — BEFORE the next implementation PR

Accepted by merged PR #2 after review findings were addressed. Unchecked items within A0-A9 remain later executable or benchmark obligations; they do not represent current implementation claims or reopen the accepted contract exit gate.

## A0 — Layer and authority freeze

- [x] Freeze the three-layer model: governance, orchestration, execution.
- [x] Require `governance != orchestration != execution != benchmark`.
- [x] Forbid upward authority promotion by lower layers.
- [x] Define the OpenAI supervisor as the only model-level completion authority.
- [x] Define future local open-weight workers as candidate-only subordinate workers.
- [x] Keep proprietary remote inference structurally OpenAI-only.
- [x] Define fail-closed behavior for unknown policy, unknown authority, malformed receipts, and unsupported provider state.

### Gate

No implementation may allow a runtime, worker, benchmark result, or orchestration strategy to modify governance authority.

## A1 — Identity taxonomy freeze

Define separate canonical identities for:

- [x] **Task identity** — what is being attempted.
- [x] **Governance identity** — policy/version/authority under which execution is admitted.
- [x] **Orchestration identity** — obligation graph and admitted orchestration decisions.
- [x] **Execution identity** — canonical admitted actions/observations/transitions.
- [x] **Execution-plan identity** — worker/chunk/device/scheduling arrangement where relevant.
- [x] **Benchmark receipt** — elapsed time, throughput, token/tool counts, device observations, and other non-correctness performance data.

Correctness identity MUST remain independent of elapsed wall-clock time. Where semantics are unchanged, correctness identity SHOULD remain independent of worker count, chunking, locality, and device assignment.

### Gate

No benchmark observation may silently become correctness evidence.

## A2 — Deterministic logical execution clock

- [x] Define `IBAE-LOGICAL-CLOCK-V1`.
- [x] Increment the logical clock from canonical admitted transitions, not elapsed seconds.
- [ ] Define which events consume request quanta, execution quanta, retry quanta, mutation quanta, and lease quanta.
- [x] Ensure cache hits still advance canonical request/transition history while consuming zero actual-execution quanta.
- [x] Keep wall-clock timing as an observational benchmark field only.
- [x] Retain a separate absolute wall-clock watchdog solely as a catastrophic-hang failsafe.
- [ ] Prove watchdog expiry cannot be mistaken for normal task-completion semantics.

### Gate

Normal boundedness must be enforceable without consulting elapsed wall-clock time.

## A3 — Execution budget vector

Define a bounded resource vector rather than one scalar timeout:

```text
requests
actual_executions
retries
mutations
retained_history
continuation_leases
optional model_turn observations
```

- [x] Every authority-bearing budget field uses exact integer accounting.
- [x] No model, local worker, tool backend, or accelerator may extend its own budget.
- [ ] Establish initial named deterministic task profiles for experiments (`tiny`, `standard`, `extended`, `repository`) without claiming the initial numeric values are optimal.
- [x] Treat profile tuning as benchmark-driven research.
- [x] Keep task-profile selection/version inside governance/orchestration identity.

## A4 — Progress and obligation semantics

- [x] Define an explicit obligation record and obligation DAG.
- [x] Distinguish **progress** from mere **activity**.
- [x] Define objective progress signals such as satisfied obligations, reduced failing tests, reduced unresolved review threads, or reduced unsatisfied acceptance gates.
- [x] Do not use model self-reported confidence/completion percentage as sole progress authority.
- [x] Define canonical strategy identity.
- [ ] Define stalled-progress and changed-strategy states.
- [x] Define completion preconditions separately from model statements.

### Gate

The runtime/orchestrator must never grant additional work merely because the model says it is making progress.

## A5 — Bounded continuation leases

- [ ] Define `IBAE-CONTINUATION-LEASE-V1`.
- [ ] A supervisor may request another lease; it may not grant one to itself.
- [ ] Governance/orchestration decides lease admission deterministically from canonical state.
- [ ] Require task incompleteness, no blocking invariant violation, available lease count, and either measurable progress or an explicitly admitted non-cyclic strategy change.
- [ ] Deny extension on detected execution cycles unless governance explicitly classifies a safe recovery transition.
- [ ] Evaluate geometrically decreasing lease sizes as the default bounded schedule, e.g. `B`, `B/2`, `B/4`, without freezing numeric values before benchmarks.
- [ ] Persist deterministic continuation checkpoints.
- [ ] Permit deterministic partial-finalization when no further lease is available.

### Gate

The sum of all possible leases must remain finitely bounded by policy before execution begins.

## A6 — Python/Rust boundary freeze

- [x] Keep Python as the logic/orchestration layer.
- [x] Establish Rust as the exact runtime/accounting/reference execution layer.
- [x] Use PyO3 + maturin as the initial in-process bridge unless conformance work proves a smaller interface is preferable.
- [x] Do not introduce RPC, daemon, socket, or distributed infrastructure during the initial runtime port.
- [x] Define a tiny versioned command/receipt protocol rather than exposing many Rust internals to Python.
- [ ] Candidate command set: `ADMIT`, `EXECUTE`, `RECORD_OBSERVATION`, `RECORD_RETRY`, `REQUEST_LEASE`, `FINALIZE`.
- [x] Require Python/Rust conformance fixtures for every authority-bearing state transition.
- [x] Prevent direct Python mutation of Rust-owned authoritative runtime state.
- [x] Keep arbitrary Python objects out of correctness identity; cross the boundary through declared canonical records.

### Gate

The runtime API must remain small enough that the complete authority surface can be audited and eventually formalized.

## A7 — AI-facing protocol freeze

Define `IBAE-AGENT-PROTOCOL-V1` around a small set of conceptual messages:

```text
STATE
PROPOSAL
ADMISSION
RESULT
LEASE
FINALIZATION
```

The agent-facing surface SHOULD expose only the smallest sufficient canonical projection of runtime state.

- [x] AI need not reconstruct deterministic bookkeeping from prose.
- [x] Expose remaining budgets directly rather than requiring arithmetic by the model.
- [x] Expose obligation readiness/blocking directly.
- [x] Every rejection has a canonical reason code.
- [x] When safe recovery moves exist, return legal next actions.
- [x] Separate `observed`, `derived`, `model_proposed`, and `unknown` state classes.
- [x] Represent missing/unqueried state as `unknown`, not false.
- [x] Expose provenance and validity conditions on reused observations.
- [x] Provide a deterministic compact state digest instead of replaying the entire execution transcript every turn.
- [x] Expose tool/capability availability at session scope so the supervisor need not rediscover unavailable capabilities repeatedly.
- [x] Support batch proposals so independent work can be deduplicated, admitted, cached, and parallelized below the model round-trip boundary.

### Gate

No deterministic runtime fact required for safe next-action selection should exist only in natural-language transcript state.

## A8 — Receipt and rejection model

- [ ] Define versioned task/governance/orchestration/execution/final receipts.
- [ ] Domain-separate all canonical hashes.
- [ ] Preserve rejected or partial executions with stage/reason receipts rather than silently discarding them.
- [ ] Bind final accepted state to the identities that actually determined correctness.
- [ ] Keep benchmark/performance records separately labelled non-correctness observations.
- [ ] Keep privacy-safe environment metadata and avoid raw machine identifiers unless explicitly required by a test protocol.

## A9 — Donor-runtime boundaries from IGM / GLUBALL

The following ideas are donor patterns, not inherited ontology.

From IGM:

- deterministic worker/chunk-independent correctness identity;
- separate benchmark timing from correctness identity;
- bounded memory/chunk planning;
- exact execution addresses;
- CPU/reference authority before accelerator authority;
- 30 meaningful addresses in a 32-wide accelerator-friendly layout as an **experiment**, not a required IBAE semantic structure.

From GLUBALL:

- exact logical sampling/partition rules;
- large logical spaces without allocation proportional to logical cardinality;
- canonical receipts and worker-range determinism.

Required non-promotion rule:

> **Execution adjacency does not imply orchestration meaning.**

- [x] Any `C5 x K2 x C3`, CRT, 30/32 lane, toroidal, sampling, or other geometry must remain an execution/scheduling representation unless a separately reviewed IBAE contract gives it semantics.
- [x] Do not make two IGM padding lanes semantic metadata lanes by default.
- [ ] Benchmark `30 work + 2 inactive padding + metadata sidecar` against alternatives such as `32 work + metadata sidecar` before freezing a GPU layout.

### Architecture-contract exit gate

Before the next implementation PR:

- [x] `ARCHITECTURE.md`, `INVARIANTS.md`, and this roadmap agree on layer authority.
- [x] Every planned MUST invariant has an ID and implementation phase.
- [x] Identity-bearing versus observational fields are explicitly classified.
- [x] Python/Rust authority boundary is explicit.
- [x] AI-facing protocol has explicit state classes and rejection semantics.
- [x] GPU geometry remains optional/deferred and cannot define correctness.

---

# Planned implementation phases

## v0.2 — Deterministic Python Orchestration Reference

Goal: prove orchestration semantics before moving authority into Rust.

- [x] Obligation registry and canonical obligation IDs.
- [x] Dependency DAG with deterministic ready-set calculation.
- [x] Canonical ordering/admission of equally ready actions.
- [x] Model proposal versus deterministic admission separation.
- [x] Canonical strategy identity.
- [x] Duplicate-action elimination by canonical identity, restricted to orchestrator-classified replay-safe actions.
- [x] Safe batch proposal representation with occurrence identity for effectful actions.
- [x] Explicit observed/derived/proposed/unknown state separation.
- [x] Canonical state digest.
- [x] Canonical rejection reason codes, relevant invariant/authority fields, and legal recovery moves.
- [x] Logical-clock reference semantics.
- [x] Deterministic orchestration fixtures with no model dependency.

### v0.2 gate

Identical canonical task state + identical proposal set with the same explicit ordering contract + identical policy must yield identical admitted orchestration decisions. Canonically independent read batches are order-normalized; effectful batches preserve their identity-bearing declared sequence.

Gate evidence: unit/regression coverage plus `fixtures/v0.2/orchestration-reference.json`, regenerated under multiple `PYTHONHASHSEED` values and byte-compared in CI. v0.3 remains blocked until this PR is reviewed and the v0.2 gate is accepted.

## v0.3 — Rust Deterministic Runtime

Goal: move exact authority-bearing execution machinery below Python.

- [ ] Rust crate for runtime state, budgets, canonical identities, cache, cycle detection, logical clock, and receipts.
- [ ] Exact integer control-plane fields.
- [ ] PyO3/maturin bridge.
- [ ] Versioned narrow command/receipt protocol.
- [ ] Rust-owned authoritative runtime state.
- [ ] Python reference versus Rust implementation conformance suite.
- [ ] Reproduce v0.1 safe-reuse and budget behavior.
- [ ] Byte-stable fixture receipts where platform contract permits.
- [ ] No OpenAI/network calls from the Rust runtime.

### v0.3 gate

No accepted Rust transition may disagree with the admitted reference semantics without a versioned contract change.

## v0.4 — Governance Wrapper and Identity Receipts

- [ ] Governance wrapper outside deterministic orchestration/runtime.
- [ ] OpenAI-only remote-provider policy at governance authority.
- [ ] Supervisor/worker/tool authority classes.
- [ ] Tool-class permissions: pure read, snapshot read, volatile read, idempotent mutation, non-idempotent mutation.
- [ ] Mutation admission rules.
- [ ] Task/governance/orchestration/execution/execution-plan identity separation.
- [ ] Final acceptance receipt.
- [ ] Rejected/partial execution receipts.
- [ ] Fail-closed malformed/unknown policy behavior.

## v0.5 — Progress and Bounded Continuation

- [ ] Objective progress predicates.
- [ ] Strategy-change admission.
- [ ] Continuation lease request/grant/deny protocol.
- [ ] Finite total lease ceiling.
- [ ] Deterministic checkpoint/resume receipt.
- [ ] Cycle-aware extension denial.
- [ ] Partial-finalization path.
- [ ] Benchmark several initial/extension budget profiles rather than hard-coding one guessed timeout.

## v0.6 — OpenAI Supervisor Integration

- [ ] Python OpenAI adapter above the governance/orchestration boundary.
- [ ] Evaluate Responses API direct-loop integration versus Agents SDK adapter while preserving the same IBAE contracts.
- [ ] OpenAI supervisor proposes actions; deterministic orchestrator admits them.
- [ ] Supervisor-only task-completion declaration.
- [ ] Trace OpenAI model turns separately from requested/executed tool operations.
- [ ] Batch proposal/admission path.
- [ ] Compact canonical state digest returned to the supervisor.
- [ ] Reused-observation provenance visible to the supervisor.
- [ ] No generic proprietary-provider abstraction.

## v0.7 — Baseline Agent Efficiency Corpus

Before GPU work, prove whether the architecture actually helps.

Compare equivalent OpenAI-supervised tasks with and without IBAE where possible.

Measure:

- [ ] task success rate;
- [ ] OpenAI model turns;
- [ ] requested tool calls;
- [ ] actual tool executions;
- [ ] cache hits;
- [ ] duplicate proposals eliminated;
- [ ] invalid/rejected proposals;
- [ ] recovery success after rejection;
- [ ] cycle incidence;
- [ ] leases granted/denied;
- [ ] tokens consumed;
- [ ] elapsed wall-clock time as observation only;
- [ ] semantic divergence, which must be zero for accepted deterministic cases.

## v0.8 — Accelerator / GPU Research Profile

GPU execution is an optimization profile, never correctness authority by speed alone.

Reference order:

```text
Python semantics reference
        -> Rust CPU authority
        -> accelerator candidate
        -> conformance/residual gate
```

- [ ] Begin on local NVIDIA RTX 5060 Ti.
- [ ] Define explicit accelerator numerical/execution profile.
- [ ] Keep governance-critical counters/addresses/flags integer/exact.
- [ ] Permit `f32` only for explicitly non-authoritative heuristic/numeric accelerator fields.
- [ ] Compare 30-of-32 padded execution cells against simpler full-32 layouts.
- [ ] Keep metadata in a sidecar unless benchmarks and review justify another representation.
- [ ] Measure warp divergence, memory locality, AoSoA/SoA behavior, and batched transition throughput.
- [ ] Prove accelerator results against Rust CPU reference.
- [ ] Only after local conformance, use Vast.ai for cross-device reproducibility across NVIDIA architectures/toolchains.
- [ ] Device/worker/chunk differences remain execution-plan/benchmark information unless semantics actually change.

### v0.8 gate

A faster GPU result is not a more correct result. No GPU profile becomes authoritative without reference conformance.

## v0.9 — Local Open-Weight Worker Protocol

- [ ] Local workers receive bounded task packets, not the full governance surface.
- [ ] Candidate-only outputs.
- [ ] No supervisory authority.
- [ ] No task-completion authority.
- [ ] No proprietary-provider selection authority.
- [ ] No budget-extension authority.
- [ ] Minimum necessary context/permissions.
- [ ] Structured result/evidence/confidence packet.
- [ ] OpenAI supervisor verifies or rejects worker candidates.
- [ ] Initial adapters may target local runtimes such as llama.cpp/Ollama/vLLM, but remote proprietary inference remains OpenAI-only.

## v1.0 — Benchmark-Backed Stable Runtime

- [ ] Stable versioned Python/Rust protocol.
- [ ] Stable governance/orchestration/runtime authority separation.
- [ ] Reproducible benchmark corpus.
- [ ] Cross-language conformance suite.
- [ ] No semantic divergence in accepted deterministic cases.
- [ ] Documented efficiency/failure-mode report.
- [ ] Formal review of the core invariant set.
- [ ] Release candidate frozen to an exact commit before any formalization target is selected.

---

# Deferred / optional research

These ideas may be valuable but are explicitly **not prerequisites** for the core runtime:

- `C5 x K2 x C3` orchestration/execution address geometry;
- CRT traversal/addressing;
- 30-meaningful/32-wide GPU mapping;
- GLUBALL-style exact sampling over very large logical candidate-action spaces;
- GPU-side candidate scoring;
- alternate deterministic scheduling strategies;
- persistent/distributed caches;
- multi-process or distributed execution;
- formal Lean specification of frozen stable contracts.

Every optional optimization must earn admission by preserving the core invariants and demonstrating measurable benefit.

---

# Permanent non-goals

- General proprietary multi-provider orchestration.
- Allowing local workers to become supervisory peers.
- Treating elapsed time as correctness identity.
- Treating benchmark speed as authority.
- Allowing an executor/worker to self-extend execution indefinitely.
- Requiring the OpenAI supervisor to perform deterministic bookkeeping that the runtime can compute exactly.
- Importing donor-repository geometry or ontology without an explicit IBAE-specific contract and benchmark justification.
