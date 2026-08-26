# IBAE Progress and Bounded Continuation Protocol v1

Status: v0.5 implementation candidate. The v0.1-v0.4 accepted contracts and
their checked-in fixture bytes remain unchanged.

This document defines the implemented objective-progress, finite continuation,
strategy-change, checkpoint, compact continuation-evidence, and semantic
partial-finalization contracts. It is an in-process deterministic protocol, not
a model-provider adapter, RPC protocol, durable attestation format, or mutation
execution surface.

## Authority boundary

The authority path is intentionally one way:

```text
OpenAI supervisor requests
        -> deterministic governance grants or denies
        -> Rust runtime applies an exact granted vector
        -> orchestration observes the resulting native state
```

- The supervisor may request a lease but cannot grant one.
- Governance owns the continuation policy and every grant/deny decision.
- Orchestration owns objective progress and structured strategy semantics.
- Rust owns runtime limits, counters, logical ticks, and lease application.
- A runtime, tool backend, scheduler, or future worker cannot request or grant
  itself authority.
- Benchmark and wall-clock observations have no correctness authority.

A request is not a grant. A grant is not applied runtime capacity. An applied
lease is not evidence of task progress. A strategy change may justify one
bounded recovery attempt, but is not itself progress.

## Versioned records

| Record | Protocol version |
|---|---|
| Continuation policy, request, and state | `IBAE-CONTINUATION-LEASE-V1` |
| Policy/governance binding | `IBAE-CONTINUATION-POLICY-RECEIPT-V1` |
| Objective progress | `IBAE-OBJECTIVE-PROGRESS-V1` |
| Strategy change | `IBAE-STRATEGY-CHANGE-V1` |
| Runtime cycle evidence | `IBAE-CYCLE-EVIDENCE-V1` |
| Governance grant | `IBAE-CONTINUATION-LEASE-GRANT-V1` |
| Governance denial | `IBAE-CONTINUATION-LEASE-DENY-V1` |
| Rust lease application | `IBAE-RUNTIME-LEASE-APPLICATION-RECEIPT-V1` |
| Continuation checkpoint | `IBAE-CONTINUATION-CHECKPOINT-V1` |
| Compact continuation evidence | `IBAE-CONTINUATION-EVIDENCE-V1` |
| Semantic partial finalization | `IBAE-CONTINUATION-PARTIAL-V1` |
| Watchdog observation | `IBAE-WATCHDOG-OBSERVATION-V1` |

Every identity-bearing class has a distinct SHA-256 domain. Grant identity and
grant-receipt identity are separate; the same is true for denial, Rust lease
application, checkpoint, progress, strategy change, evidence, partial, and
watchdog records.

## Objective progress

`ProgressMeasureContract` declares a finite ordered set of exact integer
dimensions. Each dimension declares a direction (`increase` or `decrease`), a
source, and an optional completion threshold. Implemented sources are:

- unsatisfied-obligation count;
- blocked-obligation count;
- satisfied-obligation count;
- a governed external counter.

Governed external counters accept only `observed` or `derived` epistemic
evidence bound to the task, governance identity, dimension, basis identity,
and evidence identity. Model-proposed values cannot enter the progress
measure.

Canonical obligation sources have fixed safe directions: unsatisfied and
blocked counts may only decrease, and satisfied counts may only increase. The
continuation policy and its governance receipt commit the exact admitted
`ProgressMeasureContract` identity; a record from any other contract is stale
for that continuation ledger.

Prior and current obligation counters are comparable only when their complete
obligation-definition identity is equal. The definition identity includes
obligation key, description, stable ID, and dependencies. Adding or changing an
obligation therefore becomes `new_information`, not an automatic regression.

The closed progress classifications are:

| Classification | Deterministic meaning |
|---|---|
| `measurable_progress` | At least one declared measure improved and none regressed. |
| `no_progress` | All comparable known declared measures are unchanged. |
| `regression` | At least one declared measure regressed and none improved. |
| `new_information` | Knownness or comparison basis changed. |
| `incomparable` | The same comparison contains both improvement and regression. |

