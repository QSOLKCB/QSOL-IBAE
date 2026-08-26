"""Conformance-only Python reference for the v0.1 execution semantics.

The supported execution authority is :class:`ibae.InvariantExecutor`, which is
Rust-backed as of v0.3. This module intentionally retains the merged Python
mechanics as an independent oracle for cross-language fixtures and tests.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .cache import ObservationCache
from .canonical import canonical_fingerprint, canonical_tool_key
from .executor import BudgetExceeded, CycleDetected
from .invariants import BudgetLimits, budget_violations, detect_short_cycle
from .state import ExecutionState


class PythonReferenceExecutor:
    """The exact merged v0.1 Python behavior, never production authority."""

    def __init__(self, limits: BudgetLimits | None = None) -> None:
        self.limits = limits or BudgetLimits()
        self._cache = ObservationCache()
        self.state = ExecutionState()

    def _commit_state(self, candidate: ExecutionState) -> None:
        violations = budget_violations(candidate, self.limits)
        if violations:
            raise BudgetExceeded("; ".join(violations))
        self.state = candidate

    @staticmethod
    def _transition_fingerprint(key: str, value: Any) -> str:
        observation_fp = canonical_fingerprint(value)
        return canonical_fingerprint(
            {"observation": observation_fp, "tool_key": key}
        )

    def execute_read(
        self,
        tool_name: str,
        arguments: Any,
        dependency_fingerprint: str,
        operation: Callable[[], Any],
    ) -> Any:
        key = canonical_tool_key(tool_name, arguments, dependency_fingerprint)
        self._commit_state(self.state.with_counters(requests=1))

        hit, value = self._cache.get(key)
        if hit:
            transition_fp = self._transition_fingerprint(key, value)
            candidate = self.state.with_counters(cache_hits=1)
            candidate = candidate.append_history(
                transition_fp, self.limits.max_history
            )
            self._commit_state(candidate)
            return value

        self._commit_state(self.state.with_counters(executions=1))
        value = operation()
        transition_fp = self._transition_fingerprint(key, value)
        self._cache.put(key, value)
        self._commit_state(
            self.state.append_history(transition_fp, self.limits.max_history)
        )
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

