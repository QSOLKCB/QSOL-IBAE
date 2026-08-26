"""Explicit agent-facing epistemic state classes."""

from __future__ import annotations

import heapq
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ._records import (
    CanonicalValue,
    materialize_iterable,
    require_fingerprint,
    require_positive_int,
    require_symbol,
)
from .canonical import domain_fingerprint

EPISTEMIC_RECORD_DOMAIN = "ibae.epistemic-record.v1"
EPISTEMIC_DEPENDENCY_DOMAIN = "ibae.epistemic-dependencies.v1"
_UNSET = object()


class EpistemicClass(str, Enum):
    OBSERVED = "observed"
    DERIVED = "derived"
    MODEL_PROPOSED = "model_proposed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ObservationProvenance:
    source: str
    source_identity: str
    dependency_identity: str
    reused: bool = False

    def __post_init__(self) -> None:
        require_symbol("provenance source", self.source)
        require_fingerprint("source identity", self.source_identity)
        require_fingerprint("dependency identity", self.dependency_identity)
        if not isinstance(self.reused, bool):
            raise TypeError("reused must be a boolean")

    def canonical_record(self) -> dict[str, object]:
        return {
            "dependency_identity": self.dependency_identity,
            "reused": self.reused,
            "source": self.source,
            "source_identity": self.source_identity,
        }


@dataclass(frozen=True, slots=True, init=False)
class EpistemicRecord:
    key: str
    epistemic_class: EpistemicClass
    dependencies: tuple[str, ...]
    provenance: ObservationProvenance | None
    _value: CanonicalValue | None

    def __init__(
        self,
        key: str,
        epistemic_class: EpistemicClass,
        value: Any = _UNSET,
        *,
        dependencies: Iterable[str] = (),
        provenance: ObservationProvenance | None = None,
    ) -> None:
        require_symbol("epistemic key", key)
        if not isinstance(epistemic_class, EpistemicClass):
            raise TypeError("epistemic_class must be an EpistemicClass")

        normalized_dependencies = tuple(
            sorted(materialize_iterable("epistemic dependencies", dependencies))
        )
        if len(normalized_dependencies) != len(set(normalized_dependencies)):
            raise ValueError("epistemic dependencies must be unique")
        for dependency in normalized_dependencies:
            require_symbol("epistemic dependency", dependency)
        if key in normalized_dependencies:
            raise ValueError("an epistemic record cannot depend on itself")

        if epistemic_class is EpistemicClass.UNKNOWN:
            if value is not _UNSET:
                raise ValueError("unknown epistemic records cannot carry a value")
            if provenance is not None or normalized_dependencies:
                raise ValueError(
                    "unknown epistemic records cannot carry provenance or dependencies"
                )
            canonical_value = None
        else:
            if value is _UNSET:
                raise ValueError("known epistemic records require a value")
            canonical_value = CanonicalValue.from_value(value)

        if epistemic_class is EpistemicClass.OBSERVED:
            if not isinstance(provenance, ObservationProvenance):
                raise ValueError("observed records require observation provenance")
            if normalized_dependencies:
                raise ValueError(
                    "observed dependencies belong in observation provenance"
                )
        elif provenance is not None:
            raise ValueError("only observed records may carry observation provenance")

        if epistemic_class is not EpistemicClass.DERIVED and normalized_dependencies:
            raise ValueError("only derived records may declare dependencies")

        object.__setattr__(self, "key", key)
        object.__setattr__(self, "epistemic_class", epistemic_class)
        object.__setattr__(self, "dependencies", normalized_dependencies)
        object.__setattr__(self, "provenance", provenance)
        object.__setattr__(self, "_value", canonical_value)

    @property
    def is_known(self) -> bool:
        return self.epistemic_class is not EpistemicClass.UNKNOWN

    @property
    def is_resolved(self) -> bool:
        """Whether the record may satisfy an admitted action dependency."""

        return self.epistemic_class in {
            EpistemicClass.OBSERVED,
            EpistemicClass.DERIVED,
        }

    @property
    def value(self) -> Any:
        if self._value is None:
            raise ValueError("unknown epistemic records have no value")
        return self._value.to_value()

    @property
    def record_id(self) -> str:
        return domain_fingerprint(EPISTEMIC_RECORD_DOMAIN, self.canonical_record())

    def canonical_record(self) -> dict[str, object]:
        record: dict[str, object] = {
            "dependencies": list(self.dependencies),
            "epistemic_class": self.epistemic_class.value,
            "key": self.key,
            "provenance": (
                None if self.provenance is None else self.provenance.canonical_record()
            ),
        }
        if self._value is not None:
            record["value"] = self._value.to_value()
        return record


