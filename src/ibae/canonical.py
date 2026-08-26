"""Deterministic canonicalization primitives."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> str:
    """Serialize supported JSON values deterministically.

    NaN and Infinity are rejected because they are not portable JSON values and
    would weaken content identity.
    """

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_fingerprint(value: Any) -> str:
    payload = canonical_json(value).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def canonical_tool_key(
    tool_name: str,
    arguments: Any,
    dependency_fingerprint: str,
) -> str:
    if not tool_name:
        raise ValueError("tool_name must be non-empty")
    if not dependency_fingerprint:
        raise ValueError("dependency_fingerprint must be non-empty")

    return canonical_fingerprint(
        {
            "arguments": arguments,
            "dependency_fingerprint": dependency_fingerprint,
            "tool_name": tool_name,
        }
    )
