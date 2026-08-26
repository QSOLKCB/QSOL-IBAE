# QSOL-IBAE Roadmap

Status: v0.4 governance, identity receipts, and Compact Evidence Plane accepted and merged. The current implementation frontier is v0.5 Progress and Bounded Continuation.

Current accepted main lineage:

- PR #1: v0.1 Deterministic Execution Kernel
- PR #2: architecture-contract freeze
- PR #3: v0.2 Deterministic Python Orchestration Reference
- PR #4: v0.3 Rust Deterministic Runtime
- PR #5: v0.4 Governance Wrapper, Identity Receipts, and Compact Evidence Plane
- Current accepted `main` merge commit after PR #5: `849b188fcc826184e3afa2617dd1362b475a4cd3`

QSOL-IBAE is intentionally developed invariant-first. Each authority-bearing phase is blocked on the acceptance gate of the preceding phase. The project is not intended to become a generic multi-provider agent framework. It is an OpenAI-exclusive governed execution substrate whose purpose is to reduce redundant work, make continuation finite and auditable, preserve deterministic execution semantics, minimize unnecessary context and evidence transport, and move deterministic bookkeeping out of the model's cognitive workload.

This roadmap is ordered by semantic and authority risk, not demo appeal.

---

# 1. Core architectural thesis

```text
                         USER
                           |
                           v
                 OPENAI SUPERVISOR
                  future live source
                           |
                           v
                SUPERVISOR ADAPTER
                           |
                           v
+----------------------------------------------------------------+
|                     GOVERNANCE WRAPPER                         |
| provider policy | authority | budgets | revocation | profiles  |
| tool permissions | receipts | assurance | fail-closed          |
|                                                                |
|   +--------------------------------------------------------+   |
|   |            DETERMINISTIC ORCHESTRATION                |   |
|   | obligations | DAG | admission | dedup | progress      |   |
|   | strategy | continuation | control state | compact AI   |   |
|   |                                                        |   |
|   |   +------------------------------------------------+   |   |
|   |   |            RUST EXECUTION RUNTIME             |   |   |
|   |   | exact counters | cache | logical clock        |   |   |
|   |   | cycles | runtime state | receipts             |   |   |
|   |   +------------------------+-----------------------+   |   |
|   |                            |                           |   |
|   |                            v                           |   |
|   |   +------------------------------------------------+   |   |
|   |   |            COMPACT EVIDENCE PLANE            |   |   |
|   |   | exact aggregates | bounded transport         |   |   |
|   |   | selective expansion | audit identities       |   |   |
|   |   | optional fast diagnostic fingerprints        |   |   |
|   |   +------------------------------------------------+   |   |
|   +--------------------------------------------------------+   |
+----------------------------------------------------------------+
                           |
                           v
                 FINAL / PARTIAL RECEIPT

Benchmark and performance observations remain outside correctness authority.
```

Implementation split:

```text
Python logic core
    governance policy
    orchestration semantics
    progress / continuation decisions
    task and obligation construction
    supervisor protocol
    control classifications
    AI-facing compact state
    OpenAI integration
    future worker adapters

        | narrow versioned protocol
        v

Rust authority runtime
    exact runtime transitions
    exact integer accounting
    logical execution clock
    canonical runtime identity
    cache and cycle machinery
    continuation application
    compact evidence reduction
    deterministic CPU authority
    future accelerator adapters
```

Guiding rule:

> Python decides what should be attempted. Rust proves what was admitted and executed.

The Rust runtime must not directly own model-provider integration.

---

# 2. Permanent non-promotion boundaries

The following boundaries are architectural, not stylistic:

```text
governance != orchestration != execution != benchmark
execution state != evidence transport
proposal != admission
capability != authority
data != control
model claim != observation
research claim != operational calibration
reported threshold != validated threshold
checksum match != semantic truth
compact projection != full-state reconstruction
simulation transport != extra authority
live transport != semantic authority
fast diagnostic fingerprint != cryptographic receipt
sampled evidence != exhaustive correctness
activity != progress
strategy change != progress
receipt integrity != producer authenticity
```

Lower layers cannot promote themselves upward.

Examples:

- tool availability does not grant permission to invoke the tool;
- remaining lease capacity does not grant authority to extend execution;
- a worker result does not become supervisor truth merely by being returned;
- a benchmark result does not become correctness evidence by being fast;
- a model statement that work is complete does not satisfy acceptance gates;
- a repository file containing imperative text does not become governance instruction;
- a compact receipt proves only the claims declared by its evidence profile;
- a deterministic hash proves record identity/integrity, not external truth;
- a synthetic adapter and a live adapter must enter the same normalized authority surface;
- a non-cryptographic fast fold may locate likely divergence but cannot authorize final acceptance;
- a published or externally archived numeric value cannot silently become an IBAE policy threshold;
- a missing measurement is `unknown` or `unavailable`, never silently zero;
- discovering more failures can be new information rather than automatic negative progress;
- selecting an intervention does not prove that the intervention succeeded.

---

# 3. Donor-design boundary

QSOL-IBAE may borrow independently reimplemented engineering patterns from other QSOLKCB projects, but it does not inherit their ontology or whole architecture.

Every donor idea must pass this filter:

```text
1. What exact invariant or efficiency problem does it solve?
2. What assumptions does the donor implementation rely on?
3. Can those assumptions be stated explicitly in IBAE?
4. Can the pattern be independently reimplemented under QSOL-IBAE licensing?
5. Does it preserve governance/orchestration/execution separation?
6. Does it avoid promoting heuristics, benchmarks, or research claims into correctness?
7. Is there a simpler baseline that should be benchmarked first?
```

## 3.1 UFT-ID 3.0 donor concepts

Scholarly archive DOI: `10.5281/zenodo.22108865`

Useful donor concepts:

- observational equivalence and observation-induced state classes;
- quotient/image reasoning for compact projections;
- reconstruction limits for non-injective observations;
- exact uniform floor sampling as a future bounded-sampling candidate;
- immutable source authority separate from later formalization layers;
- explicit claim boundaries between proof, implementation, reproducibility, and empirical truth;
- verifier distrust of self-reported manifests;
- exact frozen-source versus later-proof provenance;
- deterministic archive/rebuild discipline.

Do not import UFT-ID scientific ontology or physical claims into IBAE.

## 3.2 QEC donor concepts

Useful donor concepts:

- pure deterministic intermediate reuse;
- content-addressed cross-call reuse with mutation isolation;
- measured redundancy elimination as a benchmark discipline;
- bounded strategy memory;
- strategy-cycle and strategy-churn detection;
- no upward dependency promotion;
- immutable hash-bound artifacts;
- benchmark observations kept separate from correctness;
- neutral defaults that preserve pre-existing semantics;
- compositional boundedness where each admitted factor is individually bounded;
- explicit validity conditions for optimizations.

Do not import QEC's domain-specific physics/scoring ontology into IBAE.

## 3.3 QSOLKCB/ChatGPT donor concepts

Useful donor concepts:

- `CAPABILITY != AUTHORITY`;
- normalized proposal before authority decision;
- exact action-bound approvals;
- approval/replay threat modelling;
- hostile-input assumption for model output, repositories, documents, webpages, worker output, and tool output;
- single authority ledger semantics;
- opaque credential handles;
- default-deny policy;
- one authority source with revocation rather than independent competing authority instances;
- raw secrets excluded from actions, receipts, logs, and inherited environments;
- fail-closed unknown capabilities;
- machine authority represented structurally rather than inferred from model text.

Do not copy the workstation/Wayland/OBS architecture into IBAE. QSOLKCB/ChatGPT has a different purpose and trusted-computing boundary.

## 3.4 NEXUS v5 donor concepts

The attached NEXUS v5 source contains several useful execution patterns.

### Deterministic avalanche mixer

NEXUS uses a compact integer mixer mirrored in CPU and GPU implementations:

```text
x ^= x >> 16
x *= 0x7feb352d
x ^= x >> 15
x *= 0x846ca68b
x ^= x >> 16
```

This is not the Quake 3 fast inverse-square-root algorithm, but it is a conceptual cousin in the sense that a very small sequence of fixed bitwise/arithmetic operations provides a useful low-level approximation/dispersion primitive without invoking a heavyweight mechanism.

NEXUS uses this family for deterministic seeded state dispersion, deterministic jitter selection, and compact non-cryptographic regression evidence.

Potential IBAE uses are limited to:

- fast diagnostic fingerprints;
- deterministic synthetic workload dispersion;
- deterministic shard or probe ordering experiments;
- inexpensive divergence localization before canonical SHA-256 verification;
- future GPU workgroup-local reductions.

Permanent boundary:

```text
MIX32/FOLD != SHA-256 AUTHORITY
```

### Tree/XOR evidence reduction

NEXUS reduces many lane-local diagnostic words through deterministic XOR tree reduction and emits a tiny fixed-word receipt. This supports a useful IBAE pattern:

```text
many local diagnostic observations
        -> bounded deterministic reduction
        -> tiny non-cryptographic diagnostic fingerprint
        -> canonical SHA-256 receipt remains authority
```

This may complement, but must not silently replace, the existing v0.4 FNV-1a-64 non-authoritative fold.

### Cross-backend verification discipline

NEXUS verifies accelerated behavior through independent checks rather than speed alone. IBAE should borrow the abstract pattern:

```text
repeatability
+ CPU/reference differential
+ replay/state/receipt equivalence
```

Do not import NEXUS geometry, vector-equilibrium semantics, ququart labels, or scientific claims into IBAE.

## 3.5 RES=RAG / CSNP donor concepts

RES=RAG / CSNP provides a useful regulated-control protocol, but its semantic and human-machine research ontology is not an IBAE authority model.

Useful donor concepts:

### Declare -> Observe -> Classify -> Intervene -> Receipt -> Replay -> Recalibrate

This seven-stage cycle is a strong general control pattern for IBAE:

```text
DECLARE
    versioned task/governance/calibration profile

OBSERVE
    admitted runtime/evidence state

CLASSIFY
    deterministic progress/pressure/recovery class

INTERVENE
    least-force admissible recovery/action

RECEIPT
    canonical identity and bounded evidence

REPLAY
    independently verify rules, evidence, lineage, and outcome

RECALIBRATE
    change thresholds only under a new profile identity/version
```

### Least-force admissible intervention

IBAE should prefer the least-authority, least-cost action that can satisfy the declared recovery criterion.

Candidate recovery order where semantics permit:

```text
reuse valid evidence
    -> inspect/read
    -> clarify missing state
    -> retry within existing budget
    -> switch to a materially different bounded strategy
    -> request finite continuation
    -> bounded diversification experiment
    -> human handoff / deterministic partial finalization
    -> stop
```

The exact order is profile-specific. It must not override explicit task dependencies or authority requirements.

### Missing data is unavailable, not zero

This reinforces the existing IBAE epistemic distinction:

```text
observed
derived
model_proposed
unknown/unavailable
```

### Local calibration only

Operational thresholds must live in a declared versioned profile. Research claims, published values, or benchmark observations cannot silently become governance thresholds.

### Research-claim non-interference

Externally reported or archived values remain provenance-bearing claims until explicitly validated for an IBAE policy/benchmark profile.

### Rate-capacity pressure as research candidate

RES=RAG defines a rate/capacity warning quantity. IBAE may evaluate an analogous, explicitly IBAE-specific proposal/work pressure metric:

```text
proposal/frontier growth rate
        versus
orchestrator/runtime processing capacity
```

This is a CANDIDATE research metric only. No RES=RAG threshold or formula becomes an IBAE safety constant by inheritance.

Potential uses:

- detect rapidly expanding work frontiers before budget exhaustion;
- trigger backpressure or batching experiments;
- compare mono-path versus diversified recovery strategies;
- predict loss of governability before literal cycle detection.

### Bounded diversification / multitask brake as research candidate

RES=RAG v1.1.0 describes `multitask_brake` as a falsifiable intervention rather than a guaranteed safety mechanism.

IBAE may benchmark a related bounded diversification intervention when a single strategy path is overloaded or stalled:

```text
one overloaded strategy frontier
        -> split into a small finite set of independent obligations
        -> evaluate whether progress/recovery improves
```

This must never be assumed beneficial. It remains experimental until benchmarked against simpler baselines.

Do not import Wasserstein thresholds, semantic-cycle ontology, consciousness language, or RES=RAG scientific claims into IBAE authority semantics.

---

# 4. Completed foundation

## v0.1 - Deterministic Execution Kernel

Merged in PR #1.

- [x] Canonical JSON serialization.
- [x] SHA-256 content fingerprints.
- [x] Canonical read-tool identity.
- [x] Non-string mapping-key rejection.
- [x] Dependency-sensitive observation cache.
- [x] Cache mutation isolation.
- [x] Validate observations before cache insertion.
- [x] Finite request/execution/retry/history budgets.
- [x] Deterministic period-1/2/3 cycle detection.
- [x] Cache-hit/cold-execution cycle-history equivalence.
- [x] OpenAI-only proprietary remote-provider policy.
- [x] Deterministic benchmark and CI gates.

## Architecture contract - Invariant-first freeze

Merged in PR #2.

- [x] Governance/orchestration/runtime/benchmark authority separation.
- [x] Identity taxonomy.
- [x] Logical execution-clock direction.
- [x] Vector-budget direction.
- [x] Python/Rust authority boundary.
- [x] AI-native compact-state direction.
- [x] Donor geometry kept non-semantic.
- [x] Architecture MUST / SHOULD / CANDIDATE status registry.

## v0.2 - Deterministic Python Orchestration Reference

Merged in PR #3.

- [x] Immutable obligation registry.
- [x] Deterministic dependency DAG and ready set.
- [x] Canonical proposal/admission identities.
- [x] Capability-owned semantic argument allowlists.
- [x] Typed strategy schemas and canonical strategy identity.
- [x] Replay-safe-only deduplication.
- [x] Occurrence identity for effectful actions.
- [x] Observed/derived/model-proposed/unknown separation.
- [x] Compact agent-facing projection.
- [x] Stable structured rejection codes and recovery actions.
- [x] Model-free byte-stable fixture.