Task completion is computed separately. It requires every current obligation
to be satisfied and every declared completion threshold to hold. Activity
count, tool-call count, token count, elapsed time, and model confidence do not
participate.

The version-1 continuation profiles admit only `measurable_progress`. Missing,
new, incomparable, regressed, or unchanged evidence cannot independently
authorize a lease.

## Strategy materiality and cycles

`StrategyMaterialization` binds:

- the admitted typed v0.2 strategy identity;
- the available capability frontier;
- target obligation IDs;
- an ordered dependency path;
- recovery mode; and
- an optional ordered initial transition pattern.

Human-readable strategy description is validated for presentation but omitted
from correctness identity and admissibility. Rephrasing a description cannot
manufacture a new strategy.

A proposed strategy change is admitted only when all of the following hold:

- its v0.2 strategy identity differs from the prior identity;
- its structured semantic material differs;
- its schema is the active admitted schema;
- every named capability exists and is available;
- at least one target obligation is bound;
- every target obligation exists; and
- when cycle evidence exists, its proposed transition pattern does not
  reproduce the detected period-1, period-2, or period-3 cycle.

Cycle evidence is recomputed from native bounded transition history. Cold
execution and cache-hit paths use the same transition identity, so reuse cannot
hide a periodic loop. A cycle blocks continuation unless the exact request
binds an admitted cycle-breaking strategy receipt. Strategy recovery count is
finite and precommitted by policy.

## Finite continuation policy

The exact resource vector is:

```text
request_delta
execution_delta
retry_delta
mutation_delta
history_delta
```

All values are exact unsigned 64-bit integers with checked addition and
subtraction. Mutation is represented so the resource class cannot disappear
silently, but v0.5 requires every mutation delta to be zero because no mutation
execution command exists.

A policy precommits:

- an initial runtime budget;
- an ordered finite lease schedule;
- a total ceiling exactly equal to the initial budget plus the full schedule;
- a finite maximum request count;
- the exact admitted progress-contract identity;
- the admitted progress classes; and
- a finite maximum strategy-recovery count.

The hard protocol limits are 64 scheduled leases and 128 lease requests. Every
resource ceiling must also fit the Rust runtime hard caps. A requested vector
may be smaller than its indexed scheduled vector, but cannot exceed it in any
component. Cumulative grants cannot exceed the precommitted continuation
capacity or total ceiling.

### Experimental named profiles

Vector notation below is `requests / executions / retries / mutations /
history`.

| Profile v1 | Initial budget | Ordered lease schedule | Total ceiling | Request cap |
|---|---:|---:|---:|---:|
| `tiny` | `8/4/2/0/8` | `4/2/1/0/4` | `12/6/3/0/12` | 2 |
| `standard` | `32/16/4/0/32` | `16/8/2/0/16`, `8/4/1/0/8` | `56/28/7/0/56` | 4 |
| `extended` | `64/32/8/0/64` | `32/16/4/0/32`, `16/8/2/0/16`, `8/4/1/0/8` | `120/60/15/0/120` | 6 |
| `repository` | `128/64/16/0/128` | `64/32/8/0/64`, `32/16/4/0/32`, `16/8/2/0/16` | `240/120/30/0/240` | 6 |

These are exact versioned experimental fixtures, not universal or optimal
budgets. Changing any value changes policy/profile identity. Benchmark results
cannot recalibrate a live policy.

## Deterministic grant/deny transition

For one exact continuation state, request, policy receipt, progress record,
strategy receipt, cycle evidence, and blocking-governance input, decision order
is deterministic and fail closed. It checks, in order:

1. state, task, governance, policy, orchestration, runtime, and progress
   lineage, including the policy-bound contract and exact live progress-ledger
   endpoint;
2. supervisor requester authority;
3. absence of a pending unapplied grant;
4. incomplete task and absence of a blocking governance violation;
5. request-count, lease-index, lease-count, and cumulative ceilings;
6. cycle/strategy receipt binding and materiality;
7. admitted objective progress or a remaining strategy recovery;
8. non-empty, mutation-free, scheduled resource bounds; and
9. checked cumulative arithmetic against the precommitted ceiling.

