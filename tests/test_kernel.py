from __future__ import annotations

import pytest

from ibae import (
    BudgetExceeded,
    BudgetLimits,
    InvariantExecutor,
    PolicyViolation,
    canonical_fingerprint,
    canonical_json,
    canonical_tool_key,
    detect_short_cycle,
    require_openai_remote_provider,
)


def test_canonical_json_ignores_mapping_insertion_order() -> None:
    left = {"b": 2, "a": {"y": 2, "x": 1}}
    right = {"a": {"x": 1, "y": 2}, "b": 2}
    assert canonical_json(left) == canonical_json(right)
    assert canonical_fingerprint(left) == canonical_fingerprint(right)


def test_canonical_json_rejects_non_string_mapping_keys() -> None:
    with pytest.raises(TypeError):
        canonical_json({1: "x"})
    with pytest.raises(TypeError):
        canonical_json({"nested": {False: "x"}})


def test_tool_identity_depends_on_dependency_fingerprint() -> None:
    a = canonical_tool_key("read", {"path": "x"}, "commit-a")
    b = canonical_tool_key("read", {"path": "x"}, "commit-b")
    assert a != b


def test_repeated_read_executes_once() -> None:
    executor = InvariantExecutor()
    calls = 0

    def operation() -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"value": 42}

    for _ in range(3):
        assert executor.execute_read("read", {"path": "x"}, "commit-a", operation) == {
            "value": 42
        }

    assert calls == 1
    assert executor.metrics() == {
        "cache_hits": 2,
        "executions": 1,
        "requests": 3,
        "retries": 0,
    }


def test_dependency_change_invalidates_reuse() -> None:
    executor = InvariantExecutor()
    calls = 0

    def operation() -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"call": calls}

    first = executor.execute_read("read", {"path": "x"}, "commit-a", operation)
    second = executor.execute_read("read", {"path": "x"}, "commit-b", operation)
    assert first == {"call": 1}
    assert second == {"call": 2}
    assert calls == 2


def test_cache_isolated_from_caller_mutation() -> None:
    executor = InvariantExecutor()
    result = executor.execute_read(
        "read", {"path": "x"}, "commit-a", lambda: {"items": [1, 2]}
    )
    result["items"].append(999)

    reused = executor.execute_read(
        "read", {"path": "x"}, "commit-a", lambda: pytest.fail("must not execute")
    )
    assert reused == {"items": [1, 2]}


def test_invalid_observation_never_enters_cache() -> None:
    executor = InvariantExecutor()
    calls = 0

    def invalid_then_valid() -> object:
        nonlocal calls
        calls += 1
        if calls == 1:
            return float("nan")
        return {"value": "valid"}

    with pytest.raises(ValueError):
        executor.execute_read("read", {"path": "x"}, "commit-a", invalid_then_valid)

    assert executor.execute_read(
        "read", {"path": "x"}, "commit-a", invalid_then_valid
    ) == {"value": "valid"}
    assert calls == 2
    assert executor.metrics()["cache_hits"] == 0


def test_executor_does_not_expose_public_mutable_cache() -> None:
    executor = InvariantExecutor()
    assert not hasattr(executor, "cache")


def test_request_budget_is_finite_even_for_cache_hits() -> None:
    executor = InvariantExecutor(BudgetLimits(max_requests=2, max_executions=2))
    executor.execute_read("read", {"path": "x"}, "c", lambda: 1)
    executor.execute_read("read", {"path": "x"}, "c", lambda: 1)
    with pytest.raises(BudgetExceeded):
        executor.execute_read("read", {"path": "x"}, "c", lambda: 1)


def test_execution_budget_blocks_next_cache_miss_before_operation() -> None:
    executor = InvariantExecutor(BudgetLimits(max_requests=3, max_executions=1))
    calls = 0

    def operation() -> int:
        nonlocal calls
        calls += 1
        return calls

    assert executor.execute_read("read", {"path": "a"}, "c", operation) == 1
    with pytest.raises(BudgetExceeded):
        executor.execute_read("read", {"path": "b"}, "c", operation)
    assert calls == 1
    assert executor.metrics()["executions"] == 1


def test_retry_budget_accepts_boundary_then_rejects_overflow() -> None:
    executor = InvariantExecutor(BudgetLimits(max_retries=1))
    executor.record_retry()
    assert executor.metrics()["retries"] == 1
    with pytest.raises(BudgetExceeded):
        executor.record_retry()
    assert executor.metrics()["retries"] == 1


def test_history_is_truncated_to_configured_bound() -> None:
    executor = InvariantExecutor(BudgetLimits(max_history=2))
    executor.execute_read("read", {"path": "a"}, "c", lambda: "a")
    executor.execute_read("read", {"path": "b"}, "c", lambda: "b")
    executor.execute_read("read", {"path": "c"}, "c", lambda: "c")
    assert len(executor.state.history) == 2


def test_detects_period_two_cycle() -> None:
    assert detect_short_cycle(("a", "b", "a", "b")) == 2
    assert detect_short_cycle(("a", "b", "c")) is None


def test_cache_hits_preserve_canonical_transition_cycle_identity() -> None:
    executor = InvariantExecutor()
    executor.execute_read("read", {"path": "a"}, "c", lambda: {"v": "a"})
    executor.execute_read("read", {"path": "b"}, "c", lambda: {"v": "b"})
    executor.execute_read("read", {"path": "a"}, "c", lambda: pytest.fail("cached"))
    executor.execute_read("read", {"path": "b"}, "c", lambda: pytest.fail("cached"))
    assert executor.terminal_cycle_period() == 2


def test_remote_provider_policy_is_openai_only() -> None:
    assert require_openai_remote_provider(" OpenAI ") == "openai"
    with pytest.raises(PolicyViolation):
        require_openai_remote_provider("xai")
    with pytest.raises(PolicyViolation):
        require_openai_remote_provider("anthropic")