## v0.3 - Rust Deterministic Runtime

Merged in PR #4.

- [x] Rust runtime authority for exact counters/state/cache/history.
- [x] PyO3/maturin in-process boundary.
- [x] Narrow versioned runtime protocol.
- [x] Rust-owned authoritative state with no Python mutation surface.
- [x] Python/Rust canonicalization conformance.
- [x] Python/Rust execution differential tests.
- [x] Cache, invalidation, mutation isolation, budget, cycle, and retry parity.
- [x] Byte-stable cross-language fixture.
- [x] No network/model dependency inside Rust runtime.

## v0.4 - Governance, Identity Receipts, and Compact Evidence

Merged in PR #5.

- [x] Governance wrapper outside orchestration/runtime.
- [x] Explicit OpenAI-only remote provider class.
- [x] Supervisor/worker/tool authority classes.
- [x] Pure/snapshot/volatile read and idempotent/non-idempotent mutation classifications.
- [x] Task/governance/orchestration/execution/execution-plan/benchmark identity separation.
- [x] Final acceptance, rejection, and partial receipts.
- [x] Strict authorization-manifest binding.
- [x] Rust streaming Compact Evidence Plane.
- [x] Fixed 2,048-byte compact receipt ceiling for the declared profile.
- [x] No O(N) successful-case trace retention.
- [x] Bounded selective failure expansion.
- [x] Optional non-cryptographic FNV-1a-64 fold outside correctness identity.
- [x] 100,000-case deterministic compact-evidence stress fixture.
- [x] Existing v0.2/v0.3 fixtures preserved.

---

# 5. Current frontier

## v0.5 - Progress, Bounded Continuation, and Control Classification

Goal: distinguish useful progress from mere activity and grant only finite, pre-authorized continuation.

This phase addresses one of QSOL-IBAE's original motivating problems: a useful long-running agent should be able to continue when objective progress exists, while loops, strategy thrashing, confidence theatre, and self-extension remain bounded.

### 5.1 Objective progress

- [ ] Define `IBAE-PROGRESS-V1`.
- [ ] Progress derives from declared acceptance obligations/evidence, not model confidence.
- [ ] Keep exact prior/current obligation and gate states.
- [ ] Distinguish `progress`, `new_information`, `stalled`, `regressed`, `incomparable`, and `complete` where useful.
- [ ] Treat activity count, token count, wall time, and model confidence as non-authoritative observations.
- [ ] Do not automatically classify discovery of new failures as negative progress.
- [ ] Bind progress evidence to task/governance/orchestration identity.
- [ ] Require missing progress evidence to remain `indeterminate` rather than silently `no_progress` where the distinction matters.

### 5.2 Material strategy change

- [ ] Define what constitutes a semantically material strategy change.
- [ ] Require a new canonical strategy identity.
- [ ] Reject superficial rephrasing as a strategy change.
- [ ] Bind target obligations, dependency route, recovery mode, and capability frontier where relevant.
- [ ] A strategy change may justify one bounded recovery attempt but is not itself evidence of progress.

### 5.3 Strategy stability donor hardening

Borrow the QEC strategy-stability pattern without importing multiplicative scoring.

- [ ] Bound retained strategy history.
- [ ] Detect period-1/2/3 strategy cycles independently of action-level cycles.
- [ ] Detect repeated rapid strategy flipping without objective acceptance-state improvement.
- [ ] Classify strategy churn deterministically.
- [ ] `strategy_churn != progress`.
- [ ] Strategy-cycle recovery requires a materially different admitted strategy.

Candidate invariant family:

```text
IBAE-PROG-006 - Strategy history is bounded.
IBAE-PROG-007 - Strategy churn is not progress.
IBAE-PROG-008 - New information is distinct from task completion progress.
```

### 5.4 Governability/control classification

Borrow the protocol shape, not the RES=RAG scientific metric.

Define a small closed IBAE control classification such as:

```text
governable
recoverable
terminal_exhausted
indeterminate
complete
```

Exact names may change before contract freeze.

Rules:

- [ ] One failed action or one warning must not automatically produce terminal classification.
- [ ] `terminal_exhausted` requires a declared finite recovery/intervention set and explicit exhaustion/recovery criterion.
- [ ] Missing required evidence yields `indeterminate`, not `governable`.
- [ ] `complete` remains separate from `governable`.
- [ ] Control classification must be computed from versioned policy/profile state.
- [ ] Control classification itself cannot extend runtime authority.

### 5.5 Least-force admissible recovery

Introduce an explicit deterministic recovery preference contract where dependencies permit.

Candidate hierarchy:

```text
reuse valid evidence
read/inspect
clarify missing state
retry inside existing limits
material strategy change
finite continuation lease
bounded diversification experiment
human handoff / partial finalization
stop
```

- [ ] The profile declares which interventions are available.
- [ ] Recovery ordering cannot bypass task dependencies or tool authority.
- [ ] Intervention selection is recorded separately from intervention success.
- [ ] A lower-cost intervention that cannot satisfy the declared recovery condition may be skipped with a canonical reason.

### 5.6 Finite continuation lease contract

Define `IBAE-CONTINUATION-LEASE-V1`.

- [ ] Exact finite maximum number of leases.
- [ ] Exact finite resource vector for every lease.
- [ ] Exact finite cumulative ceiling committed before execution begins.
- [ ] Checked integer arithmetic only for authority-bearing counters.
- [ ] Supervisor may request a lease but cannot grant one.
- [ ] Governance grants; Rust applies.
- [ ] Runtime cannot manufacture or enlarge a lease.
- [ ] Tool backend cannot request or grant itself authority.
- [ ] Worker principal cannot grant continuation.
- [ ] Lease decision is deterministic for identical canonical state.

Candidate resource vector:

```text
request_delta
execution_delta
retry_delta
mutation_delta    # zero/unsupported until mutation execution exists
history_delta
```

### 5.7 Single authority ledger

- [ ] One governed task/session has exactly one authority-bearing continuation ledger.
- [ ] Multiple future model roles/workers cannot maintain independent lease ceilings for the same task.
- [ ] Lease count, cumulative grant, and remaining ceiling live in authoritative state.
- [ ] Ledger state is included in continuation/checkpoint identity.

### 5.8 Authority epoch and revoke-all semantics

- [ ] Define an authority/revocation epoch.
- [ ] Every continuation grant binds the current authority epoch.
- [ ] Advancing/revoking the epoch invalidates outstanding unapplied grants.
- [ ] Revoke-all does not imply task completion.
- [ ] Revocation has its own canonical receipt/status.

### 5.9 Receipt-chain continuity

Borrow CSNP's predecessor-linked audit pattern in an IBAE-specific form.

- [ ] Progress/continuation checkpoints bind the exact predecessor checkpoint/receipt identity.
- [ ] First checkpoint uses an explicit root/null predecessor contract.
- [ ] Replay verifies predecessor linkage, state identity, progress evidence, and lease lineage.
- [ ] Chain integrity does not imply external truth or producer authenticity.
- [ ] Forked continuation chains are rejected or explicitly represented rather than silently merged.

