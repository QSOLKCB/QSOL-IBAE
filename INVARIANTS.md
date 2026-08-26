# QSOL-IBAE Invariant Registry

Status: architecture-contract draft after merged v0.1 kernel.

Violation of an **ENFORCED MUST** invariant is a system defect in the current implementation.
Violation of an **ARCHITECTURE MUST** invariant is a design defect in any future implementation.
A **CANDIDATE** invariant or geometry is experimental and does not become authoritative until separately admitted.

Status labels used below:

- **ENFORCED MUST** — implemented and regression-tested now.
- **ARCHITECTURE MUST** — mandatory design contract for future phases; not necessarily implemented yet.
- **ARCHITECTURE SHOULD** — preferred design rule that may be revised only with explicit rationale and tests.
- **CANDIDATE** — research direction only.

---

# 0. Meta-invariant

## IBAE-META-001 — Invariant-first development

**ARCHITECTURE MUST**

Authority-bearing behavior must be specified as a versioned invariant/contract before optimization or accelerator work is allowed to depend on it.

A performance improvement cannot silently redefine correctness.

---

# 1. Layering and authority

## IBAE-LAY-001 — Layer separation

**ARCHITECTURE MUST**

```text
governance != orchestration != execution != benchmark
```

These are separate authority domains and must have separately inspectable state/receipts.

## IBAE-LAY-002 — No upward authority promotion

**ARCHITECTURE MUST**

A lower layer may not change the policy or authority of a higher layer.

In particular:

- execution runtime cannot rewrite orchestration policy;
- orchestration cannot rewrite governance policy;
- local workers cannot promote themselves to supervisor;
- benchmark observations cannot promote themselves into correctness evidence.

## IBAE-LAY-003 — Proposal is not admission

**ARCHITECTURE MUST**

A model-proposed action, plan, obligation, strategy, or completion claim is not authoritative runtime state until admitted through the governing contract.

## IBAE-LAY-004 — Execution adjacency is not orchestration meaning

**ARCHITECTURE MUST**

Memory adjacency, GPU-lane adjacency, CRT/toroidal neighbours, chunk membership, worker assignment, scheduling graph edges, and device placement are implementation structures only unless a separately versioned IBAE semantic contract says otherwise.

---

# 2. Determinism and canonical identity

## IBAE-DET-001 — Canonical state determinism

**ENFORCED MUST**

For any supported value `x`, repeated canonical serialization of `x` produces identical UTF-8 bytes.

Current enforcement: sorted-key canonical JSON, fixed separators, UTF-8-safe text, rejection of NaN/Infinity, and rejection of non-string mapping keys.

## IBAE-DET-002 — Canonical tool identity

**ENFORCED MUST**

A read-tool request identity is derived only from its tool name, canonical arguments, and declared dependency fingerprint.

Python `hash()`, `id()`, memory address, wall-clock timestamp, and implicit process state must not participate.

## IBAE-DET-003 — Deterministic admitted transition

**ARCHITECTURE MUST**

Within a declared deterministic profile, identical admitted prior state + identical canonical command + identical dependency state must produce the same canonical transition result/receipt.

## IBAE-DET-004 — Deterministic orchestration ordering

**ARCHITECTURE MUST**

When multiple actions are equally ready under the same policy and dependency state, the deterministic orchestrator must use a canonical ordering/admission rule rather than process/hash iteration accidents.

## IBAE-DET-005 — Domain-separated identities

**ARCHITECTURE MUST**

Task, governance, orchestration, execution, execution-plan, observation, and receipt hashes must be domain-separated so equal raw payloads from different identity classes cannot alias semantically.

---

# 3. Logical execution clock and time

## IBAE-CLK-001 — Logical clock is transition-derived

**ARCHITECTURE MUST**

Primary execution progression is counted from canonical admitted transitions, not elapsed seconds.

## IBAE-CLK-002 — Wall clock is non-correctness observation

**ARCHITECTURE MUST**

Elapsed time, throughput, queue delay, and tool latency are benchmark/environment observations and cannot enter correctness identity unless a separately reviewed protocol explicitly makes timing itself the subject of the task.

## IBAE-CLK-003 — Wall-clock watchdog is failsafe only

**ARCHITECTURE MUST**

