# QSOL-IBAE Invariant Registry

Status: frozen architecture contract with accepted v0.3/v0.4 and v0.5
implementation-candidate enforcement annotations.

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

Current enforcement: sorted-key canonical JSON, fixed separators, UTF-8-safe text, rejection of NaN/Infinity, and rejection of non-string mapping keys. The v0.3 admitted runtime domain independently parses, bounds, renders, and byte-compares canonical JSON in Rust; Python/Rust bytes and SHA-256 values are fixture-tested for nested, Unicode, float, and 256-bit integer boundary cases.

## IBAE-DET-002 — Canonical tool identity

**ENFORCED MUST**

A read-tool request identity is derived only from its tool name, canonical arguments, and declared dependency fingerprint.

Python `hash()`, `id()`, memory address, wall-clock timestamp, and implicit process state must not participate.

Current enforcement: Python and Rust derive the same v0.1 tool key from tool name, canonical arguments, and the declared dependency fingerprint. Dependency changes force a cold execution in both implementations.

## IBAE-DET-003 — Deterministic admitted transition

**ENFORCED MUST**

Within a declared deterministic profile, identical admitted prior state + identical canonical command + identical dependency state must produce the same canonical transition result/receipt.

Current enforcement: the pure v0.2 `admit_batch` transition and checked-in model-free conformance fixture produce byte-identical decisions, event history, state identity, and admission receipt. The v0.3 Rust dispatcher additionally binds each command to its canonical prior-state identity and emits domain-separated canonical command, resulting-state, transition, and runtime-receipt identities; Python/Rust semantic projections and receipts are checked across hash seeds.

## IBAE-DET-004 — Deterministic orchestration ordering

**ENFORCED MUST**

When multiple actions are equally ready under the same policy and dependency state, the deterministic orchestrator must use a canonical ordering/admission rule rather than process/hash iteration accidents.

Current enforcement: obligations are ordered by canonical obligation ID; explicitly independent/read-only proposal batches are ordered by canonical proposal ID; effectful batches require an identity-bearing declared sequence and preserve it. The determinism workflow repeats the fixture under distinct `PYTHONHASHSEED` values.

## IBAE-DET-005 — Domain-separated identities

**ARCHITECTURE MUST**

Task, governance, orchestration, execution, execution-plan, observation, and receipt hashes must be domain-separated so equal raw payloads from different identity classes cannot alias semantically.

Current partial implementation domain-separates obligation, epistemic,
capability, strategy, proposal, batch, action, orchestration-state, event,
admission-receipt, runtime-session, runtime-command, runtime-state, and
runtime-receipt identities. v0.4 adds separate task, governance, governed-action
classification, tool-authorization manifest, orchestration, execution,
execution-plan, benchmark, final, rejection, partial, compact-evidence,
evidence-summary/expansion, admission aggregate, and gate-result domains. v0.3 still
preserves the frozen v0.1 plain SHA-256 tool/observation/transition identities
for cross-language equivalence, so the broad invariant remains architecture-only
rather than overclaiming complete taxonomy coverage.

---

# 3. Logical execution clock and time

## IBAE-CLK-001 — Logical clock is transition-derived

**ENFORCED MUST**

Primary execution progression is counted from canonical admitted transitions, not elapsed seconds.

Current enforcement: `IBAE-LOGICAL-CLOCK-V1` consumes one exact logical tick per canonical orchestration proposal decision and one tick for a canonical batch-level rejection. `IBAE-RUNTIME-PROTOCOL-V1` advances a checked Rust `u64` tick only from committed request, execution, cache/history, observation/history, or retry transitions. No wall-clock input participates.

## IBAE-CLK-002 — Wall clock is non-correctness observation

**ENFORCED MUST**

Elapsed time, throughput, queue delay, and tool latency are benchmark/environment observations and cannot enter correctness identity unless a separately reviewed protocol explicitly makes timing itself the subject of the task.

Current enforcement: the v0.2 canonical orchestration state, events, admitted action identities, and receipts expose no wall-clock field. Strategy identity uses `IBAE-STRATEGY-PARAMETERS-V1` plus a strategy-specific typed allowlist schema stored in admitted orchestration state; a mismatch returns a structured batch rejection and admits no proposal. Capability contracts use `IBAE-CAPABILITY-ARGUMENTS-V1` to allowlist semantic argument keys before action identity is computed. Proposal `observational_metadata` remains agent-visible but is excluded from proposal, batch, action, event, state, and receipt identity; placing an unlisted observation in semantic arguments returns a structured rejection.

## IBAE-CLK-003 — Wall-clock watchdog is failsafe only