### 5.10 Checkpoint/resume

Define `IBAE-CONTINUATION-CHECKPOINT-V1`.

Bind at minimum:

```text
task identity
governance identity
authority epoch
orchestration identity
runtime session/state identity
progress identity
strategy identity
continuation-policy identity
lease ledger state
compact evidence identity where applicable
logical tick
predecessor checkpoint identity
checkpoint status
```

- [ ] Resume fails closed on stale/mismatched identity.
- [ ] Structural hash consistency is not producer authentication.
- [ ] If durable cross-process authority cannot be proven safely under the current native-seal model, keep the supported scope explicit and narrower rather than weakening trust.

### 5.11 Partial finalization

- [ ] Distinguish structural partial receipts from semantic continuation-exhaustion partial receipts.
- [ ] Preserve useful evidence when continuation is denied/exhausted.
- [ ] Canonical reasons include no progress, terminal cycle, exhausted ceiling, revocation, watchdog termination, and recovery-set exhaustion where applicable.
- [ ] Partial cannot be relabelled accepted without satisfying the acceptance contract.

### 5.12 Experimental budget profiles

Establish versioned model-free experiment profiles, for example:

```text
tiny
standard
extended
repository
```

Benchmark at least:

- equal fixed leases;
- front-loaded continuation;
- geometrically decreasing continuation;
- small-base plus bounded recovery lease.

Geometric continuation remains a candidate until evidence supports promotion.

### 5.13 Silent recalibration forbidden

Borrow the CSNP profile-version discipline.

- [ ] Every budget/lease/progress threshold lives in a named versioned profile.
- [ ] Changing an operational threshold changes profile/governance identity.
- [ ] Benchmark suggestions, literature values, and model-proposed numbers cannot change runtime policy directly.
- [ ] No threshold becomes universal merely because it performed well in one corpus.

Candidate invariants:

```text
IBAE-CAL-001 - Research/benchmark claims do not affect authority until promoted into a versioned validated profile.
IBAE-CAL-002 - Operational recalibration changes profile identity and cannot be silent.
```

### v0.5 gate

For identical canonical task, governance, orchestration, runtime, progress, strategy, authority-epoch, predecessor-checkpoint, and continuation-policy state:

- progress/control classification is identical;
- intervention eligibility is identical;
- lease grant/deny decision is identical;
- granted resource vector is identical;
- checkpoint/receipt identities are identical;
- no component can exceed the finite ceiling predetermined by governance;
- activity without objective progress cannot justify continuation;
- prohibited action or strategy cycles fail closed;
- unavailable required evidence cannot be silently treated as safe or zero;
- one warning/failure cannot become terminal without the declared finite recovery criterion.

---

# 6. Supervisor boundary before any live connection

## v0.6A - Supervisor Boundary, Decision-Sufficient Context, and Calibration Discipline

Goal: freeze what the eventual OpenAI supervisor is allowed to see, propose, and influence before any network model is attached.

### 6.1 UFT-derived observation contract

Treat the agent-visible context as a deterministic observation/projection of authoritative state.

```text
full authoritative state S
        |
        | P
        v
compact supervisor state C
```

Do not require `P` to be injective.

The required property is decision sufficiency:

```text
P(S1) = P(S2)
        =>
all supervisor-visible governance-relevant next-action facts agree
```

At minimum this includes:

- legal next-action classes;
- ready/blocked obligations;
- completion eligibility;
- lease eligibility;
- remaining agent-visible budgets;
- recovery actions;
- capability availability;
- control classification;
- authority/revocation state relevant to the supervisor.

Candidate invariants:

```text
IBAE-CTX-001 - Compact supervisor state is an observation, not authoritative state itself.
IBAE-CTX-002 - Equal compact projections imply equal legal supervisor decision surfaces.
IBAE-CTX-003 - Non-injective compact projection does not claim full-state reconstruction.
IBAE-CTX-004 - Omitted state must be irrelevant to the legal supervisor decision surface for that projection version.
```

### 6.2 Context checkpoint / fresh-session contract

Define a compact handoff object suitable for a fresh agent session without replaying the full conversation.

Candidate fields:

```text
task identity
repo/live-state identity
governance/profile identity
authority epoch
accepted phase/gate identities
current obligation state
current strategy/progress classification
remaining budgets/leases
compact evidence identities
next admissible work
known blockers
checkpoint identity
```

- [ ] Generated deterministically from authoritative state.
- [ ] No full conversational transcript required for deterministic bookkeeping.
- [ ] Full underlying evidence remains auditable on demand.
- [ ] Context checkpoint size is explicitly bounded.
- [ ] Fresh-session replay is compared against continued-session behavior.

### 6.3 Machine-readable assurance graph

Define `IBAE-ASSURANCE-GRAPH-V1` with explicit evidence/support classes.

Candidate nodes:

```text
MODEL_PROPOSAL
OBSERVATION
DERIVED_FACT
RUNTIME_RECEIPT
CONFORMANCE_RESULT
COMPACT_EVIDENCE
PROGRESS_EVIDENCE
BENCHMARK_OBSERVATION
RESEARCH_CLAIM
GOVERNANCE_DECISION
FINAL_ACCEPTANCE
```

Examples of allowed/forbidden promotion:

```text
RUNTIME_RECEIPT -> may support -> EXECUTION_EVIDENCE
EXECUTION_EVIDENCE -> may support -> OBLIGATION_SATISFACTION
MODEL_PROPOSAL -X-> OBSERVATION
MODEL_PROGRESS_CLAIM -X-> PROGRESS_EVIDENCE
BENCHMARK_OBSERVATION -X-> CORRECTNESS
RESEARCH_CLAIM -X-> GOVERNANCE_THRESHOLD
CHECKSUM_MATCH -X-> SEMANTIC_TRUTH
```

### 6.4 Capability and control-plane authority

Adopt the explicit invariant:

```text
CAPABILITY != AUTHORITY
```

Candidate invariant:

```text
IBAE-AUTH-003 - Discovery/availability of a tool, worker, model operation,
runtime command, cache entry, or accelerator backend does not grant authority
for its use.
```

### 6.5 Data plane versus control plane

Define a structural prompt-injection boundary.

```text
IBAE-CTRL-001 - Retrieved content is data, not governance authority.
IBAE-CTRL-002 - Governance-sensitive instructions have explicit trusted provenance.
```

Assume potentially hostile:

- model output;
- web pages;
- repository/file content;
- retrieved documents;
- tool output;
- worker output;
- OCR/UI text;
- downloaded content;
- benchmark reports;
- externally supplied receipts until validated.

Imperative text inside these surfaces cannot alter provider policy, lease ceilings, tool authority, completion rules, or trusted instruction provenance.

### 6.6 Calibration and research-claim non-interference

Borrow the RES=RAG/CSNP separation between externally reported claims and operational profiles.

Define profile-bound statuses such as:

```text
hypothesis
reported
externally_archived
validated_in_profile
```

