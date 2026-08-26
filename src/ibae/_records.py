"""Internal immutable helpers for canonical orchestration records."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, TypeVar

from .canonical import canonical_json

_SYMBOL_PATTERN = re.compile(r"^[a-z][a-z0-9._:/-]{0,127}$")
_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_INVARIANT_PATTERN = re.compile(r"^IBAE-[A-Z]+-[0-9]{3}$")
_T = TypeVar("_T")

MAX_CANONICAL_VALUE_BYTES = 262_144
MAX_CANONICAL_VALUE_DEPTH = 32
MAX_CANONICAL_VALUE_NODES = 4_096
MAX_CANONICAL_COLLECTION_ITEMS = 1_024
MAX_CANONICAL_STRING_BYTES = 65_536
MAX_CANONICAL_INTEGER_BITS = 256
MAX_IDENTITY_INTEGER_BITS = 256
MAX_RECORD_TEXT_BYTES = 4_096


def bounded_utf8_length(name: str, value: str, *, limit: int) -> int:
    """Count UTF-8 bytes without allocating an encoded copy of ``value``."""

    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    require_positive_int("UTF-8 byte limit", limit)
    total = 0
    for character in value:
        codepoint = ord(character)
        if codepoint <= 0x7F:
            width = 1
        elif codepoint <= 0x7FF:
            width = 2
        elif 0xD800 <= codepoint <= 0xDFFF:
            raise ValueError(f"{name} must not contain unpaired surrogates")
        elif codepoint <= 0xFFFF:
            width = 3
        else:
            width = 4
        total += width
        if total > limit:
            raise ValueError(f"{name} exceeds maximum UTF-8 bytes {limit}")
    return total


def _bounded_json_string_length(name: str, value: str) -> int:
    """Measure an unescaped JSON string incrementally under the string cap."""

    raw_bytes = 0
    serialized_bytes = 2  # opening and closing quotes
    short_escapes = {'"', "\\", "\b", "\f", "\n", "\r", "\t"}
    for character in value:
        codepoint = ord(character)
        if codepoint <= 0x7F:
            width = 1
        elif codepoint <= 0x7FF:
            width = 2
        elif 0xD800 <= codepoint <= 0xDFFF:
            raise ValueError(f"{name} must not contain unpaired surrogates")
        elif codepoint <= 0xFFFF:
            width = 3
        else:
            width = 4
        raw_bytes += width
        if raw_bytes > MAX_CANONICAL_STRING_BYTES:
            raise ValueError(
                f"{name} exceeds maximum UTF-8 bytes "
                f"{MAX_CANONICAL_STRING_BYTES}"
            )
        if character in short_escapes:
            serialized_bytes += 2
        elif codepoint <= 0x1F:
            serialized_bytes += 6
        else:
            serialized_bytes += width
        if serialized_bytes > MAX_CANONICAL_VALUE_BYTES:
            raise ValueError(
                "canonical value exceeds maximum UTF-8 bytes "
                f"{MAX_CANONICAL_VALUE_BYTES}"
            )
    return serialized_bytes


def materialize_bounded_iterable(
    name: str,
    values: Iterable[_T],
    *,
    limit: int,
) -> tuple[_T, ...]:
    """Materialize at most ``limit`` records without exhausting an iterable."""

    require_positive_int("iterable limit", limit)
    if isinstance(values, (str, bytes, bytearray)):
        raise TypeError(f"{name} must be an iterable of records, not text")
    try:
        iterator = iter(values)
    except TypeError as exc:
        raise TypeError(f"{name} must be iterable") from exc

    materialized: list[_T] = []
    for item in iterator:
        if len(materialized) == limit:
            raise ValueError(f"{name} exceeds the hard limit of {limit}")
        materialized.append(item)
    return tuple(materialized)


def require_symbol(name: str, value: str) -> str:
    if not isinstance(value, str) or not _SYMBOL_PATTERN.fullmatch(value):
        raise ValueError(f"{name} must match {_SYMBOL_PATTERN.pattern!r}")
    return value


def require_fingerprint(name: str, value: str) -> str:
    if not isinstance(value, str) or not _FINGERPRINT_PATTERN.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase SHA-256 fingerprint")
    return value


def require_invariant_id(value: str) -> str:
    if not isinstance(value, str) or not _INVARIANT_PATTERN.fullmatch(value):
        raise ValueError("invariant id must match 'IBAE-FAMILY-NNN'")
    return value


def require_nonnegative_int(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    if value.bit_length() > MAX_IDENTITY_INTEGER_BITS:
        raise ValueError(
            f"{name} exceeds maximum bit length {MAX_IDENTITY_INTEGER_BITS}"
        )
    return value


def require_positive_int(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    if value.bit_length() > MAX_IDENTITY_INTEGER_BITS:
        raise ValueError(
            f"{name} exceeds maximum bit length {MAX_IDENTITY_INTEGER_BITS}"
        )
    return value


def require_bounded_positive_int(name: str, value: int, hard_limit: int) -> int:
    require_positive_int(name, value)
    require_positive_int("hard limit", hard_limit)
    if value > hard_limit:
        raise ValueError(f"{name} exceeds the protocol hard limit of {hard_limit}")
    return value


def require_text(name: str, value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be non-empty with no surrounding whitespace")
    bounded_utf8_length(name, value, limit=MAX_RECORD_TEXT_BYTES)
    if value != value.strip():
        raise ValueError(f"{name} must be non-empty with no surrounding whitespace")
    return value


def _normalize_bounded_json(
    value: Any,
    *,
    depth: int = 0,
    node_count: list[int] | None = None,
    byte_count: list[int] | None = None,
) -> Any:
    """Copy a JSON value while enforcing finite shape before serialization."""

    if depth > MAX_CANONICAL_VALUE_DEPTH:
        raise ValueError(
            f"canonical value exceeds maximum depth {MAX_CANONICAL_VALUE_DEPTH}"
        )
    active_count = [0] if node_count is None else node_count
    active_bytes = [0] if byte_count is None else byte_count
    active_count[0] += 1
    if active_count[0] > MAX_CANONICAL_VALUE_NODES:
        raise ValueError(
            f"canonical value exceeds maximum node count {MAX_CANONICAL_VALUE_NODES}"
        )

    def consume_bytes(amount: int) -> None:
        active_bytes[0] += amount
        if active_bytes[0] > MAX_CANONICAL_VALUE_BYTES:
            raise ValueError(
                "canonical value exceeds maximum UTF-8 bytes "
                f"{MAX_CANONICAL_VALUE_BYTES}"
            )

    if value is None or isinstance(value, bool):
        consume_bytes(len(json.dumps(value).encode("utf-8")))
        return value
    if isinstance(value, int):
        if value.bit_length() > MAX_CANONICAL_INTEGER_BITS:
            raise ValueError(
                "canonical integer exceeds maximum bit length "
                f"{MAX_CANONICAL_INTEGER_BITS}"
            )
        consume_bytes(len(str(value).encode("ascii")))
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("canonical floats must be finite")
        consume_bytes(len(json.dumps(value, allow_nan=False).encode("ascii")))
        return value
    if isinstance(value, str):
        consume_bytes(_bounded_json_string_length("canonical string", value))
        return value
    if isinstance(value, Mapping):
        items = materialize_bounded_iterable(
            "canonical mapping items",
            value.items(),
            limit=MAX_CANONICAL_COLLECTION_ITEMS,
        )
        normalized: dict[str, Any] = {}
        consume_bytes(2 + max(0, len(items) - 1))
        for item in items:
            if not isinstance(item, tuple) or len(item) != 2:
                raise TypeError("canonical mapping items must be key/value pairs")
            key, nested = item
            if not isinstance(key, str):
                raise TypeError("canonical JSON mapping keys must be strings")
            if key in normalized:
                raise ValueError("canonical mapping keys must be unique")
            consume_bytes(
                _bounded_json_string_length("canonical mapping key", key) + 1
            )
            normalized[key] = _normalize_bounded_json(
                nested,
                depth=depth + 1,
                node_count=active_count,
                byte_count=active_bytes,
            )
        return normalized
    if isinstance(value, (list, tuple)):
        items = materialize_bounded_iterable(
            "canonical sequence items",
            value,
            limit=MAX_CANONICAL_COLLECTION_ITEMS,
        )
        consume_bytes(2 + max(0, len(items) - 1))
        return [
            _normalize_bounded_json(
                item,
                depth=depth + 1,
                node_count=active_count,
                byte_count=active_bytes,
            )
            for item in items
        ]
    raise TypeError(
        "canonical values support only JSON null, booleans, finite numbers, "
        "strings, mappings, and lists"
    )


@dataclass(frozen=True, slots=True)
class CanonicalValue:
    """Mutation-isolated JSON value stored as canonical text."""

    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("canonical value text must be a string")
        bounded_utf8_length(
            "canonical value", self.text, limit=MAX_CANONICAL_VALUE_BYTES
        )
        try:
            decoded = json.loads(self.text)
        except (json.JSONDecodeError, RecursionError) as exc:
            raise ValueError("canonical value text must be valid JSON") from exc
        normalized = _normalize_bounded_json(decoded)
        if canonical_json(normalized) != self.text:
            raise ValueError("canonical value text is not in canonical form")

    @classmethod
    def from_value(cls, value: Any) -> CanonicalValue:
        normalized = _normalize_bounded_json(value)
        return cls(canonical_json(normalized))

    def to_value(self) -> Any:
        """Return a fresh caller-owned value."""

        return json.loads(self.text)
