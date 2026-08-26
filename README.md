# QSOL-IBAE

**Invariant-Bounded Agent Execution**

An experimental, OpenAI-exclusive execution substrate for deterministic, bounded, auditable agent tool use.

> Independent project. Not affiliated with, endorsed by, or maintained by OpenAI.

## Mission

QSOL-IBAE explores whether strong execution invariants can reduce redundant tool work, detect loops early, preserve useful execution state, and increase the amount of useful work an OpenAI supervisor can complete per model turn.

The v0.x line starts intentionally small. The first objective is not to build another general agent framework. It is to prove a compact execution kernel with measurable behavior.

## v0.4 scope

The v0.1 kernel provides:

- canonical JSON and SHA-256 state identity;
- canonical read-tool call identity;
- dependency-sensitive observation reuse;
- mutation-safe cached observations;
- bounded request, execution, retry, and history budgets;
- deterministic short-cycle detection;
- an explicit OpenAI-only remote-provider policy;
- deterministic benchmark output suitable for byte comparison.

The v0.2 Python orchestration reference adds:

- canonical obligation IDs and a validated dependency DAG;
- deterministic ready sets, canonical independent-read ordering, and declared effect sequencing;
- immutable model proposals separated from admitted actions;
- orchestrator-owned replay classification and safe batch deduplication;
- persistent bounded occurrence ownership for mutations and other non-replay-safe effects;
- explicit `observed`, `derived`, `model_proposed`, and `unknown` state, with cache-delivery metadata and unadmitted model proposals excluded from authoritative correctness identity;
- versioned capability-owned semantic argument allowlists, admitted typed strategy schemas, and action, state, event, and receipt identities;
- observational proposal metadata retained outside correctness identity, with misplaced/unlisted arguments rejected structurally;
- hard-bounded consumption for every model-facing collection, 4,096-byte record text, 256-bit identity integers, and incrementally measured byte/depth/node-bounded canonical payloads;
- `IBAE-LOGICAL-CLOCK-V1` transition accounting;
- stable rejection reason codes and deterministic recovery actions;
- a compact AI-facing state projection with actionable obligation/blocker context;
- a checked-in, byte-stable model-free conformance fixture.

The accepted v0.3 Rust deterministic runtime adds:

- an opaque, in-process PyO3 session behind `IBAE-RUNTIME-PROTOCOL-V1`;
- Rust-owned exact request, actual-execution, retry, cache-hit, logical-tick, history, and cache state;
- checked integer accounting and explicit hard bounds for every resident runtime container;
- dependency-sensitive cache validation, mutation-isolated observations, and deterministic period-1-to-3 cycle detection;
- domain-separated command, session, state, and runtime-receipt identities;
- structured execution-layer rejection records with reason codes and relevant invariant IDs;
- transaction-safe full-envelope construction, exact-JSON observation semantics, and capability-ID rebinding before an admitted read can enter the cache path;
- independent Python/Rust canonical-byte, SHA-256, execution-semantic, and receipt conformance fixtures;
- a deliberately limited command family: `execute_read` and `record_retry` only.

The v0.4 implementation candidate adds deterministic governance and compact
evidence machinery above and below those accepted semantics:

- an OpenAI-only, versioned governance policy with explicit supervisor,
  orchestrator, runtime, and future candidate-worker authority classes;
- explicit `PURE_READ`, `SNAPSHOT_READ`, `VOLATILE_READ`,
  `IDEMPOTENT_MUTATION`, and `NON_IDEMPOTENT_MUTATION` tool authority;
- exact bounded binding from governed tool admissions to typed v0.2
  decisions/proposals/capabilities and onward to matching sealed v0.3 read
  receipts, including exact cache-reuse policy; current orchestration admits at
  most 64 actions per batch and the evidence protocol has a 256-authorization
  hard ceiling;
- separate domain-separated task, governance, orchestration, execution,
  execution-plan, benchmark, final, rejection, and partial receipt identities;
