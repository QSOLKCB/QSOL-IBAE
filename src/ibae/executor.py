"""Minimal invariant-bounded read executor."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .cache import ObservationCache
from .canonical import canonical_fingerprint, canonical_tool_key
from .invariants import BudgetLimits, budget_violations, detect_short_cycle
from .state import ExecutionState


class BudgetExceeded(RuntimeError):
    pass


class CycleDetected(RuntimeError):
    pass


class InvariantExecutor:
    """Execute deterministic/read-like operations behind invariant checks.

    The executor does not know about any model SDK. It is intentionally a
    substrate that a future OpenAI supervisor adapter can call.
    """

    def __init__(self, limits: BudgetLimits | None = None) -> None:
        self.limits = limits or BudgetLimits()
        self.cache = ObservationCache()
        self.state = ExecutionState()

    def _commit_state(self, candidate: ExecutionState) -> None:
        violations = budget_violations(candidate, self.limits)
        if violations:
            raise BudgetExceeded("; ".join(violations))
        self.state = candidate

    def execute_read(
        self,
        tool_name: str,
        arguments: Any,
        dependency_fingerprint: str,
        operation: Callable[[], Any],
    ) -> Any:
        key = canonical_tool_key(tool_name, arguments, dependency_fingerprint)

        requested = self.state.with_counters(requests=1)
        self._commit_state(requested)

        hit, value = self.cache.get(key)
        if hit:
            candidate = self.state.with_counters(cache_hits=1)
            candidate = candidate.append_history(key, self.limits.max_history)
            self._commit_state(candidate)
            return value

        candidate = self.state.with_counters(executions=1)
        self._commit_state(candidate)
        value = operation()
        self.cache.put(key, value)

        observation_fp = canonical_fingerprint(value)
        transition_fp = canonical_fingerprint(
            {"observation": observation_fp, "tool_key": key}
        )
        candidate = self.state.append_history(transition_fp, self.limits.max_history)
        self._commit_state(candidate)
        return value

    def record_retry(self) -> None:
        self._commit_state(self.state.with_counters(retries=1))

    def terminal_cycle_period(self) -> int | None:
        return detect_short_cycle(self.state.history)

    def assert_no_terminal_cycle(self) -> None:
        period = self.terminal_cycle_period()
        if period is not None:
            raise CycleDetected(f"terminal execution cycle detected (period={period})")

    def metrics(self) -> dict[str, int]:
        return {
            "cache_hits": self.state.cache_hits,
            "executions": self.state.executions,
            "requests": self.state.requests,
            "retries": self.state.retries,
        }
