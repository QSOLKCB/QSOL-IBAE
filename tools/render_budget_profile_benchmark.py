"""Render the canonical observational v0.5 budget-profile benchmark."""

from ibae.canonical import canonical_json
from ibae.conformance import v0_5_budget_benchmark_fixture


if __name__ == "__main__":
    print(canonical_json(v0_5_budget_benchmark_fixture()))
