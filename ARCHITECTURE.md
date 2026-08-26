# QSOL-IBAE Architecture

Status: frozen architecture contract with accepted v0.2 Python orchestration,
accepted v0.3 Rust runtime, and v0.4 governance/compact-evidence implementation
candidate.

QSOL-IBAE is a small OpenAI-exclusive governed execution substrate, not a general-purpose proprietary multi-provider agent framework.

The architecture is designed around one principle:

> **Use model intelligence for reasoning. Use deterministic software for bookkeeping, admission, boundedness, reuse, and execution evidence.**

See `INVARIANTS.md` for normative invariant IDs and `ROADMAP.md` for implementation order.

---

## 1. Authority layers

QSOL-IBAE separates three authority layers, one deterministic evidence plane,
and one observational benchmark layer:

```text
                    USER
                      |
                      v
              OPENAI SUPERVISOR
                      |
                      v
+--------------------------------------------------+
|               GOVERNANCE WRAPPER                 |
|                                                  |
| provider policy                                  |
| authority hierarchy                              |
| tool/mutation permissions                        |
| lease ceilings                                   |
| receipt admission                                |
| fail-closed policy                               |
|                                                  |
|  +--------------------------------------------+  |
|  |       DETERMINISTIC ORCHESTRATION          |  |
|  |                                            |  |
|  | obligations / dependency DAG               |  |
|  | proposal -> admission                       |  |
|  | canonical scheduling                        |  |
|  | deduplication / reuse eligibility           |  |
|  | progress / strategy / continuation          |  |
|  |                                            |  |
|  |  +--------------------------------------+  |  |
|  |  |          EXECUTION RUNTIME           |  |  |
|  |  |                                      |  |  |
|  |  | exact budget accounting              |  |  |
|  |  | logical execution clock              |  |  |
|  |  | canonical identities                 |  |  |
|  |  | cache / invalidation                 |  |  |
|  |  | cycle detection                      |  |  |
|  |  | command/observation receipts         |  |  |
|  |  +--------------------------------------+  |  |
|  |                     |                       |  |
|  |                     v                       |  |
|  |  +--------------------------------------+  |  |
|  |  |       COMPACT EVIDENCE REDUCER       |  |  |
|  |  | exact streaming aggregates          |  |  |
|  |  | bounded routine transport            |  |  |
|  |  +--------------------------------------+  |  |
|  +--------------------------------------------+  |
+--------------------------------------------------+
                      |
                      v
                 FINAL RECEIPT

BENCHMARK / PERFORMANCE OBSERVATIONS
    remain outside correctness authority
```

Normative boundary:

```text
governance != orchestration != execution != benchmark

execution state != evidence transport
```

Lower layers cannot promote themselves upward.

---

## 2. Model and deterministic authority

The OpenAI supervisor remains the intelligent decision-maker. It may propose plans, obligations, actions, strategy changes, lease requests, and completion.

Those proposals become authoritative only after deterministic admission.

```text
OpenAI supervisor
    proposes
        |
        v
Deterministic orchestrator
    canonicalizes
    dependency-checks
    deduplicates
    budget-checks
    policy-checks
    admits/rejects
        |
        v
Execution runtime
    executes admitted command
    records exact transition
    emits receipt
```

Future local open-weight models are workers, not peers. They return candidate results through a restricted task packet and do not receive governance, provider-selection, final-completion, or lease-grant authority.

---

## 3. Python logic core and Rust runtime

The v0.4 modular implementation split is:

### Python logic core

Python owns change-friendly semantic logic:

- governance configuration and policy composition;
- task/obligation construction;
- deterministic orchestration reference semantics;
- progress predicates and strategy representation;
- AI-facing compact state projection;
- governance receipt-chain validation and final-acceptance interpretation;
- future OpenAI API/SDK integration;
- future local-worker adapters;
- benchmark/research harnesses.

### Rust runtime

Rust owns exact authority-bearing runtime mechanics:

- immutable/controlled execution state transitions;
- exact integer budget counters;
- logical execution clock;
- canonical hashing/identity;
- observation cache and invalidation;
- cycle detection;
- deterministic bounded containers/streaming;
- execution and correctness receipts;
- deterministic CPU reference execution;
- future SIMD/CUDA-facing runtime adapters.

### Rust compact-evidence plane

The separate evidence-plane component owns:

- opaque, checked streaming reduction of admitted runtime receipts;
- bounded exact counter and canonical-identity aggregation;
- bounded failure-detail retention and explicit expansion;
- non-constructible in-process source seals for exact runtime receipts,
  aggregate summaries, and compact receipts.