An absolute time watchdog may exist to terminate catastrophic hangs or infrastructure failure, but normal task boundedness and completion semantics must not depend solely on that watchdog.

## IBAE-CLK-004 — Cache hits still advance canonical activity

**ARCHITECTURE MUST**

A cache hit may consume zero actual-execution quanta, but it remains a canonical request/transition event for request bounds, history, and loop detection.

---

# 4. Bounded execution

## IBAE-BND-001 — Finite request budget

**ENFORCED MUST**

Every executor has a finite maximum number of requested tool operations.

## IBAE-BND-002 — Finite actual-execution budget

**ENFORCED MUST**

Every executor has a finite maximum number of actual tool executions, independent of cache hits.

## IBAE-BND-003 — Finite retry budget

**ENFORCED MUST**

Retry accounting is bounded by an explicit finite limit.

## IBAE-BND-004 — Bounded retained history

**ENFORCED MUST**

Canonical transition history is truncated to a configured finite maximum length.

## IBAE-BND-005 — Finite continuation leases

**ARCHITECTURE MUST**

Continuation leases are explicitly finite in count and size. The maximum total execution allowance obtainable from all leases must be bounded by policy before execution begins.

## IBAE-BND-006 — No self-extension

**ARCHITECTURE MUST**

No model, local worker, tool backend, runtime, GPU kernel, or scheduler may grant itself additional execution budget.

## IBAE-BND-007 — Exact authority-bearing counters

**ARCHITECTURE MUST**

Requests, executions, retries, mutations, logical ticks, lease counters, execution addresses, and authority flags use exact integer/enumerated representations. Floating point cannot be the sole authority for these values.

## IBAE-BND-008 — Bounded batches and queues

**ARCHITECTURE MUST**

Batch proposal size, ready queue size, worker count, and other resident execution structures must have explicit finite bounds or deterministic streaming rules.

---

# 5. Observation reuse and cache integrity

## IBAE-REUSE-001 — Safe immutable observation reuse

**ENFORCED MUST**

A cached read observation may be reused only when canonical tool identity, canonical arguments, and declared dependency fingerprint are unchanged.

## IBAE-REUSE-002 — Dependency-sensitive invalidation

**ENFORCED MUST**

If a declared dependency fingerprint changes, the prior cached observation cannot satisfy the new request.

## IBAE-REUSE-003 — Cache mutation isolation

**ENFORCED MUST**

Caller mutation of a returned observation must not mutate the stored cached observation.

## IBAE-REUSE-004 — Validate before admission to cache

**ENFORCED MUST**

An observation must satisfy canonicalization/validation requirements before it is inserted into authoritative cache state.

## IBAE-REUSE-005 — Cache is not an authority bypass

**ENFORCED MUST**

Mutable cache insertion is not exposed as a public executor authority surface. A caller cannot forge an admitted observation by inserting directly into runtime cache state.

## IBAE-REUSE-006 — Reuse provenance is visible

**ARCHITECTURE MUST**

An agent-visible reused observation must expose enough provenance to determine that it is cached, where it originated, and which unchanged dependency condition keeps it valid.

---

# 6. Cycle detection, progress, and continuation

## IBAE-CYC-001 — Canonical short-cycle detection

**ENFORCED MUST**

Repeated canonical state patterns with period 1, 2, or 3 are detectable without wall-clock input.

## IBAE-CYC-002 — No unbounded identical transition

**ENFORCED MUST**

The execution kernel never relies solely on elapsed time to prevent repeated equivalent transitions. Finite request/execution bounds remain authoritative.

## IBAE-CYC-003 — Cache path preserves cycle semantics

**ENFORCED MUST**

Equivalent cold-execution and cache-hit transitions use the same canonical transition representation for cycle history.

## IBAE-PROG-001 — Progress is explicit

**ARCHITECTURE MUST**

Progress is computed from declared task obligations/acceptance conditions or another explicit deterministic predicate. Activity alone is not progress.

## IBAE-PROG-002 — Model confidence is not progress authority

**ARCHITECTURE MUST**

A model's self-reported confidence, percentage complete, or request for more time cannot by itself establish measurable progress or justify another execution lease.

## IBAE-PROG-003 — Obligation state is canonical

**ARCHITECTURE MUST**