for research/benchmark threshold suggestions if such records are supported.

Rules:

- [ ] `externally_archived` means provenance only.
- [ ] Only an explicitly validated/promoted profile may affect operational policy.
- [ ] Profile validation method and corpus identity are recorded.
- [ ] Changing classifier/budget semantics requires a new profile identity/version.
- [ ] No model or retrieved document can silently recalibrate policy.

### 6.7 Authority/replay hardening

- [ ] Supervisor proposals normalize before authority decisions.
- [ ] Any one-shot authority token binds exact normalized content/state.
- [ ] Stale authority grants cannot apply to later state.
- [ ] Authority epoch invalidation works across all outstanding grants.
- [ ] One governed task/session has one authority ledger.
- [ ] Session/nonce/occurrence fields are exact and bounded where used.

### 6.8 Functional-mode default

Borrow only the implementation discipline from RES=RAG Mode B:

- [ ] Supervisor protocol state uses observable/functional terms.
- [ ] No authority decision depends on anthropomorphic inference or claims about model interiority.
- [ ] Model confidence/persona language remains non-authoritative.

### v0.6A gate

Before any live OpenAI connection:

- compact supervisor state is decision-sufficient under a versioned contract;
- assurance promotions are machine-readable and fail closed;
- data/control provenance is explicit;
- capability never implies authority;
- threshold/profile calibration cannot drift silently;
- research/benchmark claims cannot alter operational policy without explicit promotion;
- stale/replayed authority fails closed;
- fresh-session checkpoint replay is semantically equivalent for deterministic next-action state.

---

# 7. Full synthetic wiring before live connections

## v0.6B - Synthetic End-to-End Supervisor Conformance

Goal: execute the complete intended agent control path with fake/frozen external data and real IBAE authority machinery before allowing any live network dependency.

Principle:

```text
fake external world
real governance
real orchestration
real progress/continuation
real Rust accounting
real compact evidence
real receipts
real authority boundaries
```

### 7.1 IBAE control-cycle protocol

Adopt an IBAE-specific version of the useful CSNP cycle:

```text
DECLARE
    task + governance + calibration/profile identity

OBSERVE
    synthetic/frozen admitted tool/runtime evidence

CLASSIFY
    progress/control/pressure state

INTERVENE
    deterministic least-force admissible action

RECEIPT
    canonical receipts + compact evidence

REPLAY
    independent deterministic verifier

RECALIBRATE
    only under a new versioned profile
```

The cycle is an execution-control protocol only. It does not inherit RES=RAG semantic ontology.

### 7.2 Synthetic supervisor protocol

Build a deterministic fake supervisor that emits the same normalized proposal contract expected from future OpenAI integration.

- [ ] No network.
- [ ] No credential.
- [ ] No provider SDK required.
- [ ] Transcript/proposal streams are checked-in deterministic fixtures.
- [ ] Synthetic supervisor receives the same compact state surface as live transport will later receive.

### 7.3 Synthetic tool universe

Provide bounded fake adapters for representative classes:

```text
FakeGitHub
FakeFilesystem
FakeWeb
FakeReadTool
FakeEffectTool
FakeWorker
FakeCredentialBroker
```

Authority semantics remain real.

Synthetic effect tools must still require real IBAE governance approval contracts.

### 7.4 Synthetic credentials

Use opaque handles only, for example:

```text
cred:openai.test
```

Test:

- raw credential-shaped input rejected;
- opaque handle accepted only by the appropriate contract;
- no secret appears in receipt, compact state, log fixture, or correctness identity;
- no actual secret resolution occurs.

### 7.5 Golden supervisor transcript corpus

At minimum:

- happy path;
- long progressing task;
- activity-without-progress loop;
- period-1/2/3 action cycle;
- strategy cycle;
- strategy churn;
- material strategy recovery;
- superficial strategy paraphrase;
- stale lease replay;
- duplicate lease application;
- authority-epoch revocation;
- capability escalation attempt;
- fake completion claim;
- fake progress claim;
- prompt injection in repository text;
- prompt injection in tool output;
- prompt injection in worker output;
- malformed receipt;
- forged compact evidence;
- provider substitution attempt;
- missing measurements/evidence producing `indeterminate`;
- one warning followed by successful recovery;
- recovery-set exhaustion;
- silent threshold/profile mutation attempt;
- externally archived research claim attempting to alter policy;
- context checkpoint resume;
- fresh-session versus continued-session equivalence.

### 7.6 Simulation invariants

```text
IBAE-SIM-001 - Synthetic and live adapters enter the same normalized supervisor interface.
IBAE-SIM-002 - Synthetic adapters receive no extra authority.
IBAE-SIM-003 - Transport success cannot alter governance/orchestration semantics.
IBAE-SIM-004 - Core conformance requires no network, credentials, or remote model.
IBAE-SIM-005 - Equivalent normalized proposal streams preserve deterministic IBAE decisions across adapter substitution.
```

### 7.7 No-live-connection enforcement

CI/conformance must prove the synthetic phase cannot accidentally connect externally.

Possible controls:

- no OpenAI SDK dependency yet, or adapter compiled/disabled behind an explicit later feature;
- no credential resolver capable of returning real secrets;
- no required DNS/network access;
- fake provider has a closed fixture source;
- tests fail if a live endpoint configuration appears in the synthetic profile.

### 7.8 Synthetic pressure/backpressure experiments

Introduce, as research-only telemetry, candidate proposal/work pressure measurements.

Evaluate whether simple exact counters are sufficient before using any ratio metric.

Possible observables:

```text
ready-frontier growth per logical interval
proposal arrival count per logical interval
admission throughput
execution throughput
rejection backlog
unresolved obligation growth
```

If a normalized pressure ratio is tested, its denominator floor, units, profile, and calibration must be explicit.

No inherited RES=RAG threshold such as `1` becomes IBAE authority without independent validation.

### 7.9 Bounded diversification candidate

Benchmark an optional finite diversification intervention inspired by the falsifiable `multitask_brake` idea:

```text
stalled overloaded mono-strategy
        -> split into small independent obligation subset
        -> observe whether progress/recovery improves
```

Controls:

- [ ] Max number of simultaneous sub-obligations explicitly bounded.
- [ ] No extra total authority or lease budget created by diversification.
- [ ] Compare against simple slowdown/retry/strategy-change baselines.
- [ ] Intervention selection does not imply success.
- [ ] Remains CANDIDATE unless benchmark evidence supports promotion.

### v0.6B gate

The entire supervisor -> governance -> orchestration -> progress/continuation -> Rust runtime -> compact evidence -> final/partial receipt path must pass deterministically using only synthetic/frozen external data.

No live OpenAI request, live credential, or required external service is allowed before this gate is accepted.

---

# 8. Staged live OpenAI activation

## v0.6C - Official OpenAI Transport and Credential Boundary

Goal: attach reality one trust boundary at a time without changing IBAE semantics.

The OpenAI adapter should be boring. It translates between official OpenAI wire objects and already-tested IBAE normalized supervisor messages.

### 8.1 Provider boundary

