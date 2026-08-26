"""Canonical obligation records and deterministic dependency DAG semantics."""

from __future__ import annotations

import heapq
from collections.abc import Iterable
from dataclasses import dataclass, replace
from enum import Enum

from ._records import (
    materialize_bounded_iterable,
    require_bounded_positive_int,
    require_fingerprint,
    require_symbol,
    require_text,
)
from .canonical import domain_fingerprint

OBLIGATION_ID_DOMAIN = "ibae.obligation-id.v1"
MAX_OBLIGATIONS = 128
MAX_OBLIGATION_DEPENDENCIES = MAX_OBLIGATIONS - 1


class ObligationStatus(str, Enum):
    UNSATISFIED = "unsatisfied"
    SATISFIED = "satisfied"
    BLOCKED = "blocked"


class ObligationReadiness(str, Enum):
    READY = "ready"
    DEPENDENCY_BLOCKED = "dependency_blocked"
    EXPLICITLY_BLOCKED = "explicitly_blocked"
    SATISFIED = "satisfied"


def canonical_obligation_id(key: str) -> str:
    require_symbol("obligation key", key)
    return domain_fingerprint(OBLIGATION_ID_DOMAIN, {"key": key})


@dataclass(frozen=True, slots=True)
class Obligation:
    """A stable obligation definition and its explicit current status."""

    key: str
    description: str
    dependency_ids: tuple[str, ...] = ()
    status: ObligationStatus = ObligationStatus.UNSATISFIED
    block_reason: str | None = None

    def __post_init__(self) -> None:
        require_symbol("obligation key", self.key)
        require_text("obligation description", self.description)
        if not isinstance(self.status, ObligationStatus):
            raise TypeError("status must be an ObligationStatus")

        dependencies = tuple(
            sorted(
                materialize_bounded_iterable(
                    "dependency_ids",
                    self.dependency_ids,
                    limit=MAX_OBLIGATION_DEPENDENCIES,
                )
            )
        )
        if len(dependencies) != len(set(dependencies)):
            raise ValueError("obligation dependencies must be unique")
        for dependency_id in dependencies:
            require_fingerprint("dependency id", dependency_id)
        if self.obligation_id in dependencies:
            raise ValueError("an obligation cannot depend on itself")
        object.__setattr__(self, "dependency_ids", dependencies)

        if self.status is ObligationStatus.BLOCKED:
            if self.block_reason is None:
                raise ValueError("blocked obligations require a block reason")
            require_text("block reason", self.block_reason)
        elif self.block_reason is not None:
            raise ValueError("only blocked obligations may carry a block reason")

    @property
    def obligation_id(self) -> str:
        return canonical_obligation_id(self.key)

    def canonical_record(self) -> dict[str, object]:
        return {
            "block_reason": self.block_reason,
            "dependencies": list(self.dependency_ids),
            "description": self.description,
            "key": self.key,
            "obligation_id": self.obligation_id,
            "status": self.status.value,
        }

    def with_status(
        self,
        status: ObligationStatus,
        *,
        block_reason: str | None = None,
    ) -> Obligation:
        return replace(self, status=status, block_reason=block_reason)


