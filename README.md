# QSOL-IBAE

**Invariant-Bounded Agent Execution**

An experimental, OpenAI-exclusive execution kernel for deterministic, bounded, auditable agent tool use.

> Independent project. Not affiliated with, endorsed by, or maintained by OpenAI.

## Mission

QSOL-IBAE explores whether strong execution invariants can reduce redundant tool work, detect loops early, preserve useful execution state, and increase the amount of useful work an OpenAI supervisor can complete per model turn.

The v0.x line starts intentionally small. The first objective is not to build another general agent framework. It is to prove a compact execution kernel with measurable behavior.

## v0.1 scope

The initial kernel provides:

- canonical JSON and SHA-256 state identity;
- canonical read-tool call identity;
- dependency-sensitive observation reuse;
- mutation-safe cached observations;
- bounded request, execution, retry, and history budgets;
- deterministic short-cycle detection;
- an explicit OpenAI-only remote-provider policy;
- deterministic benchmark output suitable for byte comparison.

There are deliberately **no model calls yet**. OpenAI SDK integration comes only after the kernel invariants are independently testable.

## Architecture

```text
User / future OpenAI supervisor
            |
            v
     proposed tool action
            |
            v
      +-------------+
      | Invariant   |
      | Gate        |
      +------+------+
             |
       +-----+-----+
       |           |
     reuse       execute
       |           |
       +-----+-----+
             |
             v
       observation
             |
             v
      canonical state
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

Experimental pre-release kernel. No production claims are made.
