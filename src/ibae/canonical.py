"""Deterministic canonicalization primitives."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


def _validate_mapping_keys(value: Any) -> None:
    """Reject mapping keys that JSON would otherwise coerce to strings.

    Canonical identity must not allow distinct Python inputs such as ``1`` and
    ``"1"`` to collapse onto the same serialized key.
    """

    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise TypeError("canonical JSON mapping keys must be strings")
            _validate_mapping_keys(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _validate_mapping_keys(nested)


def canonical_json(value: Any) -> str:
    """Serialize supported JSON values deterministically.

    NaN and Infinity are rejected because they are not portable JSON values and
    would weaken content identity. Mapping keys must already be strings; the
    JSON encoder's implicit key coercion is forbidden because it can alias
    distinct inputs.
    """

    _validate_mapping_keys(value)
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
