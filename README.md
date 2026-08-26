# QSOL-IBAE

**Invariant-Bounded Agent Execution**

An experimental, OpenAI-exclusive execution substrate for deterministic, bounded, auditable agent tool use.

> Independent project. Not affiliated with, endorsed by, or maintained by OpenAI.

## Mission

QSOL-IBAE explores whether strong execution invariants can reduce redundant tool work, detect loops early, preserve useful execution state, and increase the amount of useful work an OpenAI supervisor can complete per model turn.

The v0.x line starts intentionally small. The first objective is not to build another general agent framework. It is to prove a compact execution kernel with measurable behavior.

## v0.2 scope

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

Benchmark observations remain outside correctness authority.
```

See [ARCHITECTURE.md](ARCHITECTURE.md) and [INVARIANTS.md](INVARIANTS.md).

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

From a fresh checkout, install the package and run the current micro-benchmark with:

```bash
python -m pip install -e .
python benchmarks/basic.py
python tools/render_v0_2_fixture.py
```

Run tests with:

```bash
python -m pip install -e '.[dev]'
pytest
```

## Licensing

QSOL-IBAE is **source-available, not OSI open source**.

Anyone may inspect the implementation and use it to reproduce the science under the research grant in [LICENSE](LICENSE). Productization and commercial deployment of the implementation are reserved to **QSOL-IMC and OpenAI Parties** as defined by the license.

External code contributions are not currently accepted without a separate written contribution agreement. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Status

Experimental v0.2 pre-release reference. The governance wrapper, Rust authority runtime, continuation leases, OpenAI adapter, accelerators, and local workers remain later gated phases. No production claims are made.