**ENFORCED MUST**

An absolute time watchdog may exist to terminate catastrophic hangs or infrastructure failure, but normal task boundedness and completion semantics must not depend solely on that watchdog.

Current enforcement: normal runtime and continuation boundedness derives only
from exact precommitted budgets, lease/request ceilings, and logical
transitions. `IBAE-WATCHDOG-OBSERVATION-V1` is explicitly non-authoritative,
always reports `task_complete = false`, excludes elapsed magnitude from its
correctness identity, includes the correctness-relevant lease-exhaustion flag
in that identity, and must match independently computed lease-exhaustion state
before a watchdog partial can bind it.

## IBAE-CLK-004 — Cache hits still advance canonical activity

**ENFORCED MUST**

A cache hit may consume zero actual-execution quanta, but it remains a canonical request/transition event for request bounds, history, and loop detection.

Current enforcement: a Rust cache hit increments request and cache-hit counters, advances logical activity, appends the same transition identity used by its cold path, and consumes zero actual-execution quanta. Request-budget exhaustion rejects before reuse.

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

Current v0.3 enforcement for `IBAE-BND-001` through `IBAE-BND-004`: Rust owns the counters and bounded history, uses checked `u64` arithmetic, enforces the declared boundary before the corresponding transition, and never invokes an operation after actual-execution admission fails. Cache hits remain request-bounded.

## IBAE-BND-005 — Finite continuation leases

**ENFORCED MUST**

Continuation leases are explicitly finite in count and size. The maximum total execution allowance obtainable from all leases must be bounded by policy before execution begins.

Current enforcement: `IBAE-CONTINUATION-LEASE-V1` binds an exact initial
budget, finite ordered schedule, request cap, strategy-recovery cap, and total
ceiling equal to the initial budget plus the complete schedule. Governance
checks every requested/cumulative vector componentwise with checked arithmetic;
Rust independently checks the grant, indexed schedule, cumulative ledger, and
ceiling before changing limits.

## IBAE-BND-006 — No self-extension

**ENFORCED MUST**

No model, local worker, tool backend, runtime, GPU kernel, or scheduler may grant itself additional execution budget.

Current enforcement: only the closed OpenAI-supervisor principal can request;
trusted module initialization captures the exact evaluator/observer once in
native storage and removes its bootstrap entrypoint. Continuation-session
creation clones only those originals into a Rust-private per-instance authority
and returns a separate once-issued, session-scoped,
non-constructible supervisor request capability. The public principal label is
insufficient. An exact native request seal invokes only the pinned evaluator, and Rust validates
the authorized request plus full grant against the live session before issuing
the grant seal. No raw grant issuer or mutable Python validator is exposed, and
an equal-ID duplicate session carries distinct non-serialized authority. A
reconstructed hash-consistent grant is insufficient. Tool, runtime,
orchestrator, and candidate-worker requesters deny deterministically.
`request_lease` is not a Rust command, and a rejected or forged `apply_lease`
transition is state-, tick-, limit-, and resource-neutral.

## IBAE-BND-007 — Exact authority-bearing counters

**ARCHITECTURE MUST**

Requests, executions, retries, mutations, logical ticks, lease counters, execution addresses, and authority flags use exact integer/enumerated representations. Floating point cannot be the sole authority for these values.

Current v0.5 partial enforcement: all implemented runtime/evidence/continuation counters,
limits, logical ticks, statuses, authority classes, gate flags, and rejection
classes use checked exact integer or closed enumerated representations. Inputs
are type-checked, booleans are not accepted as integers, and hard caps prevent
unbounded resident state. Continuation policies and native application use
checked unsigned 64-bit resource/lease/tick arithmetic, with mutation present
but fixed to zero. Mutation execution and execution-address counters do not
exist yet; therefore this broad invariant remains architecture-only.

## IBAE-BND-008 — Bounded batches and queues

**ENFORCED MUST**

Batch proposal size, ready queue size, worker count, and other resident execution structures must have explicit finite bounds or deterministic streaming rules.

Current enforcement: v0.2 gives every model-facing collection boundary an explicit protocol/configuration cap, including obligation and epistemic registries/dependencies, capability semantic-argument keys and state keys, proposal targets/batches, admitted strategy schemas/parameters, persistent occurrence ownership, and retained history. Canonical model values additionally have explicit byte, depth, total-node, per-collection, string, and integer-size bounds enforced while copying the input before serialization. Free-text record fields have a 4,096-byte UTF-8 cap, identity-bearing integers have a 256-bit cap, and oversized strings are measured incrementally without allocating a full encoded copy. Bounded consumers stop at cap + 1 instead of fully materializing over-size/infinite iterables. v0.3 adds explicit hard caps for Rust requests, executions/cache entries, retries, history, canonical bytes/depth/nodes/items/strings, and tool/session text. v0.4 adds finite policy/gate/receipt collections, one-million-case streaming evidence admission, a fixed compact receipt ceiling, and bounded failure retention/expansion. v0.5 bounds progress dimensions, strategy material, lease schedule/request/decision history, continuation evidence, and all experimental profiles. No worker queue exists yet; any later worker phase inherits this invariant.

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

