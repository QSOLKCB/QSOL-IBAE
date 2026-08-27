"""Render the canonical model-free v0.5 progress/continuation fixture."""

from ibae.canonical import canonical_json
from ibae.conformance import v0_5_reference_fixture


if __name__ == "__main__":
    print(canonical_json(v0_5_reference_fixture()))
