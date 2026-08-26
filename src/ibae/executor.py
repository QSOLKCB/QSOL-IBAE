"""Python API backed by the exact v0.3 Rust execution authority."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .invariants import BudgetLimits
from .runtime import RuntimeLimits, RuntimeReceipt, RuntimeRejected, RustRuntimeSession
from .state import ExecutionState


class BudgetExceeded(RuntimeError):
    pass


class CycleDetected(RuntimeError):
    pass


class InvariantExecutor:
    """Execute admitted deterministic reads through private Rust-owned state."""

    def __init__(self, limits: BudgetLimits | None = None) -> None:
        self.limits = limits or BudgetLimits()
        self._runtime = RustRuntimeSession(
            "invariant-executor",
            RuntimeLimits(
                max_requests=self.limits.max_requests,
                max_executions=self.limits.max_executions,
                max_retries=self.limits.max_retries,
                max_history=self.limits.max_history,
            ),
        )
        self.last_receipt: RuntimeReceipt | None = None

    @property
    def state(self) -> ExecutionState:
        snapshot = self._runtime.snapshot
        return ExecutionState(
            requests=snapshot.requests,
            executions=snapshot.executions,
            cache_hits=snapshot.cache_hits,
            retries=snapshot.retries,
            history=snapshot.history,
        )

    def execute_read(
        self,
        tool_name: str,
        arguments: Any,
        dependency_fingerprint: str,
        operation: Callable[[], Any],
    ) -> Any:
        transition = self._runtime.execute_read_transition(
            tool_name,
            arguments,
            dependency_fingerprint,
            operation,
        )
        self.last_receipt = transition.receipt
        if transition.receipt.status == "rejected":
            reason = transition.receipt.rejection_reason
            if reason in {
                "IBAE-RT-REJECT-REQUEST-BUDGET",
                "IBAE-RT-REJECT-EXECUTION-BUDGET",
            }:
                raise BudgetExceeded(reason)
            if reason == "IBAE-RT-REJECT-INVALID-OBSERVATION":
                raise ValueError(reason)
            raise RuntimeRejected(transition.receipt)
        return transition.observation

    def record_retry(self) -> None:
        transition = self._runtime.record_retry_transition()
        self.last_receipt = transition.receipt
        if transition.receipt.status == "rejected":
            if transition.receipt.rejection_reason == "IBAE-RT-REJECT-RETRY-BUDGET":
                raise BudgetExceeded(transition.receipt.rejection_reason)
            raise RuntimeRejected(transition.receipt)

    def terminal_cycle_period(self) -> int | None:
        return self._runtime.terminal_cycle_period()

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
