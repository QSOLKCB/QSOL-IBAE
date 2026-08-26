"""Deterministic v0.1 micro-benchmark."""

from __future__ import annotations

import json

from ibae import InvariantExecutor, canonical_fingerprint


def main() -> None:
    executor = InvariantExecutor()
    actual_calls = 0

    def read() -> dict[str, object]:
        nonlocal actual_calls
        actual_calls += 1
        return {"content": "immutable payload", "revision": 1}

    outputs = [
        executor.execute_read("read_file", {"path": "A"}, "commit-1", read)
        for _ in range(3)
    ]

    report = {
        "actual_operation_calls": actual_calls,
        "metrics": executor.metrics(),
        "output_fingerprint": canonical_fingerprint(outputs),
        "status": "completed",
    }
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