The reducer does not own runtime transition authority or governance acceptance.

The bridges are in-process and narrow: PyO3 + maturin, with one opaque runtime
session, one canonical command dispatcher, and one opaque bounded evidence
accumulator. RPC, daemons, sockets, async runtimes, and distributed
infrastructure are absent and deferred.

Conceptually:

```text
Python command record
        |
        v
Rust admission/transition
        |
        v
Rust receipt record
        |
        v
Rust compact-evidence reducer
        |
        v
Python governance interpretation / orchestration update
```

Python must not mutate authoritative Rust runtime state directly.

The Rust runtime must not directly call OpenAI or another model provider.

The exact v0.3 record schemas, accounting deltas, identity domains, and rejection taxonomy are defined in `RUNTIME_PROTOCOL.md`.

The v0.4 policy, receipt-chain, compact-evidence, trust-scope, and size
contracts are defined in `GOVERNANCE_PROTOCOL.md` and `EVIDENCE_PROTOCOL.md`.
The evidence reducer is an execution-support mechanism, not governance
authority.

---

## 4. Versioned narrow protocol

The Python/Rust and agent-facing surfaces should remain small enough to audit completely.

Implemented runtime command family:

```text
IBAE-RUNTIME-PROTOCOL-V1
    execute_read
    record_retry
```

`execute_read` is restricted to Python/orchestrator-classified cacheable reads. The callback crosses the bridge only as a controlled canonical observation envelope. Rust admits request/execution activity before invocation, validates the canonical observation before cache insertion, and emits a canonical receipt. `record_retry` performs exact bounded retry accounting. Unsupported command variants fail closed without mutating runtime state.

`REQUEST_LEASE`, finalization, governance admission, generic mutation/effect execution, RPC, and worker commands are deliberately absent; they belong to later phases.

Candidate agent-facing protocol:

```text
IBAE-AGENT-PROTOCOL-V1

STATE
PROPOSAL
ADMISSION
RESULT
LEASE
FINALIZATION
```

The agent-facing names remain architecture candidates until their later phases, but the principle is normative: arbitrary implementation internals must not leak into the authority surface.

---

## 5. Deterministic logical execution clock

IBAE does not treat elapsed seconds as the primary measure of agent progress.

Instead, canonical admitted transitions advance a logical execution clock.

```text
request -> cache/reuse -> execute -> observation -> verify -> replan
  t1          t2           t3          t4          t5        t6
```

Different resource classes are tracked separately:

```text
requests
actual executions
retries
mutations
retained history
continuation leases
```

A cache hit may consume no actual-execution quantum, but it still counts as a canonical request/transition so caching cannot create a free infinite loop.

Wall-clock time remains useful for latency/benchmark observations and as a catastrophic-hang watchdog. It is not normal correctness or completion identity.

---

## 6. Progress and bounded continuation

Continuation is a governed lease, not a timeout reset.

The orchestrator tracks explicit obligations/acceptance conditions rather than asking the model to remember completion state from prose.

Example:

```text
O1 inspect review feedback       satisfied
O2 patch executor                satisfied
O3 add regression tests          satisfied
O4 CI green                      blocked/pending
O5 resolve review threads        blocked by O4
```

Progress is an objective change in declared obligations/acceptance state. Model confidence or "I am nearly finished" is not sufficient evidence.

A continuation lease can be requested by the supervisor but granted only under deterministic governance rules such as:

```text
task incomplete
AND lease capacity remains
AND no blocking invariant violation
AND no disallowed cycle
AND (measurable progress OR admitted non-cyclic strategy change)
```

Lease count and total possible extension are finite before execution begins.

Geometrically decreasing lease sizes are a candidate policy to benchmark, not yet a frozen constant.

---

## 7. AI-native state surface

IBAE should reduce the amount of cognitive plumbing required from the OpenAI supervisor.

The agent should receive a compact structural state such as:

```text
task status
ready obligations
actionable blockers
remaining budgets
cycle/progress state
available capabilities
valid cached observations
legal recovery actions
canonical state identity
```

Rather than requiring the model to infer runtime truth from a large transcript.

Agent-visible state must keep distinct epistemic classes:

```text
observed
    obtained from an admitted tool/runtime observation

derived
    deterministically computed from observed/canonical state

model_proposed
    suggested by a model but not yet admitted

unknown
    not observed/resolved
```

Unknown is not false. Proposal is not observation.

Rejected actions should return machine-readable reason codes and, where deterministically known, legal next actions.

Reused observations should expose provenance and dependency validity so the model need not reread merely to determine whether cache state is trustworthy.

---

## 8. Batch proposals and reduced model round trips