Obligations have stable IDs, explicit satisfied/unsatisfied/blocked state, and declared dependencies. The orchestrator must not require the supervisor to remember obligation completion only from transcript prose.

## IBAE-PROG-004 — Continuation admission is deterministic

**ARCHITECTURE MUST**

A continuation lease may be granted only when:

- the task is not complete;
- lease capacity remains;
- no blocking governance/invariant violation exists;
- no disallowed terminal cycle exists; and
- measurable progress occurred or an explicitly admitted non-cyclic strategy change is available.

## IBAE-PROG-005 — Strategy identity is explicit

**ARCHITECTURE MUST**

A strategy change used to justify continuation must have a canonical identity distinct from superficial rewording of the same action sequence.

---

# 7. Governance and provider authority

## IBAE-GOV-001 — OpenAI-only remote proprietary inference

**ENFORCED MUST**

Any remote proprietary model provider admitted by the project must canonicalize to `openai`. Other proprietary remote providers are outside project scope.

This policy is implemented now and remains a continuing architectural obligation for all future provider/model integration layers.

## IBAE-GOV-002 — OpenAI supervisor completion authority

**ARCHITECTURE MUST**

When model orchestration is introduced, only the OpenAI supervisor may declare overall task completion at the model-authority layer. Completion still remains subject to deterministic acceptance/gate checks.

## IBAE-GOV-003 — Local workers are candidate-only

**ARCHITECTURE MUST**

Future local open-weight workers may produce candidate analyses/artifacts only. They receive no provider-selection, governance, lease-grant, or final-completion authority.

## IBAE-GOV-004 — Tool authority classes are explicit

**ARCHITECTURE MUST**

Tools/actions are classified before admission, at minimum distinguishing read/cacheable behavior from mutations and non-idempotent external side effects. Mutation authority cannot be inferred merely from tool availability.

## IBAE-GOV-005 — Governance identity is versioned

**ARCHITECTURE MUST**

Accepted execution is bound to a canonical governance/policy identity so a policy change cannot silently masquerade as the same governed run.

## IBAE-GOV-006 — Fail closed on unknown authority

**ARCHITECTURE MUST**

Unknown provider, unknown authority class, malformed policy, unsupported command class, or invalid governance receipt is rejected rather than guessed into an allowed state.

## IBAE-GOV-007 — Receipt admission precedes accepted finalization

**ARCHITECTURE MUST**

No final execution may be labelled accepted without the required governance/orchestration/execution receipts validating under the current contract.

---

# 8. Deterministic orchestration

## IBAE-ORCH-001 — Supervisor proposes, orchestrator admits

**ARCHITECTURE MUST**

OpenAI supplies intelligence and proposed actions. The deterministic orchestrator canonicalizes, classifies action authority/replay safety, deduplicates only where replay-safe equivalence is proven, dependency-checks, budget-checks, and admits/rejects those actions.

## IBAE-ORCH-002 — Ready-set calculation is deterministic

**ARCHITECTURE MUST**

For identical obligation/DAG state, policy, and admitted observations, the ready set is identical.

## IBAE-ORCH-003 — Duplicate elimination is replay-safe only

**ARCHITECTURE MUST**

Canonical equivalence and unchanged dependency state are sufficient for deduplication only for actions whose authority class is cacheable/read-only or is otherwise explicitly proven replay-safe under the active contract.

Mutations, non-idempotent external effects, and any action with occurrence-sensitive semantics must preserve each admitted occurrence even when canonical arguments are identical. Repeated proposal does not by itself authorize suppressing a required effect.

## IBAE-ORCH-004 — Batch admission preserves semantics

**ARCHITECTURE MUST**

Batching/parallelizing independent actions may alter execution-plan identity and performance, but cannot alter correctness identity or result semantics for an admitted deterministic case.

## IBAE-ORCH-005 — Dependency barriers are explicit

**ARCHITECTURE MUST**

An action that depends on an unsatisfied obligation/observation cannot be made ready merely by scheduling preference or model request.

## IBAE-ORCH-006 — Orchestration state is bounded

**ARCHITECTURE MUST**

Obligation graphs, ready sets, pending proposals, and retained orchestration history require explicit bounds or deterministic streaming/compaction policies.

## IBAE-ORCH-007 — Occurrence identity is preserved for effectful actions

**ARCHITECTURE MUST**