@dataclass(frozen=True, slots=True)
class EpistemicState:
    records: tuple[EpistemicRecord, ...] = ()
    max_records: int = 256

    def __post_init__(self) -> None:
        require_positive_int("max_records", self.max_records)
        supplied = materialize_iterable("epistemic records", self.records)
        if any(not isinstance(item, EpistemicRecord) for item in supplied):
            raise TypeError("records must contain EpistemicRecord values")
        records = tuple(sorted(supplied, key=lambda item: item.key))
        if len(records) > self.max_records:
            raise ValueError("epistemic state exceeds max_records")
        keys = [record.key for record in records]
        if len(keys) != len(set(keys)):
            raise ValueError("epistemic record keys must be unique")
        known = set(keys)
        for record in records:
            missing = sorted(set(record.dependencies) - known)
            if missing:
                raise ValueError(
                    f"epistemic record {record.key} has unknown dependencies: "
                    + ",".join(missing)
                )
        object.__setattr__(self, "records", records)
        self._validate_acyclic()
        by_key = self._by_key()
        for record in records:
            unresolved = [
                dependency
                for dependency in record.dependencies
                if not by_key[dependency].is_resolved
            ]
            if unresolved:
                raise ValueError(
                    f"derived record {record.key} has unresolved dependencies: "
                    + ",".join(unresolved)
                )

    @classmethod
    def from_iterable(
        cls,
        records: Iterable[EpistemicRecord],
        *,
        max_records: int = 256,
    ) -> EpistemicState:
        return cls(tuple(records), max_records=max_records)

    def _by_key(self) -> dict[str, EpistemicRecord]:
        return {record.key: record for record in self.records}

    def _validate_acyclic(self) -> None:
        indegree = {record.key: len(record.dependencies) for record in self.records}
        dependents: dict[str, list[str]] = {record.key: [] for record in self.records}
        for record in self.records:
            for dependency in record.dependencies:
                dependents[dependency].append(record.key)
        ready = [key for key, degree in indegree.items() if degree == 0]
        heapq.heapify(ready)
        visited = 0
        while ready:
            key = heapq.heappop(ready)
            visited += 1
            for dependent in sorted(dependents[key]):
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    heapq.heappush(ready, dependent)
        if visited != len(self.records):
            unresolved = sorted(key for key, degree in indegree.items() if degree > 0)
            raise ValueError(
                "epistemic dependency cycle detected: " + ",".join(unresolved)
            )

    def get(self, key: str) -> EpistemicRecord:
        require_symbol("epistemic key", key)
        try:
            return self._by_key()[key]
        except KeyError as exc:
            raise KeyError(key) from exc

    def unresolved_keys(self, keys: Iterable[str]) -> tuple[str, ...]:
        by_key = self._by_key()
        normalized = materialize_iterable("epistemic keys", keys)
        unresolved = {
            key
            for key in normalized
            if key not in by_key or not by_key[key].is_resolved
        }
        return tuple(sorted(unresolved))

    def dependency_digest(self, keys: Iterable[str]) -> str:
        normalized = tuple(sorted(materialize_iterable("dependency keys", keys)))
        if len(normalized) != len(set(normalized)):
            raise ValueError("dependency keys must be unique")
        unresolved = self.unresolved_keys(normalized)
        if unresolved:
            raise KeyError(",".join(unresolved))
        by_key = self._by_key()
        closure = set(normalized)
        pending = list(normalized)
        while pending:
            key = pending.pop()
            for dependency in by_key[key].dependencies:
                if dependency not in closure:
                    closure.add(dependency)
                    pending.append(dependency)
        return domain_fingerprint(
            EPISTEMIC_DEPENDENCY_DOMAIN,
            [by_key[key].canonical_record() for key in sorted(closure)],
        )

    def canonical_record(self) -> dict[str, object]:
        return {
            "max_records": self.max_records,
            "records": [record.canonical_record() for record in self.records],
        }

    def projection(self) -> dict[str, list[dict[str, object]]]:
        return {
            epistemic_class.value: [
                record.canonical_record()
                for record in self.records
                if record.epistemic_class is epistemic_class
            ]
            for epistemic_class in EpistemicClass
        }