- [ ] Official OpenAI only.
- [ ] No generic provider registry.
- [ ] No arbitrary proprietary endpoint abstraction.
- [ ] No Anthropic/xAI/Google/OpenRouter/Azure generic compatibility layer.
- [ ] Runtime remains provider-agnostic below Python supervisor boundary.
- [ ] Current official API integration choice documented against the same IBAE protocol.

### 8.2 Opaque credential handles

```text
model/orchestration sees: cred:openai.<name>
credential broker sees:   actual secret for minimum required lifetime
receipts/logs see:         no raw secret
```

Candidate invariants:

```text
IBAE-SECRET-001 - Raw OpenAI secrets never enter orchestration/model-visible state/receipts/tool arguments/logs.
IBAE-SECRET-002 - Credentials are referenced only through opaque governance-owned handles.
IBAE-SECRET-003 - Secret resolution occurs at the latest responsible moment for the shortest necessary lifetime.
```

### 8.3 Activation ladder

Proceed in strict stages:

```text
Stage 0: fake supervisor + fake tools                [v0.6B]
Stage 1: live OpenAI + fake tools
Stage 2: live OpenAI + deterministic read-only local fixtures
Stage 3: live OpenAI + selected real read-only tools
Stage 4: live OpenAI + governed effects              [v0.6D+]
```

Every stage gets its own evidence/rollback gate.

Do not jump directly from synthetic mode to broad effectful execution.

### 8.4 Live transport equivalence

- [ ] Equivalent normalized synthetic/live proposal streams produce the same deterministic admission decisions.
- [ ] OpenAI request IDs, latency, token counts, and network metadata remain benchmark/transport observations unless separately required.
- [ ] Live model output remains `model_proposed` until admitted.
- [ ] Live API success never grants tool/lease authority.

### v0.6C gate

Live OpenAI transport must not introduce a semantic or authority path unavailable in synthetic conformance.

---

# 9. Governed effect execution

## v0.6D - Effectful Runtime Profile

Do not smuggle mutations through the read-only runtime protocol.

- [ ] Version a separate effect execution command family.
- [ ] Preserve occurrence identity.
- [ ] Idempotent and non-idempotent mutations remain distinct.
- [ ] Exact governance authorization required.
- [ ] Stale/replayed approvals rejected.
- [ ] Authority epoch/revoke-all applies.
- [ ] Before/after evidence where the tool contract permits it.
- [ ] Effect receipt cannot be replaced by model claims.
- [ ] Partial/failed effects preserve evidence and ambiguity explicitly.
- [ ] Synthetic effect fixtures first.
- [ ] Selected real effects only after dedicated review.

### v0.6D gate

Every effect is explicitly authorized, occurrence-bound, replay-safe under its declared semantics, bounded, and receipt-bearing.

---

# 10. Baseline agent-efficiency corpus

## v0.7 - Prove IBAE actually saves work

Before accelerator work, demonstrate measurable benefit on realistic agent workloads.

Compare equivalent tasks with and without the relevant IBAE machinery where practical.

Measure:

- [ ] task success rate;
- [ ] OpenAI model turns;
- [ ] requested tool calls;
- [ ] actual tool executions;
- [ ] cache hits;
- [ ] duplicate proposals eliminated;
- [ ] deterministic derived values reused;
- [ ] invalid/rejected proposals;
- [ ] recovery success after rejection;
- [ ] cycle incidence;
- [ ] strategy-cycle/churn incidence;
- [ ] leases requested/granted/denied;
- [ ] partial-finalization frequency;
- [ ] compact-evidence bytes versus underlying work cardinality;
- [ ] agent-visible context bytes/tokens;
- [ ] full transcript bytes/tokens avoided by checkpointing;
- [ ] tokens consumed;
- [ ] elapsed wall-clock time as observation only;
- [ ] semantic divergence, which must be zero for accepted deterministic cases;
- [ ] energy/compute proxies only where methodology is explicit and not overstated.

### 10.1 Fresh-session/context-checkpoint benchmark

Compare:

```text
A. long continuously accumulated conversation/context
B. fresh session + canonical IBAE checkpoint + live repository/evidence retrieval
```

Measure:

- model input tokens;
- duplicated context content;
- task success;
- tool rediscovery;
- stale-state errors;
- wall-clock observation;
- deterministic decision-surface equivalence where applicable.

### 10.2 Control-cycle benchmark

Compare whether explicit:

```text
Declare -> Observe -> Classify -> Intervene -> Receipt -> Replay
```

reduces invalid actions/recovery waste relative to an unstructured baseline.

Do not assume the extra classification machinery is free. Count its overhead.

### 10.3 Pressure/backpressure research

Evaluate whether work-frontier pressure predicts wasted calls, cycle onset, or lease exhaustion.

Candidate baselines:

- simple ready-queue length;
- growth in unresolved obligations;
- proposal-to-admission ratio;
- execution-throughput deficit;
- normalized rate/capacity metric.

No pressure metric may become governance authority without held-out evidence and a versioned policy promotion.

### 10.4 Bounded diversification research

Compare mono-strategy recovery against bounded diversification for selected workloads.

Measure:

- progress improvement;
- additional tool/model cost;
- duplicated work;
- convergence/recovery rate;
- context growth;
- strategy churn;
- total execution budget consumed.

### v0.7 gate

IBAE must demonstrate that its deterministic machinery provides net useful-work benefit on the benchmark corpus without semantic divergence in accepted deterministic cases.

---

# 11. Derived-state reuse and internal waste elimination

## v0.7A - Pure Derived-State Reuse

QEC demonstrates that pure deterministic intermediates can be computed once and reused safely when their validity conditions are explicit.

Apply this within IBAE to derived orchestration/governance values such as:

- dependency closures;
- ready-set derivations;
- canonical action identities;
- blocker projections;
- strategy identities;
- progress classifications;
- capability classifications;
- receipt constituent hashes;
- compact state projection fragments;
- assurance graph support checks;
- control classifications.

Candidate invariants:

```text
IBAE-DERIVE-001 - A derived value proven pure over immutable canonical source state may be reused.
IBAE-DERIVE-002 - Reuse requires all declared source identities to remain unchanged.
IBAE-DERIVE-003 - Caller mutation cannot alter stored derived authority state.
IBAE-DERIVE-004 - Derived reuse does not suppress occurrence-sensitive effects.
```

Requirements:

- [ ] benchmark before/after call counts;
- [ ] document purity assumptions;
- [ ] explicit source identity set;
- [ ] mutation isolation;
- [ ] invalidation tests;
- [ ] no unbounded cache growth;
- [ ] no performance claim without measurement.

### v0.7A gate

Every derived-cache hit must be provably semantically equivalent to recomputation under the declared source identities.

---

# 12. Exact bounded sampling research

## v0.7B - Large Logical Candidate-Space Sampling

UFT-ID's formally verified uniform floor-sampling result gives a clean candidate for bounded representative selection.

Candidate mapping:

```text
logical cardinality L
sample count R
R < L

sample(i) = floor(i * L / R)
for i in [0, R)
```

Potential uses:

- diagnostic audit sampling;
- benchmark subsets;
- large candidate-frontier probes;
- periodic conformance probes;
- very large logical spaces where full materialization is unnecessary.

Permanent boundary:

```text
sampled evidence != exhaustive correctness
```

Requirements:

- [ ] exact integer implementation;
- [ ] no floating-point index authority;
- [ ] deterministic fixture/reference proof;
- [ ] selection policy included in benchmark/evidence profile identity;
- [ ] never sample away a mandatory correctness gate;
- [ ] compare against simpler deterministic prefix/random-seeded baselines;
- [ ] formal result cited only for the arithmetic property actually established.

---

# 13. Fast diagnostic fingerprints and deterministic dispersion

## v0.7C - Non-Cryptographic Fast Diagnostic Profile

NEXUS provides a useful candidate family for fast deterministic integer mixing and XOR-tree reduction. IBAE already has a non-authoritative FNV-1a-64 observation. This phase evaluates whether a stronger avalanche-style diagnostic provides measurable benefit.

### 13.1 Candidate fast mixer

Evaluate an independently implemented fixed-u32 avalanche mixer profile inspired by the documented NEXUS pattern.

Possible uses:

- per-case diagnostic fingerprints;
- deterministic shard seeds;
- low-cost mismatch localization;
- workgroup-local reduction in future accelerators;
- synthetic deterministic dispersion.

### 13.2 Strict authority boundary

```text
FAST_MIX/FOLD
    correctness_authority = false

SHA-256 CANONICAL RECEIPT
    correctness_authority = true
```

- [ ] Fast mixer/fold never replaces SHA-256.
- [ ] Collision does not imply equality.
- [ ] Fast mismatch may trigger detailed verification.
- [ ] Fast match cannot by itself establish final acceptance.
- [ ] Mixer seed/configuration is explicit and versioned.

### 13.3 Compare candidates

Benchmark:

- current FNV-1a-64 diagnostic;
- candidate 32-bit avalanche mixer aggregated into multiple words;
- direct SHA-256 where cost is acceptable;
- no-fast-fold baseline.

Measure:

- CPU cost;
- future GPU suitability;
- collision behavior on adversarial synthetic corpus;
- mismatch-detection sensitivity;
- amount of detailed evidence expansion avoided.

### 13.4 Deterministic dispersion candidate

A content-derived seed plus a deterministic mixer may be used experimentally to spread synthetic probes or candidate ordering without hidden randomness.

Permanent rule:

```text
deterministic dispersion != randomness authority
```

If ordering affects semantics, it belongs in orchestration identity and must be canonical rather than pseudo-randomized.

If ordering is semantically neutral, it may live in execution-plan identity.

### v0.7C gate

No fast diagnostic primitive becomes correctness authority. Promotion requires measured benefit over the existing FNV/no-fold baselines and preserved SHA-256 conformance.

---

# 14. Accelerator / GPU research profile

## v0.8 - Accelerator Candidate

GPU execution is an optimization profile, never correctness authority by speed alone.

Reference order:

```text
Python semantic reference
        -> Rust CPU authority
        -> accelerator candidate
        -> independent conformance gate
```

### 14.1 Initial local target

- [ ] Begin on local NVIDIA RTX 5060 Ti.
- [ ] Use exact integer governance/accounting fields.
- [ ] Keep accelerator heuristic/numeric fields explicitly non-authoritative where floating point is used.
- [ ] No accelerator path may call a model provider.

### 14.2 NEXUS-derived verification triad

Borrow the verification pattern, not the VE geometry:

```text
1. repeat accelerator run under identical deterministic input/profile;
2. compare exact relevant aggregates/results to Rust CPU authority;
3. replay receipt/state lineage and require equivalent accepted semantics.
```

Where a fully reversible execution mapping exists, inversion/reconstruction tests may be added, but reversibility is not an IBAE requirement.

### 14.3 Resident-state / compact-evidence architecture

Preserve the v0.4 principle:

```text
large resident accelerator state
        -> bounded local reduction
        -> tiny compact evidence readback
```

Do not read back large successful per-case state solely for audit convenience.

Detailed mismatch expansion remains explicit and bounded.

### 14.4 Fast local diagnostic reductions

If v0.7C admits a fast diagnostic profile, accelerator implementations may use it for non-authoritative local divergence detection.

Canonical SHA-256 receipts remain generated/validated under the authoritative profile.

### 14.5 Execution layout experiments

- [ ] Compare 30-of-32 padded cells against simpler full-32 layouts.
- [ ] Keep metadata in a sidecar unless evidence justifies otherwise.
- [ ] Measure warp divergence.
- [ ] Measure memory locality.
- [ ] Compare AoSoA/SoA layouts.
- [ ] Measure batched transition throughput.
- [ ] Keep execution topology distinct from orchestration semantics.

### 14.6 Cross-device reproducibility

Only after local conformance:

- [ ] use Vast.ai or another explicitly selected environment for cross-device NVIDIA testing;
- [ ] record device/toolchain as execution-plan/benchmark observations;
- [ ] compare accelerator output to Rust authority independently on each profile;
- [ ] do not treat cross-device speed as correctness.

### v0.8 gate

A faster GPU result is not a more correct result. No accelerator profile becomes authoritative without deterministic reference conformance.

---

# 15. Local open-weight worker protocol

## v0.9 - Candidate-Only Local Workers

- [ ] Workers receive bounded task packets, not the full governance surface.
- [ ] Candidate outputs only.
- [ ] No supervisory authority.
- [ ] No final task-completion authority.
- [ ] No provider-selection authority.
- [ ] No budget/lease-extension authority.
- [ ] Minimum necessary context and permissions.
- [ ] Structured result/evidence/confidence packet.
- [ ] Worker output is hostile/untrusted input until admitted.
- [ ] Worker cannot alter calibration/profile thresholds.
- [ ] OpenAI supervisor verifies or rejects candidate output.
- [ ] One task authority ledger remains shared rather than duplicated per worker.
- [ ] Initial adapters may target local runtimes such as llama.cpp/Ollama/vLLM without changing remote proprietary-provider policy.

### v0.9 gate

Adding workers may increase computation capacity but cannot increase governance authority or total continuation authority beyond the task's precommitted policy.

---

# 16. v1.0 - Benchmark-backed stable runtime

Before v1.0:

- [ ] Stable versioned Python/Rust protocol.
- [ ] Stable supervisor normalized protocol.
- [ ] Stable governance/orchestration/runtime/evidence separation.
- [ ] Stable progress/continuation contracts.
- [ ] Stable authority epoch/ledger semantics.
- [ ] Stable decision-sufficient compact context contract.
- [ ] Stable assurance graph.
- [ ] Stable calibration/profile versioning.
- [ ] Stable synthetic/live adapter-equivalence contract.
- [ ] Reproducible benchmark corpus.
- [ ] Cross-language conformance suite.
- [ ] Synthetic end-to-end conformance corpus.
- [ ] Live OpenAI staged integration evidence if activated.
- [ ] No semantic divergence in accepted deterministic cases.
- [ ] Documented efficiency/failure-mode report.
- [ ] Documented context/evidence reduction report.
- [ ] Formal review of core invariant set.
- [ ] Threat-model review for prompt injection, replay, credential, authority, and effect boundaries.
- [ ] Release candidate frozen to an exact commit before any formalization target is selected.

