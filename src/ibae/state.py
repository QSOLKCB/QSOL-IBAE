"""Immutable execution state records."""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class ExecutionState:
    requests: int = 0
    executions: int = 0
    cache_hits: int = 0
    retries: int = 0
    history: tuple[str, ...] = ()

    def with_counters(
        self,
        *,
        requests: int = 0,
        executions: int = 0,
        cache_hits: int = 0,
        retries: int = 0,
    ) -> "ExecutionState":
        return replace(
            self,
            requests=self.requests + requests,
            executions=self.executions + executions,
            cache_hits=self.cache_hits + cache_hits,
            retries=self.retries + retries,
        )

    def append_history(self, fingerprint: str, max_history: int) -> "ExecutionState":
        if max_history <= 0:
            raise ValueError("max_history must be positive")
        history = (*self.history, fingerprint)[-max_history:]
        return replace(self, history=history)