@dataclass(frozen=True, slots=True)
class ObligationRegistry:
    """Immutable, bounded obligation registry with a validated DAG."""

    obligations: tuple[Obligation, ...]
    max_obligations: int = MAX_OBLIGATIONS

    def __post_init__(self) -> None:
        require_bounded_positive_int(
            "max_obligations", self.max_obligations, MAX_OBLIGATIONS
        )
        supplied = materialize_bounded_iterable(
            "obligations",
            self.obligations,
            limit=self.max_obligations,
        )
        if any(not isinstance(item, Obligation) for item in supplied):
            raise TypeError("obligations must contain Obligation records")
        obligations = tuple(sorted(supplied, key=lambda item: item.obligation_id))
        if len(obligations) > self.max_obligations:
            raise ValueError("obligation registry exceeds max_obligations")

        ids = [item.obligation_id for item in obligations]
        keys = [item.key for item in obligations]
        if len(ids) != len(set(ids)) or len(keys) != len(set(keys)):
            raise ValueError("obligation keys and ids must be unique")
        known_ids = set(ids)
        for item in obligations:
            missing = sorted(set(item.dependency_ids) - known_ids)
            if missing:
                raise ValueError(
                    f"obligation {item.obligation_id} has unknown dependencies: "
                    + ",".join(missing)
                )

        object.__setattr__(self, "obligations", obligations)
        self._validate_acyclic()
        self._validate_satisfied_dependencies()

    @classmethod
    def from_iterable(
        cls,
        obligations: Iterable[Obligation],
        *,
        max_obligations: int = MAX_OBLIGATIONS,
    ) -> ObligationRegistry:
        require_bounded_positive_int(
            "max_obligations", max_obligations, MAX_OBLIGATIONS
        )
        return cls(
            materialize_bounded_iterable(
                "obligations", obligations, limit=max_obligations
            ),
            max_obligations=max_obligations,
        )

    def _by_id(self) -> dict[str, Obligation]:
        return {item.obligation_id: item for item in self.obligations}

    def _validate_acyclic(self) -> None:
        indegree = {
            item.obligation_id: len(item.dependency_ids) for item in self.obligations
        }
        dependents: dict[str, list[str]] = {
            item.obligation_id: [] for item in self.obligations
        }
        for item in self.obligations:
            for dependency_id in item.dependency_ids:
                dependents[dependency_id].append(item.obligation_id)

        ready = [item_id for item_id, degree in indegree.items() if degree == 0]
        heapq.heapify(ready)
        visited: list[str] = []
        while ready:
            item_id = heapq.heappop(ready)
            visited.append(item_id)
            for dependent_id in sorted(dependents[item_id]):
                indegree[dependent_id] -= 1
                if indegree[dependent_id] == 0:
                    heapq.heappush(ready, dependent_id)

        if len(visited) != len(self.obligations):
            unresolved = sorted(
                item_id for item_id, degree in indegree.items() if degree > 0
            )
            raise ValueError(
                "obligation dependency cycle detected: " + ",".join(unresolved)
            )

    def _validate_satisfied_dependencies(self) -> None:
        by_id = self._by_id()
        for item in self.obligations:
            if item.status is not ObligationStatus.SATISFIED:
                continue
            unsatisfied = [
                dependency_id
                for dependency_id in item.dependency_ids
                if by_id[dependency_id].status is not ObligationStatus.SATISFIED
            ]
            if unsatisfied:
                raise ValueError(
                    f"satisfied obligation {item.obligation_id} has unsatisfied "
                    "dependencies: " + ",".join(unsatisfied)
                )

    def get(self, obligation_id: str) -> Obligation:
        require_fingerprint("obligation id", obligation_id)
        try:
            return self._by_id()[obligation_id]
        except KeyError as exc:
            raise KeyError(obligation_id) from exc

    @property
    def known_ids(self) -> tuple[str, ...]:
        return tuple(item.obligation_id for item in self.obligations)

    def blocking_dependency_ids(self, obligation_id: str) -> tuple[str, ...]:
        item = self.get(obligation_id)
        by_id = self._by_id()
        return tuple(
            dependency_id
            for dependency_id in item.dependency_ids
            if by_id[dependency_id].status is not ObligationStatus.SATISFIED
        )

    def readiness(self, obligation_id: str) -> ObligationReadiness:
        item = self.get(obligation_id)
        if item.status is ObligationStatus.SATISFIED:
            return ObligationReadiness.SATISFIED
        if item.status is ObligationStatus.BLOCKED:
            return ObligationReadiness.EXPLICITLY_BLOCKED
        if self.blocking_dependency_ids(obligation_id):
            return ObligationReadiness.DEPENDENCY_BLOCKED
        return ObligationReadiness.READY

    @property
    def ready_ids(self) -> tuple[str, ...]:
        return tuple(
            item.obligation_id
            for item in self.obligations
            if self.readiness(item.obligation_id) is ObligationReadiness.READY
        )

    @property
    def topological_ids(self) -> tuple[str, ...]:
        indegree = {
            item.obligation_id: len(item.dependency_ids) for item in self.obligations
        }
        dependents: dict[str, list[str]] = {
            item.obligation_id: [] for item in self.obligations
        }
        for item in self.obligations:
            for dependency_id in item.dependency_ids:
                dependents[dependency_id].append(item.obligation_id)
        ready = [item_id for item_id, degree in indegree.items() if degree == 0]
        heapq.heapify(ready)
        ordered: list[str] = []
        while ready:
            item_id = heapq.heappop(ready)
            ordered.append(item_id)
            for dependent_id in sorted(dependents[item_id]):
                indegree[dependent_id] -= 1
                if indegree[dependent_id] == 0:
                    heapq.heappush(ready, dependent_id)
        return tuple(ordered)

    def with_status(
        self,
        obligation_id: str,
        status: ObligationStatus,
        *,
        block_reason: str | None = None,
    ) -> ObligationRegistry:
        self.get(obligation_id)
        updated = tuple(
            item.with_status(status, block_reason=block_reason)
            if item.obligation_id == obligation_id
            else item
            for item in self.obligations
        )
        return ObligationRegistry(updated, max_obligations=self.max_obligations)

    def canonical_record(self) -> dict[str, object]:
        return {
            "max_obligations": self.max_obligations,
            "obligations": [item.canonical_record() for item in self.obligations],
        }