Current v0.2 partial implementation: compact epistemic projection retains the explicit `reused` delivery-path flag, while epistemic record, dependency, action, and orchestration-state correctness identities exclude that flag. Wiring the v0.1 cache to emit these records remains a later runtime-boundary obligation.

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

**ENFORCED MUST**

Progress is computed from declared task obligations/acceptance conditions or another explicit deterministic predicate. Activity alone is not progress.

Current enforcement: `IBAE-OBJECTIVE-PROGRESS-V1` compares a finite declared
integer measure contract over canonical obligation counts or governed external
counters. It emits closed measurable/no-progress/regression/new-information/
incomparable classes and computes completion independently. Both claims are
rederived from exact bound prior/current orchestration states and governed
counter evidence whenever a record is constructed or consumed. Tool activity
and elapsed time are absent. Canonical obligation sources enforce their safe
direction, and continuation policy/state/native context commit the exact
admitted progress-contract identity. Only `measurable_progress` may
independently authorize continuation.

## IBAE-PROG-002 — Model confidence is not progress authority

**ENFORCED MUST**

A model's self-reported confidence, percentage complete, or request for more time cannot by itself establish measurable progress or justify another execution lease.

Current enforcement: only exact obligation measures or task/governance-bound
`observed`/`derived` counter evidence can enter a progress record. Every
external counter is derived from an accepted native source-bound runtime
observation and matched to its exact governed read-tool admission; a supplied
fingerprint or structural receipt alone is insufficient. The continuation
evaluator validates and deliberately ignores bounded benchmark observations;
it has no confidence, percentage, token, or wall-clock input.

## IBAE-PROG-003 — Obligation state is canonical

**ENFORCED MUST**

Obligations have stable IDs, explicit satisfied/unsatisfied/blocked state, and declared dependencies. The orchestrator must not require the supervisor to remember obligation completion only from transcript prose.

Current enforcement: v0.2 provides immutable obligation records, key-derived canonical IDs, explicit status/block reason fields, validated dependency references, cycle rejection, and deterministic ready/blocking projections.

## IBAE-PROG-004 — Continuation admission is deterministic

**ENFORCED MUST**

A continuation lease may be granted only when:

- the task is not complete;
- lease capacity remains;
- no blocking governance/invariant violation exists;
- no disallowed terminal cycle exists; and
- measurable progress occurred or an explicitly admitted non-cyclic strategy change is available.

Current enforcement: one pure ordered decision function binds exact task,
governance/policy receipt, continuation/orchestration/runtime state, the exact
policy-bound live progress endpoint, strategy, and cycle evidence. Context
rebind requires the progress record's prior endpoint to equal the live
pre-rebind orchestration state. It returns a domain-separated grant or a closed
denial, advances a bounded continuation decision ledger, and cannot exceed the
precommitted request/schedule/cumulative ceilings. Period-1/2/3 evidence is
recomputed from live native history, so omitting caller evidence cannot bypass
a terminal-cycle denial; the compact projection reports both remaining
schedule slots and request decisions and suppresses impossible recoveries when
either is exhausted. Progress observation immediately refreshes the live
stalled/progressing/complete control state. The built-in contract counts both
unsatisfied and blocked obligations, so newly blocked work cannot authorize a
lease. External evidence is paired with declared dimensions in canonical key
order. A measurable progress identity is consumed by its first
progress-authorized grant, so a later progress-based grant requires a freshly
observed endpoint. Only exact context observation may replace that live
endpoint; denials preserve it. Native evaluator-issued lineage binds the decision ledger,
last decision/denial, progress identity/classification/state, consumed endpoint,
and recovery count; context observation is resealed through the pinned native
observer.
Repeated inputs produce byte-identical fixtures across hash seeds.

## IBAE-PROG-005 — Strategy identity is explicit

**ENFORCED MUST**

A strategy change used to justify continuation must have a canonical identity distinct from superficial rewording of the same action sequence.

