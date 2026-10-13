"""Render/replay offline synthetic evidence from bounded canonical input."""
import argparse
import json
from pathlib import Path

from ibae.canonical import canonical_json
from ibae.synthetic_conformance import (
    MAX_SYNTHETIC_INPUT_BYTES, MAX_SYNTHETIC_OUTPUT_BYTES, replay_synthetic_fixture, synthetic_input_fixture,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Replay actual golden input instead of default corpus")
    parser.add_argument("--inputs-only", action="store_true", help="Render the canonical input corpus")
    parser.add_argument("--verify", type=Path, help="Require output equality with this expected fixture")
    args = parser.parse_args()
    if args.input is None:
        source = synthetic_input_fixture()
    else:
        with args.input.open("rb") as stream:
            raw = stream.read(MAX_SYNTHETIC_INPUT_BYTES + 1)
        if len(raw) > MAX_SYNTHETIC_INPUT_BYTES:
            raise ValueError("golden input file exceeds bound")
        source = json.loads(raw)
        if canonical_json(source).encode() + b"\n" != raw:
            raise ValueError("golden input file must use exact canonical bytes")
    result = source if args.inputs_only else replay_synthetic_fixture(source)
    rendered = canonical_json(result) + "\n"
    if args.verify is not None:
        with args.verify.open("rb") as stream:
            expected = stream.read(MAX_SYNTHETIC_OUTPUT_BYTES + 1)
        if len(expected) > MAX_SYNTHETIC_OUTPUT_BYTES or expected != rendered.encode("utf-8"):
            raise ValueError("independent synthetic replay did not match bounded expected evidence")
    print(rendered, end="")


if __name__ == "__main__":
    main()
