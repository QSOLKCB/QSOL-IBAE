# Governance Protocol

Status: v0.4 implementation contract.

This document defines the deterministic governance surface implemented above
the accepted v0.2 orchestration and v0.3 Rust runtime. It does not define a
model-provider adapter, continuation lease, worker protocol, or remote service.

## Authority boundary

```text
future OpenAI supervisor
        |
        v
Python GovernanceWrapper
        |
        v
Python deterministic orchestration
        |
        v
Rust deterministic runtime
```

Only `openai` is a valid proprietary remote-provider authority. The closed
principal classes are OpenAI supervisor, future local candidate worker,
deterministic orchestrator, and Rust execution runtime. Merely naming a class
does not grant it another class's authority. In v0.4 only the supervisor admits
a task or requests finalization, and only the deterministic orchestrator admits
a governed tool action.

No live OpenAI call or local-worker adapter exists in this phase. The provider
and worker records enforce the deterministic policy boundary; they are not a
claim that the later integrations are complete.

## Tool authority

Every governed tool permission declares all of these fields explicitly:

- tool name;
- one of `pure_read`, `snapshot_read`, `volatile_read`,
  `idempotent_mutation`, or `non_idempotent_mutation`;
- whether mutation is allowed;
- whether cache reuse is allowed.

Omission is not permission. Reads cannot acquire mutation authority. Volatile
reads and mutations cannot enter the observation cache. Every governed action
requires the exact v0.2 dependency-state fingerprint, including the canonical
empty-state fingerprint when its declared dependency-key set is empty;
snapshot reads therefore bind their declared dependency state rather than an
implicit default. Volatile reads and all mutation classes require occurrence
identity in the implemented conservative v1 profile, so equal
payloads do not collapse. A later replay-safe mutation exception would require
an explicit versioned contract and proof; it is not inferred from the word
"idempotent." These governance classes supplement rather than replace the
accepted v0.2 capability/replay contract and v0.3 read-admission checks.

A tool-admission receipt policy-authorizes one exact v0.2 action identity. It
binds the typed admitted decision, proposal, and capability; recomputes the
v0.2 action ID from canonical arguments, capability, dependency state, and any
required occurrence; and binds the governed tool/class, replay policy,
permission, and governance context. The orchestration receipt requires exact
bounded coverage: one valid tool admission for every unique admitted action,
with no extras or duplicates, and every deduplication must point to an earlier
admitted proposal with the same action identity. A domain-separated
authorization-manifest identity and exact count commit to at most 256 resulting
action-to-permission bindings.

The current Rust command family can execute only cacheable reads. Consequently
only governed `pure_read` and `snapshot_read` entries can enter a finalizable
v0.4 execution, and every sealed read receipt must match its manifest entry's
action ID, tool name, arguments ID, dependency identity, `execute_read` command
class, and exact cache-reuse permission. Sealed `record_retry` receipts may
contribute exact known-admission accounting and continuity, but cannot satisfy
manifest action coverage alone. `volatile_read` and mutation permissions are
deterministic, fail-closed governance records in this phase; they do not
fabricate a Rust effect-execution path.

The accepted v0.1/v0.3 cache key omits the v0.2 admission/capability identity.
Therefore v0.4 evidence admits a cache hit only after an accepted cold receipt
for that exact governed action in the same continuous stream. Distinct governed
actions that collide on the same runtime cache tuple fail closed rather than
sharing authority through the cache.

## Policy and task admission

`IBAE-GOVERNANCE-PROTOCOL-V1` policy records bind a policy key/version, provider
authority, task profile/version, exact tool permissions, and an exact sorted
acceptance-gate set. The implemented profile requires exactly these three
gates:

```text
compact_evidence_valid
orchestration_receipt_valid
execution_receipt_valid
```

Unknown fields, missing booleans, unknown authority, extra/missing gates,
duplicate values, and non-canonical values fail closed.

A task receipt binds the task key, task contract version, canonical acceptance
contract, and exact required gates. A governance receipt binds that task to the
active policy and supervisor authority.

## Identity taxonomy

The following semantic identities are separate and domain-separated:

- task;
- governance;
- governed tool classification;
- orchestration correctness;
- execution correctness;
- execution plan;
- benchmark observation;
- final acceptance.

Each receipt also has its own receipt-ID domain. Equal raw payloads in different
classes therefore cannot alias. Execution-plan and benchmark receipts carry
`correctness_authority: false` and are excluded from final correctness identity.
Wall-clock time, throughput, worker count, device placement, and scheduling
choices are not final-acceptance inputs.

## Receipt chain

The implemented versioned records are:

```text
IBAE-TASK-RECEIPT-V1
IBAE-GOVERNANCE-RECEIPT-V1
IBAE-TOOL-ADMISSION-RECEIPT-V1
IBAE-ORCHESTRATION-RECEIPT-V1
IBAE-EXECUTION-RECEIPT-V1
IBAE-EXECUTION-PLAN-RECEIPT-V1
IBAE-BENCHMARK-RECEIPT-V1
IBAE-FINAL-ACCEPTANCE-RECEIPT-V1
IBAE-REJECTION-RECEIPT-V1
IBAE-PARTIAL-RECEIPT-V1
```

The orchestration receipt wraps an accepted v0.2 admission receipt and the
bounded governed authorization manifest described above. The fixed-shape
execution receipt binds that governed orchestration; the manifest identity and
count; the first and last typed, accepted v0.3 runtime receipts; one continuous
runtime session and its initial/final states; the exact transition count; and
ordered streaming aggregate identities for admissions, inputs, results, and
runtime receipts. It does not retain an O(N) list of transition receipts.

Final acceptance requires the exact task/governance/orchestration/execution
chain, the exact closed gate set with each gate bound to its corresponding
receipt ID, and a `complete_no_failures` compact-evidence receipt whose
manifest, roots, runtime boundary, and counts agree with the execution receipt,
plus OpenAI-supervisor authority. Missing chain elements or unsatisfied gates
produce immutable
partial receipts. Invalid authority or malformed bindings produce immutable
rejection receipts. Neither can be mutated or relabelled accepted; a later
successful attempt creates a new receipt.

## Validation and trust scope

`ReceiptValidator` independently reconstructs the expected canonical record for
each v0.4 receipt class and rejects unknown fields, unknown enum values, wrong
bindings, and identity mismatches. Compact-evidence parsing separately validates
its exact schema and SHA-256 identity.

These checks establish deterministic contract consistency, not producer
authentication. A self-consistent serialized runtime, summary, or compact
receipt is structural-only and cannot finalize a task. The implemented path
additionally requires non-constructible native seals for each exact live runtime
receipt, the aggregate summary, and the finalized compact receipt. Governance
matches the sealed manifest, aggregates, counts, and session/state boundary to
the typed receipt chain. Those in-process seals still are not signatures,
remote attestation, durable provenance, or proof of external truth.

## Deferred

v0.4 does not implement continuation leases, Responses/Agents SDK calls, local
workers, distributed execution, GPU/SIMD execution, or performance authority.
Those remain subject to their later roadmap gates.