Current enforcement: the v0.2 typed strategy identity is combined with a
v0.5 material identity over available capability frontier, target obligations,
ordered dependency path, recovery mode, and initial transition pattern.
Description/paraphrase is excluded. Admission requires a different strategy
identity, structured material difference, active schema, known targets and
capabilities, at least one bound target, and a pattern that does not reproduce
bound period-1/2/3 cycle evidence. Every receipt revalidates its exact bound
orchestration state, prior/proposed material, status, reason, and cycle evidence
before it can authorize recovery. A strategy receipt may authorize only the
policy-bounded recovery count and is never classified as progress. The live
recovery count is protected by evaluator-issued decision lineage; reconstructing
that public counter cannot restore recovery authority.

---

# 7. Governance and provider authority

## IBAE-GOV-001 — OpenAI-only remote proprietary inference

**ENFORCED MUST**

Any remote proprietary model provider admitted by the project must canonicalize to `openai`. Other proprietary remote providers are outside project scope.

This policy is implemented now and remains a continuing architectural obligation for all future provider/model integration layers.

## IBAE-GOV-002 — OpenAI supervisor completion authority

**ARCHITECTURE MUST**

When model orchestration is introduced, only the OpenAI supervisor may declare overall task completion at the model-authority layer. Completion still remains subject to deterministic acceptance/gate checks.

Current v0.4 partial enforcement: the deterministic governance API accepts
task admission/finalization requests only from the closed OpenAI-supervisor
principal and still requires receipt/gate validation. No live OpenAI model path
exists, so the full integration invariant remains architecture-only.

## IBAE-GOV-003 — Local workers are candidate-only

**ARCHITECTURE MUST**

Future local open-weight workers may produce candidate analyses/artifacts only. They receive no provider-selection, governance, lease-grant, or final-completion authority.

Current v0.4 partial enforcement: a future local candidate worker is a separate
closed principal class and is rejected from task admission, tool admission, and
finalization. No worker adapter exists yet.

## IBAE-GOV-004 — Tool authority classes are explicit

**ENFORCED MUST**

Tools/actions are classified before admission, at minimum distinguishing read/cacheable behavior from mutations and non-idempotent external side effects. Mutation authority cannot be inferred merely from tool availability.

Current enforcement: the governance policy requires one of five closed classes
(`pure_read`, `snapshot_read`, `volatile_read`, `idempotent_mutation`, or
`non_idempotent_mutation`) plus explicit mutation and cache-reuse booleans.
Snapshot reuse requires dependency identity, volatile reads/mutations cannot be
cache-reusable, and volatile reads/mutations require occurrence identity in the
conservative v1 profile. Each governed tool receipt binds and recomputes one
exact typed v0.2 admitted decision, proposal, capability, dependency state, and
action ID; the orchestration receipt requires exact bounded coverage and
commits to an authorization manifest capped by the current 64-action governed
batch limit, while the evidence reducer also enforces a defensive
256-authorization ceiling. A finalizable sealed v0.3 read
must match that manifest's action, tool, canonical arguments, dependency,
command class, governed admission receipt, and cache-reuse policy before
evidence-state mutation. A sealed retry must name a known admission, preserves
exact continuity/accounting, and cannot satisfy read coverage alone. The
accepted v0.2 replay class and v0.3 capability/action recomputation remain
independently enforced. Effect execution is not claimed because the accepted
runtime protocol remains read-only.

## IBAE-GOV-005 — Governance identity is versioned

**ENFORCED MUST**

Accepted execution is bound to a canonical governance/policy identity so a policy change cannot silently masquerade as the same governed run.

Current enforcement: `IBAE-GOVERNANCE-PROTOCOL-V1` hashes the complete bounded
policy key/version, OpenAI provider class, task profile/version, gate set, and
tool permissions in a dedicated governance domain. Policy-version changes alter
the governance identity and all downstream bindings.

## IBAE-GOV-006 — Fail closed on unknown authority

**ENFORCED MUST**

Unknown provider, unknown authority class, malformed policy, unsupported command class, or invalid governance receipt is rejected rather than guessed into an allowed state.

Current enforcement: policy/receipt parsers require exact fields and closed
enums, all authority APIs fail closed, and rejections carry immutable canonical
reason/invariant records. Existing Rust unsupported-command rejection remains
unchanged.

## IBAE-GOV-007 — Receipt admission precedes accepted finalization

**ENFORCED MUST**

No final execution may be labelled accepted without the required governance/orchestration/execution receipts validating under the current contract.

Current enforcement: finalization reconstructs and binds the exact task,
governance, accepted v0.2 admission plus governed authorization manifest,
fixed-shape execution with typed first/last runtime receipts, direct-case native-
sealed compact evidence, and the exact closed three-gate set bound to the
corresponding receipt IDs. Missing elements produce immutable partial records;
malformed/foreign bindings produce immutable rejection records. Structural
hashes alone cannot finalize a task.