The OpenAI supervisor should eventually be able to propose a batch:

```text
read A
read B
inspect C
verify D
```

The deterministic orchestrator may then:

- remove canonical duplicates;
- satisfy actions from valid cache;
- enforce dependencies;
- reject disallowed actions;
- canonicalize scheduling order;
- parallelize independent reads;
- return one bounded result packet.

Batching may alter execution-plan/performance identity but must not alter correctness semantics for admitted deterministic cases.

---

## 9. Identity and receipt model

IBAE separates at least six record classes.

### Task identity

What acceptance problem is being attempted.

### Governance identity

Which policy/version/authority admits the run.

### Orchestration identity

Which obligations/dependencies/admission decisions define the orchestrated plan.

### Execution correctness identity

Which canonical actions/observations/results determine the accepted outcome.

### Execution-plan identity

How work was physically arranged: workers, chunks, locality, device assignment, accelerator layout.

### Benchmark receipt

Performance observations such as elapsed time, throughput, OpenAI turns, token use, cache-hit rate, and device observations.

Correctness identity should be independent of worker/chunk/device assignment where those choices do not alter semantics.

Rejected/partial executions may be persisted as evidence, but cannot be relabelled accepted without satisfying the acceptance contract.

v0.4 implements each class as a distinct immutable canonical record with a
separate semantic-identity domain and receipt-identity domain. Final acceptance
binds the validated task, governance, orchestration, execution, and compact
evidence records plus the exact gate-result set. It excludes execution-plan,
benchmark, fast-fold, wall-clock, and device fields. Canonical hashes prove
record integrity; finalization separately requires a live chain bound by
non-constructible native seals. Those in-process seals are not signatures,
remote attestation, or producer authentication.

---

## 10. Compact Evidence Plane

The evidence plane reduces large bounded deterministic workloads without
turning resident execution state into routine model/host transport:

```text
canonical case/runtime receipts
        |
        v
opaque checked streaming reducer
        |
        v
fixed-ceiling compact receipt
        |
        v
governance scope validation
```

For the declared v1 profile, successful per-case records are not retained. The
receipt carries exact counts; ordered SHA-256 admission, input, result, and
runtime-receipt aggregates; the bounded governed authorization-manifest
identity/count; initial/final receipt and state continuity for one runtime
session; bounded failure-locator metadata; and separately bound
task/governance/orchestration/execution identities. Its 2,048-byte ceiling does
not grow with admitted case count. Failures may retain only a declared bounded
detail prefix, exposed only through a parent-bound bounded expansion request.

Structural receipt/SHA validation establishes canonical consistency, not
producer authentication or external truth. Final governance additionally
requires a live source-bound direct-case reducer result whose roots, manifest,
runtime boundary, and counts agree with the execution receipt. Every sealed
runtime case is checked against the governed manifest before reducer mutation.
Cache-hit receipts additionally require the manifest's exact cache-reuse
permission. A sealed `record_retry` for a known admission may preserve exact
accounting and session/state continuity between reads, but it does not establish
execute-read coverage for that admission.
The first accepted evidence receipt for each action must be cold before its
hits are admitted, preventing the frozen v0.3 cache key from carrying authority
across distinct same-name capability contracts.
A separate optional non-cryptographic fold has
`correctness_authority: false` and is absent from every correctness identity.

Live child receipts can be validated before deterministic bounded parent
composition. The initial child transport root is grouping-sensitive, so child
composition is not admitted into v0.4 final correctness identity. A future
versioned indexed/range-proof profile is required before arbitrary chunking can
claim plan-neutral final evidence. This is an explicit partial hierarchical
contract, not distributed execution.

The engineering pattern is independently derived from the bounded evidence
reduction described by QEC/VE-24. QEC/VE-24 implementation code, GPU kernels,
geometry, constants, assets, and domain/physical claims are not incorporated.

---

## 11. Donor patterns from IGM and GLUBALL

IGM and GLUBALL contribute engineering patterns, not ontology.

Useful IGM donor patterns:

- exact execution addressing;
- bounded memory/chunk planning;
- worker/chunk-independent correctness identity;
- explicit separation between correctness and benchmark timing;
- reference implementation authority before accelerator authority;
- accelerator-friendly 30-meaningful/32-wide layout experiments.

Useful GLUBALL donor patterns:

- exact integer logical sampling;
- deterministic partitions;
- very large logical spaces without proportional allocation;
- canonical receipts.

Permanent boundary:

> **Execution adjacency does not imply orchestration meaning.**