Each admitted mutation or non-idempotent action has occurrence identity distinct from content equivalence. An orchestrator may reorder an effectful action only when its dependency/ordering contract permits it, and may never merge two required occurrences into one execution merely because their payloads match.

---

# 9. Python/Rust runtime boundary

## IBAE-RT-001 — Python owns logic semantics; Rust owns exact runtime state

**ARCHITECTURE MUST**

Python is the initial governance/orchestration/OpenAI-facing logic core. Rust is the authoritative execution/accounting/reference-runtime layer once v0.3 is implemented.

## IBAE-RT-002 — Narrow versioned protocol

**ARCHITECTURE MUST**

Python and Rust communicate through a small versioned command/receipt protocol. Arbitrary internal Rust mutation surfaces must not be exposed to Python.

## IBAE-RT-003 — No direct Python mutation of authoritative Rust state

**ARCHITECTURE MUST**

Authority-bearing Rust runtime state changes only through admitted commands/transitions.

## IBAE-RT-004 — Runtime is model-provider agnostic internally

**ARCHITECTURE MUST**

The Rust runtime does not directly call OpenAI or any remote model endpoint. Provider/model integration belongs above the runtime boundary.

## IBAE-RT-005 — Cross-language conformance

**ARCHITECTURE MUST**

Every authority-bearing Rust transition must have reference fixtures sufficient to demonstrate conformance with the frozen semantic contract.

## IBAE-RT-006 — Performance implementation is not semantic authority

**ARCHITECTURE MUST**

Rust/CUDA/SIMD implementation speed cannot redefine the Python/reference semantic contract without a versioned architecture change and new conformance gate.

---

# 10. AI-facing interface

## IBAE-AI-001 — AI does not reconstruct deterministic state from prose

**ARCHITECTURE MUST**

If runtime state can be computed exactly by software, the supervisor must receive that state structurally rather than being required to infer it from a natural-language transcript.

## IBAE-AI-002 — Rejections have canonical reason codes

**ARCHITECTURE MUST**

Every governed rejection exposes a stable machine-readable reason code and relevant invariant/authority class.

## IBAE-AI-003 — Safe recovery actions are exposed when known

**ARCHITECTURE SHOULD**

If deterministic governance knows legal next moves after a rejection, the agent-facing response should expose them directly.

## IBAE-AI-004 — Epistemic state classes remain distinct

**ARCHITECTURE MUST**

Agent-visible state distinguishes at least:

```text
observed
derived
model_proposed
unknown
```

A proposal cannot silently become an observation. Unknown/unqueried cannot silently become false.

## IBAE-AI-005 — Runtime bookkeeping belongs to runtime

**ARCHITECTURE MUST**

Remaining budgets, logical ticks, cache-hit counts, obligation readiness, and other deterministic bookkeeping are computed by the runtime/orchestrator and presented directly to the model.

## IBAE-AI-006 — Smallest sufficient canonical state projection

**ARCHITECTURE SHOULD**

The supervisor receives a deterministic compact state digest sufficient for safe next-action reasoning instead of an ever-growing replay of the full execution transcript.

## IBAE-AI-007 — Cached observation validity is explicit

**ARCHITECTURE MUST**

The model can determine whether an observation is fresh or reused and which dependency identity makes reuse valid.

## IBAE-AI-008 — Capability state is explicit

**ARCHITECTURE SHOULD**

Available tool/work capability is surfaced structurally so the supervisor need not repeatedly attempt unavailable actions to discover capability state.

## IBAE-AI-009 — Local workers receive least authority/context

**ARCHITECTURE MUST**

Subordinate workers receive only the minimum task packet, input evidence, constraints, and output schema necessary for the bounded subproblem.

## IBAE-AI-010 — Batch proposal interface

**ARCHITECTURE SHOULD**

The supervisor may propose multiple actions in one structured batch so deterministic orchestration can deduplicate only replay-safe equivalent work, reuse valid observations, dependency-order actions, preserve occurrence-sensitive mutations, and parallelize independent work without requiring one model round-trip per low-level tool request.

---

# 11. Identity, receipts, and evidence separation

## IBAE-ID-001 — Task identity is distinct

**ARCHITECTURE MUST**

Task identity states what problem/acceptance contract is being attempted and is not execution-plan identity.

