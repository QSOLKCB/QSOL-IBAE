"""Render the canonical model-free v0.4 governance/evidence fixture."""

from ibae import canonical_json
from ibae.conformance import v0_4_reference_fixture


def main() -> None:
    print(canonical_json(v0_4_reference_fixture()))


if __name__ == "__main__":
    main()