The closed denial taxonomy includes unauthorized requester, stale lineage,
pending application, complete task, governance violation, request or lease
ceiling, wrong index, terminal cycle, no measurable progress, nonmaterial or
cycle-equivalent strategy, exhausted strategy recovery, empty/unsupported
resources, and schedule/ceiling overflow.

Each admitted request decision consumes one continuation request and advances
the continuation logical tick once, whether granted or denied. After the
precommitted request cap has been reached, another request returns a stable
request-limit denial without advancing state, tick, or counters. This prevents
denial spam from becoming unbounded retained authority state.

A grant advances governance continuation state and creates one pending grant.
It does not itself change native runtime limits or consume runtime request,
execution, retry, mutation, cache-hit, or history resources. No second request
can be admitted while a grant remains pending.

## Rust lease application

`apply_lease` is accepted only by an opt-in continuation-enabled native
session. Rust independently parses the full canonical governance grant and
recomputes both grant and receipt identities. Governance evaluation attaches a
non-serialized, non-constructible native capability for that exact canonical
grant, native session, and prior runtime state. Rust refuses a hash-consistent
but unissued grant. It then validates:

- task, governance, governance receipt, policy, and policy receipt bindings;
- native session and exact prior runtime state;
- exact next lease index and duplicate/replay exclusion;
- the precommitted indexed schedule;
- cumulative grant and total ceiling;
- zero mutation authority; and
- checked limit and logical-tick arithmetic.

Accepted application has this exact accounting quantum:

| Effect | Delta |
|---|---:|
| Runtime logical tick | 1 |
| Request counter | 0 |
| Execution counter | 0 |
| Cache-hit counter | 0 |
| Retry counter | 0 |
| Mutation counter | 0 |
| Execution history | 0 |
| Runtime limits | Exact granted vector |

Rejected application is state-, tick-, limit-, and resource-neutral. Its
closed reasons cover disabled continuation, forged grant identity, stale
policy/governance/runtime state, wrong or replayed index, schedule/ceiling
violation, unsupported resource, unissued grant, and arithmetic overflow.

The Rust application receipt is a separate execution-authority record. The
grant capability is consumed only as an in-process application prerequisite
and is not serialized. The application receipt itself deliberately has no v0.3
native source seal: the supported checkpoint scope is in-process structural
lineage, not durable producer authentication or remote attestation.

Python may commit an accepted application into continuation lineage only after
matching every task/governance/policy/session/grant/index/cumulative/ceiling
field, the exact native applied-grant ledger, the resulting runtime state, and
the resulting exact limits.

## Runtime compatibility

Continuation is opt-in at native session construction and requires an exact
policy/receipt pair. For a legacy session:

- the runtime session identity is unchanged;
- the snapshot schema and state identity are unchanged;
- the v0.3 runtime receipt schema is unchanged; and
- `apply_lease` rejects without mutation.

For an opted-in session, the session/state identity additionally binds task,
governance receipt, continuation policy/receipt, admitted progress contract,
initial budget, full schedule, total ceiling, cumulative grants, applied grant
IDs, and the next lease index. Existing v0.2-v0.4 conformance bytes remain
frozen.

## Continuation state and compact projection

`ContinuationState` is one task/session ledger. Its identity includes exact
task/governance/policy/progress-contract/orchestration/runtime lineage,
request/grant/denial counts, cumulative grants, decision aggregate, bounded
decision receipt IDs, strategy recovery count, progress state, pending
application, and continuation logical tick. Advancing orchestration state
requires a progress record whose prior endpoint is the ledger's current state;
lease requests must reuse the exact last committed progress identity.

The compact AI projection exposes exact remaining leases and total continuation
capacity, the last progress/decision/denial state, pending-application state,
and legal deterministic recovery actions. It is an observation of authority
state, not authority to alter that state.

## Checkpoint and resume scope