## IBAE-ID-002 — Governance identity is distinct

**ARCHITECTURE MUST**

Governance identity binds the authority/policy under which the task is admitted.

## IBAE-ID-003 — Orchestration identity is distinct

**ARCHITECTURE MUST**

Orchestration identity binds admitted obligations/dependencies/scheduling decisions relevant to orchestration semantics.

## IBAE-ID-004 — Execution correctness identity is distinct

**ARCHITECTURE MUST**

Execution correctness identity binds the canonical actions/observations/results that determine the accepted deterministic outcome.

## IBAE-ID-005 — Execution-plan identity is distinct

**ARCHITECTURE MUST**

Worker count, chunking, locality, device assignment, accelerator layout, and other implementation-plan fields live outside correctness identity unless they change semantics.

## IBAE-ID-006 — Benchmark receipt is observational

**ARCHITECTURE MUST**

Elapsed seconds, throughput, model turns, tokens, worker/device observations, and cache efficiency are benchmark data and cannot prove correctness by being fast.

## IBAE-ID-007 — Rejected/partial state is preserved as rejected/partial

**ARCHITECTURE MUST**

A rejected or partial run may be persisted for audit, but cannot later be relabelled accepted without satisfying the acceptance contract.

---

# 12. Accelerator and geometry boundary

## IBAE-ACC-001 — CPU/reference authority precedes accelerator authority

**ARCHITECTURE MUST**

GPU/SIMD execution is an optimization candidate until it passes explicit conformance against the reference runtime.

## IBAE-ACC-002 — Accelerator numerical/execution profile is explicit

**ARCHITECTURE MUST**

Any accelerator path has a versioned profile defining data types, deterministic assumptions, tolerated residuals if any, and conformance procedure.

## IBAE-ACC-003 — Floating point cannot govern authority

**ARCHITECTURE MUST**

`f32`/`f64` may be used for explicitly numerical/heuristic fields, but exact provider authority, budget counters, logical ticks, command IDs, and acceptance flags cannot depend solely on floating-point equality.

## IBAE-ACC-004 — Padding lanes are non-semantic by default

**ARCHITECTURE MUST**

If a 30-meaningful/32-wide GPU layout is tested, lanes 30 and 31 remain inactive/non-semantic padding unless a separately reviewed contract explicitly changes the layout. Governance metadata should default to a sidecar rather than silently occupying padding lanes.

## IBAE-ACC-005 — Geometry is optional optimization structure

**ARCHITECTURE MUST**

`C5 x K2 x C3`, CRT addressing, toroidal layouts, GLUBALL-style sampling, or other donor geometry cannot become IBAE task/governance semantics merely because they are elegant or accelerator-friendly.

## IBAE-ACC-006 — Cross-device correctness before speedup claim

**ARCHITECTURE MUST**

Local RTX-class GPU testing may establish candidate conformance/performance. Wider services such as Vast.ai are used for cross-device reproducibility only after the reference gate exists. Cross-device speed does not replace conformance.

---

# 13. Candidate research invariants

These are intentionally non-normative until benchmarked/admitted.

## IBAE-CAND-001 — Geometrically decreasing continuation leases

**CANDIDATE**

Evaluate bounded lease schedules such as `B`, `B/2`, `B/4`, where the maximum sum is finite and predetermined by governance.

## IBAE-CAND-002 — `C5 x K2 x C3` orchestration/execution address family

**CANDIDATE**

Evaluate whether a 30-state exact address family improves deterministic scheduling/GPU mapping without injecting artificial task semantics.

## IBAE-CAND-003 — Exact logical sampling over large candidate spaces

**CANDIDATE**

Evaluate GLUBALL-style exact integer sampling/partitioning for large logical action spaces without allocation proportional to logical cardinality.

---

# Verification rule

Each **implemented** MUST invariant must be enforced by at least one of:

- pure construction that makes violation unrepresentable;
- runtime assertion/exception;
- deterministic regression/conformance test;
- structural architecture rule with executable validation where practical.

Each new implementation PR must state:

1. which invariant IDs it implements or affects;
2. which invariant IDs remain architecture-only;
3. which tests prove the affected invariants;
4. whether any identity-bearing fields changed;
5. whether any benchmark-only field was accidentally promoted into correctness state.