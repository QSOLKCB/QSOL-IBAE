# QSOL-IBAE Architecture

Status: frozen architecture contract with v0.2 Python orchestration reference.

QSOL-IBAE is a small OpenAI-exclusive governed execution substrate, not a general-purpose proprietary multi-provider agent framework.

The architecture is designed around one principle:

> **Use model intelligence for reasoning. Use deterministic software for bookkeeping, admission, boundedness, reuse, and execution evidence.**

See `INVARIANTS.md` for normative invariant IDs and `ROADMAP.md` for implementation order.

---

## 1. Authority layers

QSOL-IBAE separates three active layers and one observational layer:

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

The intended modular implementation split is:

### Python logic core

Python owns change-friendly semantic logic:

- governance configuration and policy composition;
- task/obligation construction;
- deterministic orchestration reference semantics;
- progress predicates and strategy representation;
- AI-facing compact state projection;
- OpenAI API/SDK integration;
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

The initial bridge should be in-process and narrow, likely PyO3 + maturin. RPC/daemon/distributed infrastructure is deferred.

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
Python orchestration update
```

Python must not mutate authoritative Rust runtime state directly.

The Rust runtime must not directly call OpenAI or another model provider.

---

## 4. Versioned narrow protocol

The Python/Rust and agent-facing surfaces should remain small enough to audit completely.

Candidate runtime command family:

```text
ADMIT
EXECUTE
RECORD_OBSERVATION
RECORD_RETRY
REQUEST_LEASE
FINALIZE
```

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

These names are architecture candidates until frozen, but the principle is normative: arbitrary implementation internals must not leak into the authority surface.

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

---

## 10. Donor patterns from IGM and GLUBALL

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

## 11. CPU and accelerator authority

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

## 12. Modular extension rule

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
cpu
future accelerator adapters
```

Optional features such as GPU scheduling geometry, local workers, alternative orchestration strategies, distributed caches, or formal proofs must preserve the core layer/identity invariants.

---

## 13. Current implementation boundary

The merged v0.1 Python kernel implements the deterministic execution foundation: canonicalization, observation reuse, finite request/execution/retry/history bounds, short-cycle detection, and provider policy.

The v0.2 Python reference implements deterministic orchestration semantics for:

- stable obligation identities and validated dependency DAGs;
- canonical ready sets and proposal ordering;
- model proposal versus admitted-action separation;
- orchestrator-owned replay classification;
- within-batch deduplication only for replay-safe actions;
- distinct occurrence identity for mutations/non-idempotent effects;
- explicit epistemic state classes and dependency-bound state identity;
- bounded proposal/state/history containers;
- canonical rejection codes, recovery actions, compact state projection, and logical orchestration ticks;
- byte-stable, model-free conformance fixtures.

v0.2 remains a Python semantic reference. It does not execute admitted actions, grant continuation leases, own governance receipts, call models, or provide a Rust authority boundary.

The governance wrapper, logical lease system, Rust runtime, OpenAI adapter, GPU path, and local workers described elsewhere are **later architecture targets, not current implementation claims**. The v0.3 Rust phase must not begin until the v0.2 conformance gate is accepted.