Stable does not mean feature-complete.

GPU and local workers may remain optional profiles if they have not earned stable admission.

---

# 17. Post-v1.0 formal assurance

UFT-ID 3.0 provides a useful scholarly model for keeping immutable source release authority separate from later formalization.

Target discipline:

```text
IBAE SOURCE RELEASE
        !=
LATER FORMAL PROOF LAYER
```

and:

```text
LEAN_VERIFIED
        !=
RUST_CONFORMANT
        !=
SUPERVISOR_BENCHMARKED
        !=
LIVE_DEPLOYMENT_VALIDATED
```

After a stable release is frozen:

- [ ] select only mature invariant subsets for formalization;
- [ ] pin exact source tag/commit/tree;
- [ ] pin Lean/toolchain/mathlib identities;
- [ ] preserve historical source bytes unchanged;
- [ ] store later formalization in a separate provenance layer;
- [ ] audit imported axioms;
- [ ] ban `sorry`/`admit` in accepted theorem targets;
- [ ] distinguish mathematical theorem scope from software/runtime conformance;
- [ ] build deterministic scholarly/source archives if publication is useful;
- [ ] independently verify frozen source against Git objects rather than trusting archive manifests.

Potential formal targets:

- finite lease ceiling theorem;
- no-self-extension authority theorem;
- decision-sufficient projection theorem over a finite abstract supervisor state model;
- exact floor-sampling properties;
- bounded evidence transport properties;
- identity-domain separation model;
- deterministic replay/checkpoint lineage;
- single-authority-ledger invariants.

---

# 18. Optional / deferred research

These ideas may be useful but are explicitly not prerequisites for the core stable runtime:

- `C5 x K2 x C3` orchestration/execution address geometry;
- CRT traversal/addressing;
- 30-meaningful/32-wide GPU mapping;
- GLUBALL-style exact sampling over large logical candidate spaces;
- UFT-derived exact uniform-floor sampling profile;
- GPU-side candidate scoring;
- alternate deterministic scheduling strategies;
- content-derived deterministic dispersion;
- NEXUS-style fast integer diagnostic mixers;
- grouping-neutral hierarchical compact-evidence roots;
- durable per-success-leaf inclusion proofs;
- persistent/distributed caches;
- multi-process or distributed execution;
- RES=RAG-inspired proposal pressure metrics;
- bounded diversification / multitask-brake experiments;
- formal optimal-transport metrics for agent behavior;
- any learned progress classifier;
- any heuristic lease allocator.

Optional research becomes normative only through a separately reviewed contract, conformance evidence, and benchmark-backed promotion.

---

# 19. Development discipline

Every implementation PR must include:

## Roadmap phase

State the exact phase and prerequisite gate.

## Affected invariants

List:

- newly enforced;
- partially enforced;
- remaining architecture-only;
- candidate research touched.

## Identity-bearing changes

Explicitly list every new/changed canonical domain or field.

## Benchmark-only changes

State which fields/measurements remain observational.

## Calibration/profile changes

If thresholds, policy values, lease schedules, classifiers, or experimental controls change:

- identify the exact profile/version;
- explain whether this is operational or benchmark-only;
- never silently overwrite prior calibration semantics.

## Donor boundary

If adopting an idea from another project:

- identify the donor concept;
- state what is independently reimplemented;
- state what semantics are explicitly not imported;
- verify licensing/provenance compatibility before copying any source bytes.

## Verification

Include:

- Python tests;
- Rust tests;
- format/lint/Clippy;
- deterministic fixtures;
- cross-language conformance;
- synthetic end-to-end conformance where relevant;
- package build/install;
- exact head SHA;
- CI/Determinism status.

## Review loop

1. implement only the current phase;
2. run complete local verification;
3. open focused PR;
4. inspect every legitimate Codex finding;
5. fix with regressions;
6. resolve only after push;
7. rerun full verification;
8. request fresh exact-head review;
9. advance only after exact-head green/review acceptance.

Never weaken an invariant to make a review finding disappear.

---

# 20. Hard live-connection rule

No live OpenAI connection or other live external authority-bearing connection is allowed merely because adapters exist.

The required order is:

```text
1. contracts
2. invariants
3. deterministic reference semantics
4. Rust authority
5. governance
6. compact evidence
7. progress/continuation
8. decision-sufficient supervisor boundary
9. calibration/assurance/control-plane boundary
10. fully synthetic end-to-end wiring
11. adversarial synthetic corpus
12. exact-head review acceptance
13. live OpenAI with fake tools
14. selected real read-only integrations
15. separately governed effects
```

Each new live boundary must be introduced independently enough that failures can be attributed to that boundary.

Never connect multiple new trust boundaries in one release merely to make a demo work.

---

# 21. Efficiency doctrine

IBAE optimizes useful work, not merely primitive speed.

Preferred order of optimization:

```text
1. Do not ask the model to reconstruct deterministic facts.
2. Do not retain conversational history when a decision-sufficient checkpoint is enough.
3. Do not call a tool if valid evidence already exists.
4. Do not execute work if a replay-safe equivalent result already exists.
5. Do not recompute a pure deterministic intermediate if its source identities are unchanged.
6. Do not transport full successful state if bounded compact evidence is sufficient.
7. Do not expand detailed evidence unless failure/audit requires it.
8. Do not grant continuation merely because activity is occurring.
9. Do not branch/diversify work unless bounded evidence shows a likely benefit.
10. Do not use heavyweight cryptographic work for every diagnostic if a non-authoritative fast fingerprint can safely filter candidates before canonical verification.
11. Only accelerate the irreducible work after unnecessary work has been removed.
```

Efficiency claims must count the overhead introduced by IBAE itself.

---

# 22. Final project criterion

QSOL-IBAE succeeds if an OpenAI supervisor can perform more useful bounded work while spending less reasoning/context/tool capacity on deterministic plumbing and redundant operations, without weakening correctness or authority boundaries.

The mature system should be able to say, structurally and audibly:

```text
What is the task?
What evidence is authoritative?
What is merely proposed?
What is missing?
What is the current control/progress state?
What work is legal now?
What work is redundant?
What can be reused safely?
What derived facts have already been proven from this state?
What is the least-force admissible recovery?
Does this task deserve more bounded execution?
What exact authority grants that continuation?
How much continuation remains possible in total?
Can a fresh agent session resume from a compact decision-sufficient checkpoint?
Can the result be summarized without shipping all successful execution state?
Can fast diagnostics locate likely mismatch without pretending to be cryptographic proof?
Can the entire path be replayed deterministically?
Can reality be attached one trust boundary at a time without changing semantics?
```

The design principle remains:

> Use model intelligence for reasoning. Use deterministic software for bookkeeping, authority, admission, boundedness, reuse, compact evidence, replay, and execution proof.

And the deployment principle remains:

> Prove the boundary with controlled evidence first. Attach reality later.
