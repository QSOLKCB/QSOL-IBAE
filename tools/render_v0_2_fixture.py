"""Render the canonical model-free v0.2 orchestration fixture."""

from ibae import canonical_json
from ibae.conformance import v0_2_reference_fixture


def main() -> None:
    print(canonical_json(v0_2_reference_fixture()))


if __name__ == "__main__":
    main()