- fail-closed finalization that requires the admitted receipt chain, the exact
  closed three-gate registry with receipt-ID bindings, and native-sealed compact
  evidence;
- a Rust-owned streaming evidence accumulator with exact checked counters and
  no retained per-case success list;
- non-constructible native runtime/summary/receipt seals, ordered admission and
  case aggregates, and continuous first-to-last runtime session/state binding;
- a compact evidence receipt capped at 2,048 canonical UTF-8 bytes independent
  of admitted case cardinality for the declared v1 profile;
- bounded, parent-bound failure expansion and a separately labelled
  non-cryptographic regression fold that has no correctness authority;
- independent structural receipt validation and explicit limits on what the
  compact profile can establish.

The v0.4 finalizable execution profile remains deliberately narrow: governed
`PURE_READ` and `SNAPSHOT_READ` actions may cross the accepted v0.3
`execute_read` path. Sealed `record_retry` transitions may contribute exact
known-admission accounting and continuity, but cannot cover an authorized read
on their own. Volatile reads and mutations are classified and fail closed by
governance, but no effect-execution command is invented in this phase.

There are deliberately **no model calls yet**. OpenAI SDK integration comes only after the kernel invariants are independently testable.

## Architecture

```text
OpenAI supervisor
        |
        v
Governance wrapper
        |
        v
Deterministic orchestration
        |
        v
Execution runtime
        |
        v
Compact evidence plane

Benchmark observations remain outside correctness authority.
```

See [ARCHITECTURE.md](ARCHITECTURE.md), [INVARIANTS.md](INVARIANTS.md),
[RUNTIME_PROTOCOL.md](RUNTIME_PROTOCOL.md),
[GOVERNANCE_PROTOCOL.md](GOVERNANCE_PROTOCOL.md), and
[EVIDENCE_PROTOCOL.md](EVIDENCE_PROTOCOL.md).

## Provider scope

Remote proprietary model inference is intentionally scoped to **OpenAI only**. This repository does not expose a generic proprietary-provider interface.

Future local open-weight workers may be supported as subordinate computation workers. They will not receive supervisory, completion, provider-selection, or execution-budget authority.

## Benchmark philosophy

Every optimization must answer a simple question: did it reduce work without changing required semantics?

The benchmark surface records at least:

- requested tool calls;
- actual tool executions;
- cache hits;
- retries;
- completion/failure status;
- deterministic output fingerprints.

From a fresh checkout with Python 3.11+ and Rust 1.74.1+, install the package and run the current deterministic evidence with:

```bash
python -m pip install -e .
python benchmarks/basic.py
python tools/render_v0_2_fixture.py
python tools/render_v0_3_fixture.py
python tools/render_v0_4_fixture.py
python tools/stress_compact_evidence.py
```

Run both language suites with:

```bash
python -m pip install -e '.[dev]'
cargo fmt --manifest-path rust/Cargo.toml --check
cargo clippy --manifest-path rust/Cargo.toml --all-targets --locked -- -D warnings
cargo test --manifest-path rust/Cargo.toml --locked
pytest
```

## Licensing

QSOL-IBAE is **source-available, not OSI open source**.

Anyone may inspect the implementation and use it to reproduce the science under the research grant in [LICENSE](LICENSE). Productization and commercial deployment of the implementation are reserved to **QSOL-IMC and OpenAI Parties** as defined by the license.

External code contributions are not currently accepted without a separate written contribution agreement. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Status

Experimental v0.4 pre-release implementation candidate. PR #4 merged the exact
reviewed v0.3 Rust-runtime head, so v0.3 is accepted rather than pending review.
The merged v0.2 Python orchestrator remains the semantic reference above that
runtime. v0.4 adds deterministic governance/receipt contracts and bounded
evidence transport; continuation leases, live OpenAI integration, accelerators,
distributed execution, and local workers remain later gated phases. No
production, authentication, or performance claim is made.