A `C5 x K2 x C3` graph, CRT address, toroidal geometry, 30/32 warp mapping, or sampling rule is an optional scheduler/execution representation until an IBAE-specific contract and benchmark justify it.

The current preferred GPU experiment keeps two padding lanes inactive and metadata in a sidecar. Turning padding lanes into semantic metadata is not assumed.

---

## 12. CPU and accelerator authority

Accelerator implementation comes only after Python/Rust semantics are frozen and benchmarked.

```text
Python semantic reference
        |
        v
Rust CPU authority
        |
        v
GPU/SIMD candidate
        |
        v
conformance/residual gate
```

Governance-critical fields use exact integer/enumerated representations. `f32`/`f64` may be used for declared numerical or heuristic accelerator fields but cannot solely govern provider authority, budgets, logical ticks, command identity, or acceptance.

Initial GPU work should run locally on an available NVIDIA RTX-class device. Wider infrastructure such as Vast.ai is for cross-device reproducibility after a reference conformance gate exists, not a substitute for that gate.

A fast result is not a more correct result.

---

## 13. Modular extension rule

Future features must attach through explicit module/protocol boundaries rather than forcing core rewrites.

Potential Python-side modules:

```text
governance/
orchestration/
progress/
openai/
workers/
protocol/
benchmarks/
```

Potential Rust-side modules:

```text
state
budget
canonical
cache
cycle
clock
receipt
runtime
evidence
cpu
future accelerator adapters
```

Optional features such as GPU scheduling geometry, local workers, alternative orchestration strategies, distributed caches, or formal proofs must preserve the core layer/identity invariants.

---

## 14. Current implementation boundary

The merged v0.1 Python kernel implements the deterministic execution foundation: canonicalization, observation reuse, finite request/execution/retry/history bounds, short-cycle detection, and provider policy.

The v0.2 Python reference implements deterministic orchestration semantics for:

- stable obligation identities and validated dependency DAGs;
- canonical ready sets, canonical ordering for independent reads, and preserved declared sequencing for effectful batches;
- model proposal versus admitted-action separation;
- orchestrator-owned replay classification;
- within-batch deduplication only for replay-safe actions;
- distinct bounded occurrence identity/ownership for mutations and non-idempotent effects, persisted across batches;
- explicit epistemic state classes and dependency-bound state identity;
- semantic epistemic identity that excludes fresh-versus-cache delivery metadata and unadmitted model-proposed values while preserving both in the AI projection;
- strategy-specific, typed, finite parameter allowlists stored in admitted orchestration state and bound into strategy identity, with schema drift returned as a structured batch rejection;
- capability-owned finite semantic argument-key allowlists, with observational proposal metadata retained for the agent but excluded from correctness identity and replay-safe deduplication;
- bounded proposal/state/history/occurrence containers, with bounded consumption at every model-facing iterable boundary, incrementally measured free text, bounded identity integers, and bounded canonical-value traversal before serialization;
- canonical rejection codes (including strategy/argument policy drift), recovery actions, compact state projection, and logical orchestration ticks;
- byte-stable, model-free conformance fixtures.

v0.2 remains the Python orchestration semantic reference. It constructs/admits
actions but does not grant continuation leases or call models. v0.4 wraps its
admission receipt rather than moving orchestration intelligence into governance
or Rust.

The accepted v0.3 runtime moves the already admitted v0.1 cacheable-read
execution semantics below Python. Rust owns exact counters, logical execution
ticks, canonical cache/history, cycle detection, and runtime receipts. Python
can request only versioned transitions and receives mutation-isolated
observation/snapshot copies. The Rust crate has no network or model-provider
dependency. The retained Python executor is conformance evidence, not an
alternate production authority.

The v0.4 candidate implements the deterministic governance policy/receipt
surface, separate task/governance/orchestration/execution/plan/benchmark/final
identities, immutable rejection/partial receipts, and the bounded Compact
Evidence Plane. Governed tool admissions are bound to v0.2 action identities;
the finalizable v1 execution path additionally requires live sealed v0.3
`execute_read` receipts matching the bounded authorization manifest; sealed
`record_retry` receipts may appear only as exact known-admission accounting
transitions and cannot cover a manifest action on their own. The
wrapper may classify effect permissions, but v0.4 does not execute a mutation
or volatile read. It does not authenticate a producer, call a model, or grant a
continuation lease. The exact v0.2 and v0.3 fixtures remain
frozen compatibility evidence.

The logical lease system, live OpenAI adapter, GPU path, distributed execution,
and local workers remain **later architecture targets, not current
implementation claims**. They remain blocked until the exact v0.4 head passes
CI, determinism, compact-evidence stress, and fresh review.
