"""Mutation-isolated content-addressed observation cache."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

_MISSING = object()


class ObservationCache:
    def __init__(self) -> None:
        self._values: dict[str, Any] = {}

    def get(self, key: str) -> tuple[bool, Any]:
        value = self._values.get(key, _MISSING)
        if value is _MISSING:
            return False, None
        return True, deepcopy(value)

    def put(self, key: str, value: Any) -> None:
        self._values[key] = deepcopy(value)

    def __len__(self) -> int:
        return len(self._values)