---

# 8. Deterministic orchestration

## IBAE-ORCH-001 — Supervisor proposes, orchestrator admits

**ARCHITECTURE MUST**

OpenAI supplies intelligence and proposed actions. The deterministic orchestrator canonicalizes, classifies action authority/replay safety, deduplicates only where replay-safe equivalence is proven, dependency-checks, budget-checks, and admits/rejects those actions.

Current partial implementation covers immutable v0.2 proposal records,
orchestrator-owned capability/replay and semantic-argument classification,
observation-versus-correctness metadata separation, obligation and epistemic
dependency checks, bounded batches, and structured admission/rejection. v0.4
adds governed authorization-manifest binding for admitted actions and the
accepted v0.3 runtime owns exact execution-budget admission. Live supervisor
proposal integration remains v0.6.

## IBAE-ORCH-002 — Ready-set calculation is deterministic

**ENFORCED MUST**

For identical obligation/DAG state, policy, and admitted observations, the ready set is identical.

Current enforcement: the validated v0.2 obligation DAG computes readiness solely from canonical obligation status and dependency state.

## IBAE-ORCH-003 — Duplicate elimination is replay-safe only

**ENFORCED MUST**

Canonical equivalence and unchanged dependency state are sufficient for deduplication only for actions whose authority class is cacheable/read-only or is otherwise explicitly proven replay-safe under the active contract.

Mutations, non-idempotent external effects, and any action with occurrence-sensitive semantics must preserve each admitted occurrence even when canonical arguments are identical. Repeated proposal does not by itself authorize suppressing a required effect.

Current enforcement: replay classification and semantic argument-key allowlists are read from the orchestrator-owned versioned capability record, capability-owned dependencies cannot be omitted by a proposal, observational metadata is excluded from action identity, non-read replay safety requires an explicit evidence identity, and only cacheable-read/proven-replay-safe equal action identities are coalesced within a batch.

## IBAE-ORCH-004 — Batch admission preserves semantics

**ARCHITECTURE MUST**

Batching/parallelizing independent actions may alter execution-plan identity and performance, but cannot alter correctness identity or result semantics for an admitted deterministic case.

Current enforcement proves v0.2 admission equivalence across input order only
for batches that explicitly declare canonical independence. Batches containing
effectful capabilities require an identity-bearing declared sequence, which
admission preserves. v0.4 adds a separate non-correctness execution-plan
receipt; physical parallel execution remains later-phase work.

## IBAE-ORCH-005 — Dependency barriers are explicit

**ENFORCED MUST**

An action that depends on an unsatisfied obligation/observation cannot be made ready merely by scheduling preference or model request.

Current enforcement: unknown, satisfied, explicitly blocked, dependency-blocked, epistemically unknown, and unadmitted model-proposed inputs produce canonical rejections and recovery actions. Only observed or valid derived epistemic records satisfy action dependencies.

## IBAE-ORCH-006 — Orchestration state is bounded

**ENFORCED MUST**

Obligation graphs, ready sets, pending proposals, and retained orchestration history require explicit bounds or deterministic streaming/compaction policies.

Current enforcement: `OrchestrationLimits` cannot exceed protocol hard caps; all exposed iterable inputs, free-text records, identity integers, and canonical model payloads are validated through explicit structural/byte bounds before retention/serialization; over-size proposal construction/admission fails closed; admitted strategy schemas have a finite registry; retained history uses deterministic bounded truncation; and persistent occurrence ownership rejects new effects when its exact registry reaches capacity.

## IBAE-ORCH-007 — Occurrence identity is preserved for effectful actions

**ENFORCED MUST**

Each admitted mutation or non-idempotent action has occurrence identity distinct from content equivalence. An orchestrator may reorder an effectful action only when its dependency/ordering contract permits it, and may never merge two required occurrences into one execution merely because their payloads match.

Current enforcement: occurrence-sensitive capabilities require a unique occurrence key, bind it into action identity, never enter the replay-safe deduplication index, and persist bounded occurrence ownership across batches so reuse is rejected rather than treated as a cache hit. Effectful batches also require and preserve an explicit declared sequence.

---

# 9. Python/Rust runtime boundary

## IBAE-RT-001 — Python owns logic semantics; Rust owns exact runtime state

**ENFORCED MUST**

Python is the initial governance/orchestration/OpenAI-facing logic core. Rust is the authoritative execution/accounting/reference-runtime layer once v0.3 is implemented.

