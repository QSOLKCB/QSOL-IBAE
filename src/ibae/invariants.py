"""Pure invariant checks for bounded execution and cycle detection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .state import ExecutionState


@dataclass(frozen=True, slots=True)
class BudgetLimits:
    max_requests: int = 32
    max_executions: int = 16
    max_retries: int = 4
    max_history: int = 32

    def __post_init__(self) -> None:
        for name, value in (
            ("max_requests", self.max_requests),
            ("max_executions", self.max_executions),
            ("max_retries", self.max_retries),
            ("max_history", self.max_history),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be positive")


def budget_violations(state: ExecutionState, limits: BudgetLimits) -> tuple[str, ...]:
    violations: list[str] = []
    if state.requests > limits.max_requests:
        violations.append("request budget exceeded")
    if state.executions > limits.max_executions:
        violations.append("execution budget exceeded")
    if state.retries > limits.max_retries:
        violations.append("retry budget exceeded")
    if len(state.history) > limits.max_history:
        violations.append("history bound exceeded")
    return tuple(violations)


def detect_short_cycle(history: Sequence[str], max_period: int = 3) -> int | None:
    """Return the shortest repeated terminal period, else None.

    Two consecutive copies are sufficient to identify a terminal cycle.
    v0.1 intentionally restricts detection to small periods.
    """

    n = len(history)
    for period in range(1, max_period + 1):
        width = period * 2
        if n < width:
            continue
        if tuple(history[-width:-period]) == tuple(history[-period:]):
            return period
    return None
