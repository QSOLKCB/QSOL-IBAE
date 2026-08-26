"""Internal immutable helpers for canonical orchestration records."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, TypeVar

from .canonical import canonical_json

_SYMBOL_PATTERN = re.compile(r"^[a-z][a-z0-9._:/-]{0,127}$")
_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_INVARIANT_PATTERN = re.compile(r"^IBAE-[A-Z]+-[0-9]{3}$")
_T = TypeVar("_T")


def materialize_iterable(name: str, values: Iterable[_T]) -> tuple[_T, ...]:
    if isinstance(values, (str, bytes, bytearray)):
        raise TypeError(f"{name} must be an iterable of records, not text")
    try:
        return tuple(values)
    except TypeError as exc:
        raise TypeError(f"{name} must be iterable") from exc


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
    return value


def require_positive_int(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def require_text(name: str, value: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be non-empty with no surrounding whitespace")
    return value


@dataclass(frozen=True, slots=True)
class CanonicalValue:
    """Mutation-isolated JSON value stored as canonical text."""

    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("canonical value text must be a string")
        try:
            decoded = json.loads(self.text)
        except json.JSONDecodeError as exc:
            raise ValueError("canonical value text must be valid JSON") from exc
        if canonical_json(decoded) != self.text:
            raise ValueError("canonical value text is not in canonical form")

    @classmethod
    def from_value(cls, value: Any) -> CanonicalValue:
        return cls(canonical_json(value))

    def to_value(self) -> Any:
        """Return a fresh caller-owned value."""

        return json.loads(self.text)