Current enforcement: the supported Python `InvariantExecutor` delegates all implemented execution accounting, cache/history mutation, cycle state, logical ticks, and runtime receipts to an opaque Rust session. The retained Python implementation is named and documented as a conformance-only oracle.

## IBAE-RT-002 — Narrow versioned protocol

**ENFORCED MUST**

Python and Rust communicate through a small versioned command/receipt protocol. Arbitrary internal Rust mutation surfaces must not be exposed to Python.

Current enforcement: `IBAE-RUNTIME-PROTOCOL-V1` admits `execute_read` and
`record_retry`, plus `apply_lease` only for a session opted into an exact
continuation policy/receipt pair. Commands and observations cross as bounded
canonical records; unsupported variants reject structurally. Rust cannot
request or grant a lease, and finalization/effect commands are absent.

## IBAE-RT-003 — No direct Python mutation of authoritative Rust state

**ENFORCED MUST**

Authority-bearing Rust runtime state changes only through admitted commands/transitions.

Current enforcement: the non-subclassable PyO3 session exposes dispatch, copied snapshot, and cycle query only. Counters, cache, history, tick, and limits have no Python setter or cache-insertion method; returned observations and snapshots are caller-owned copies.

## IBAE-RT-004 — Runtime is model-provider agnostic internally

**ENFORCED MUST**

The Rust runtime does not directly call OpenAI or any remote model endpoint. Provider/model integration belongs above the runtime boundary.

Current enforcement: the Rust crate dependency graph contains only PyO3, JSON/canonical formatting, and SHA-256 support. It has no HTTP, socket, async runtime, SDK, provider, or model integration.

## IBAE-RT-005 — Cross-language conformance

**ENFORCED MUST**

Every authority-bearing Rust transition must have reference fixtures sufficient to demonstrate conformance with the frozen semantic contract.

Current enforcement: Rust unit tests and Python integration tests cover canonical bytes/hashes, repeated reads, dependency invalidation, invalid observations, caller mutation isolation, each budget boundary, bounded history, cycle equivalence, unsupported commands, and wall-clock neutrality. The v0.3 checked-in fixture compares the merged Python reference and Rust semantic projections and receipts under multiple `PYTHONHASHSEED` values. v0.5 adds adversarial Rust application tests for exact acceptance, duplicate/skip replay, forged identity, overflow, and state-neutral rejection, plus a checked-in end-to-end Python/Rust progress/continuation fixture across hash seeds.

## IBAE-RT-006 — Performance implementation is not semantic authority

**ENFORCED MUST**

Rust/CUDA/SIMD implementation speed cannot redefine the Python/reference semantic contract without a versioned architecture change and new conformance gate.

Current enforcement: runtime correctness records contain no elapsed time, throughput, worker, chunk, device, build, or scheduling-plan field. v0.3 makes no speedup claim and introduces no accelerator or parallel execution path.

---

# 10. AI-facing interface

## IBAE-AI-001 — AI does not reconstruct deterministic state from prose

**ARCHITECTURE MUST**

If runtime state can be computed exactly by software, the supervisor must receive that state structurally rather than being required to infer it from a natural-language transcript.

## IBAE-AI-002 — Rejections have canonical reason codes

**ARCHITECTURE MUST**

Every governed rejection exposes a stable machine-readable reason code and relevant invariant/authority class.

Current v0.4 partial implementation: orchestration admissions, Rust runtime
transitions, and governance/finalization decisions expose closed canonical
reason codes with authority/invariant and bounded blocking state. This includes
strategy/capability drift, batch/dependency/ordering/occurrence failures,
runtime protocol/budget/observation failures, and authority/receipt/gate
failures. Some local constructor/value errors and future lease/worker paths are
not governed rejection receipts, so the broad interface invariant remains
architecture-only.

## IBAE-AI-003 — Safe recovery actions are exposed when known

**ARCHITECTURE SHOULD**

If deterministic governance knows legal next moves after a rejection, the agent-facing response should expose them directly.

Current v0.2 implementation includes a closed `RecoveryAction` enum and returns deterministic recovery actions with each supported rejection.

## IBAE-AI-004 — Epistemic state classes remain distinct

**ENFORCED MUST**

Agent-visible state distinguishes at least:

```text
observed
derived
model_proposed
unknown
```

A proposal cannot silently become an observation. Unknown/unqueried cannot silently become false.

Current enforcement: v0.2 uses distinct immutable record classes, forbids values on `unknown`, requires provenance on `observed`, marks every proposal `model_proposed`, prevents model-proposed values from satisfying admitted dependencies or changing authoritative orchestration-state identity, and still exposes them in a separate compact-projection collection.

