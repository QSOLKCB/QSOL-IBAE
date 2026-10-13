"""Render/replay closed native synthetic effects without external mutations."""
import argparse
import json
from pathlib import Path
from ibae.canonical import canonical_json
from ibae.effect_conformance import reference_effect_inputs, replay_effect_inputs

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs-only", action="store_true")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    inputs = reference_effect_inputs() if args.input is None else json.loads(args.input.read_text())
    record = inputs if args.inputs_only else replay_effect_inputs(inputs)
    encoded = canonical_json(record)
    if args.verify is not None and args.verify.read_text().strip() != encoded:
        raise SystemExit("synthetic effect fixture mismatch")
    print(encoded)