`IBAE-CONTINUATION-CHECKPOINT-V1` binds task and governance receipts,
orchestration and native session/state identities, policy, progress contract,
and continuation state, the exact live progress endpoint and strategy
identities, lease and strategy-recovery ledgers, optional compact
evidence/relevant receipt IDs, all three logical ticks, status, and optional
partial reason.

Resume reconstructs the expected checkpoint from the exact live in-process
objects and requires byte-equivalent canonical content and checkpoint identity.
Stale orchestration, runtime, progress, strategy, policy, or continuation state
fails closed.

The v1 checkpoint does not provide:

- producer authentication or signatures;
- remote or durable attestation;
- a `from_record` authority-reconstruction path;
- cross-process reconstruction of opaque Rust runtime state; or
- authority to merge independent/forked lineages.

It is explicitly `structural-in-process-lineage-only`. A future durable resume
contract must be separately versioned and cannot weaken the native trust model.

## Compact continuation evidence

`IBAE-CONTINUATION-EVIDENCE-V1` is separate from the frozen
`IBAE-COMPACT-EVIDENCE-V1` receipt. It retains fixed aggregate state:

- progress-event count and ordered progress aggregate;
- lease request/grant/deny counts;
- final lease index and continuation status;
- decision aggregate and final decision receipt identity; and
- optional binding to a v0.4 compact execution-evidence receipt.

It retains no successful per-progress trace and is capped at 4,096 canonical
UTF-8 bytes. This preserves `execution state != evidence transport` and does
not alter the v0.4 evidence schema or identity.

Construction nevertheless validates the supplied bounded trace before folding
it: every record must use the policy-bound progress contract, adjacent
orchestration endpoints must be contiguous, and the final progress and
orchestration endpoints must equal the live continuation ledger.

## Partial finalization and watchdogs

`IBAE-CONTINUATION-PARTIAL-V1` is a semantic continuation partial, separate
from v0.4 structural missing-receipt/gate partial records. Closed reasons are:

- `lease_ceiling_exhausted`;
- `no_progress`;
- `terminal_cycle`;
- `strategy_recovery_exhausted`; and
- `watchdog_expired`.

Reason, continuation status, exact last denial, and relevant exhausted
lease/recovery counter must agree. Every partial binds its checkpoint,
continuation state, decision aggregate, and optional execution/compact evidence
receipts. It always has `status = partial` and `task_complete = false`; a
complete continuation state cannot be relabelled partial, and a partial cannot
be relabelled accepted.

A watchdog expiry requires a bound `WatchdogObservation`. Elapsed milliseconds
are retained as an observation but excluded from watchdog correctness identity.
The observation always has `correctness_authority = false` and
`task_complete = false`. Its `lease_exhausted` flag must match independent
continuation state, and its task, governance, orchestration, runtime, and
continuation identities must match the exact partial state; elapsed time cannot
manufacture lease exhaustion or normal completion.

## Benchmark-only policy experiment

`IBAE-BUDGET-PROFILE-BENCHMARK-V1` is deterministic and model-free. It compares
fixed-equal, front-loaded, geometric-candidate, and small-base/larger-recovery
schedules across short success, genuinely progressing work, activity without
progress, periodic loops, material recovery, strategy paraphrase, cache-heavy,
retry-heavy, and ceiling-exhaustion scenarios.

The report records base/lease resources, unused capacity, progress and strategy
events, cycle/no-progress denials, outcome, and partial reason. It explicitly
sets `benchmark_only = true`, `correctness_authority = false`, and
`wall_clock_in_correctness_identity = false`. It emits no winner or universal
recommendation.

## Current non-goals

v0.5 does not add a live OpenAI call, mutation/effect execution, worker
protocol, GPU path, distributed runtime, cross-process checkpoint
reconstruction, producer authentication, universal budget calibration, or any
v0.6 supervisor transport.

## Conformance evidence

The checked-in v0.5 fixtures are:

- `fixtures/v0.5/progress-continuation-reference.json`;
- `fixtures/v0.5/budget-profile-benchmark.json`.

CI renders both across distinct `PYTHONHASHSEED` values and byte-compares them.
The legacy v0.2, v0.3, and v0.4 fixtures are rendered and compared separately
to prove compatibility.