## IBAE-AI-005 — Runtime bookkeeping belongs to runtime

**ARCHITECTURE MUST**

Remaining budgets, logical ticks, cache-hit counts, obligation readiness, and other deterministic bookkeeping are computed by the runtime/orchestrator and presented directly to the model.

## IBAE-AI-006 — Smallest sufficient canonical state projection

**ARCHITECTURE SHOULD**

The supervisor receives a deterministic compact state digest sufficient for safe next-action reasoning instead of an ever-growing replay of the full execution transcript.

Current v0.2 implementation exposes a bounded compact projection containing canonical state identity, logical tick, ready/blocked/satisfied obligations with descriptions and explicit block reasons, epistemic classes, capability state, occurrence ownership, and remaining resident-state capacity. Delivery to a live supervisor is deferred to v0.6.

## IBAE-AI-007 — Cached observation validity is explicit

**ARCHITECTURE MUST**

The model can determine whether an observation is fresh or reused and which dependency identity makes reuse valid.

Current v0.2 partial implementation: observed epistemic records require provenance containing source identity, dependency identity, and an explicit `reused` flag; compact projection preserves those fields, while correctness identity excludes only the fresh-versus-reused delivery path. Wiring the v0.1 cache to emit these records remains a later runtime-boundary obligation.

## IBAE-AI-008 — Capability state is explicit

**ARCHITECTURE SHOULD**

Available tool/work capability is surfaced structurally so the supervisor need not repeatedly attempt unavailable actions to discover capability state.

Current v0.2 implementation includes versioned capability identity, replay class, required state dependencies, availability, and description in the compact projection. It also exposes the admitted typed strategy-schema registry and its remaining bounded capacity.

## IBAE-AI-009 — Local workers receive least authority/context

**ARCHITECTURE MUST**

Subordinate workers receive only the minimum task packet, input evidence, constraints, and output schema necessary for the bounded subproblem.

## IBAE-AI-010 — Batch proposal interface

**ARCHITECTURE SHOULD**

The supervisor may propose multiple actions in one structured batch so deterministic orchestration can deduplicate only replay-safe equivalent work, reuse valid observations, dependency-order actions, preserve occurrence-sensitive mutations, and parallelize independent work without requiring one model round-trip per low-level tool request.

Current v0.2 implementation provides immutable canonical batch proposals and deterministic admission/deduplication decisions. Execution parallelism and live supervisor integration remain later phases.

---

# 11. Identity, receipts, and evidence separation

## IBAE-ID-001 — Task identity is distinct

**ENFORCED MUST**

Task identity states what problem/acceptance contract is being attempted and is not execution-plan identity.

Current enforcement: an immutable task receipt hashes only its versioned task
key, bounded canonical acceptance contract, contract version, and required gate
set in task-specific identity and receipt domains.

## IBAE-ID-002 — Governance identity is distinct

**ENFORCED MUST**

Governance identity binds the authority/policy under which the task is admitted.

Current enforcement: see `IBAE-GOV-005`; governance semantic identity and
governance receipt identity use distinct domains.

## IBAE-ID-003 — Orchestration identity is distinct

**ENFORCED MUST**

Orchestration identity binds admitted obligations/dependencies/scheduling decisions relevant to orchestration semantics.

Current enforcement: the v0.4 orchestration receipt binds the governed task to
the exact accepted v0.2 admission receipt, batch, prior/final orchestration
states, logical-tick interval, and bounded governed authorization manifest in
orchestration-specific domains.

## IBAE-ID-004 — Execution correctness identity is distinct

**ENFORCED MUST**

Execution correctness identity binds the canonical actions/observations/results that determine the accepted deterministic outcome.

Current enforcement: a fixed-shape execution receipt binds the governed
orchestration and authorization manifest, one continuous runtime session and
its initial/final states, typed first/last strict v0.3 runtime receipts, exact
transition count, and ordered admission/input/result/runtime-receipt roots.
Final native-sealed compact evidence must reproduce the manifest, boundary,
counts, and roots.

## IBAE-ID-005 — Execution-plan identity is distinct

**ENFORCED MUST**

Worker count, chunking, locality, device assignment, accelerator layout, and other implementation-plan fields live outside correctness identity unless they change semantics.

Current enforcement: execution-plan records have a separate identity/receipt
domain and `correctness_authority: false`; plan changes do not alter task,
governance, orchestration, execution, or final identity. Grouping-sensitive
hierarchical evidence is consequently not admitted into the v0.4 final path.

## IBAE-ID-006 — Benchmark receipt is observational

**ENFORCED MUST**

Elapsed seconds, throughput, model turns, tokens, worker/device observations, and cache efficiency are benchmark data and cannot prove correctness by being fast.

Current enforcement: benchmark observations live only in a dedicated benchmark
record with `correctness_authority: false`. Benchmark records are excluded from
execution and final-acceptance constructors and identities. The v0.5
model-free budget comparison reports any componentwise unmet base demand as an
exact deficit and denies that scenario as base-budget exhausted instead of
silently clipping demand and declaring completion.

## IBAE-ID-007 — Rejected/partial state is preserved as rejected/partial

**ENFORCED MUST**

A rejected or partial run may be persisted for audit, but cannot later be relabelled accepted without satisfying the acceptance contract.

Current enforcement: rejection, partial, and final acceptance are separate
immutable record classes with fixed closed statuses and distinct receipt
domains. v0.5 checkpoints require status to equal the live continuation state;
any supplied strategy must equal the live strategy even when that identity is
absent, and remaining leases use the effective request/schedule minimum;
semantic partial evidence IDs are derived from the cited checkpoint and cannot
be replaced by unrelated fingerprints. A later accepted attempt creates a new
final receipt rather than mutating earlier evidence.

---

# 12. Compact evidence

## IBAE-EVID-001 — Execution state is not evidence transport

**ENFORCED MUST**

Large internal execution state is not required to cross an authority boundary
merely because it exists.

Current enforcement: the opaque Rust reducer retains fixed aggregate state and
only a bounded distinct authorization-observation set, with no successful
per-case trace. Python receives a copied fixed-shape summary and compact receipt
rather than Rust-owned resident execution/evidence state.

## IBAE-EVID-002 — Routine evidence is bounded

**ENFORCED MUST**

For a declared compact-evidence profile, routine successful evidence has a
fixed or explicitly bounded maximum size independent of underlying workload
cardinality.

Current enforcement: `IBAE-COMPACT-EVIDENCE-V1` rejects receipts larger than
2,048 canonical UTF-8 bytes for up to 1,000,000 admitted cases. CI compares 1,
1,000, and 100,000-case model-free reductions and verifies the same ceiling.

## IBAE-EVID-003 — Authority-bearing aggregates are exact

**ENFORCED MUST**

Counts used as correctness/governance evidence use exact integer arithmetic.

Current enforcement: case/status and request/execution/cache/retry/mutation/
mismatch totals use checked Rust `u64` addition. Overflow, inconsistent child
counts, oversize cases, and exhausted case bounds reject atomically.

## IBAE-EVID-004 — Failure supports selective expansion

**ENFORCED MUST**

Detailed per-operation evidence is exceptional, explicitly requested,
parent-bound, and bounded.

Current enforcement: the compact receipt exposes only exact failure count,
first index, detail availability, and truncation. At most 32 failure details of
at most 4,096 canonical bytes each are retained; expansion requires the exact
finalized parent identity and is capped by count and 262,144 output bytes.

## IBAE-EVID-005 — Fast folds are not cryptographic authority

**ENFORCED MUST**

A fast XOR/fold/checksum may provide regression evidence but cannot replace
canonical cryptographic receipt identity.

Current enforcement: the optional FNV-1a-64 observation is emitted separately
with `correctness_authority: false`. It is absent from the compact evidence,
execution, and final receipt identities; enabling it cannot change those IDs.

## IBAE-EVID-006 — Evidence sufficiency is versioned

**ENFORCED MUST**

Each compact evidence profile states exactly which claims/invariants it is
sufficient to support.

Current enforcement: the closed v1 counts-and-identities profile validates
exact processed/classified counts, exact admitted counter sums, authorization-
manifest coverage, continuous runtime boundaries, ordered admission/input/
result/receipt commitments, reported verifier mismatches, and execution
manifest/root/boundary/count correspondence. It explicitly does not claim
producer authentication, external truth, durable availability, benchmark
superiority, or semantics outside the declared verifier.

## IBAE-EVID-007 — Underlying evidence remains auditable

**ARCHITECTURE MUST**

Compact transport must not destroy the ability to deterministically reproduce,
locate, or selectively inspect underlying execution evidence when required.

Current v0.4 partial enforcement: a bounded prefix of failure details can be
located and expanded from a live parent-bound reducer, and aggregate commitments
detect input/result/order changes. Successful leaves and details beyond the
bounded prefix are not durably retained; arbitrary inclusion proofs, replay
locators, and grouping-neutral hierarchical roots remain later versioned work.

---

# 13. Accelerator and geometry boundary

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

# 14. Candidate research invariants

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
