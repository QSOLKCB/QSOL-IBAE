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


def test_request_budget_is_finite_even_for_cache_hits() -> None:
    executor = InvariantExecutor(BudgetLimits(max_requests=2, max_executions=2))
    executor.execute_read("read", {"path": "x"}, "c", lambda: 1)
    executor.execute_read("read", {"path": "x"}, "c", lambda: 1)
    with pytest.raises(BudgetExceeded):
        executor.execute_read("read", {"path": "x"}, "c", lambda: 1)


def test_detects_period_two_cycle() -> None:
    assert detect_short_cycle(("a", "b", "a", "b")) == 2
    assert detect_short_cycle(("a", "b", "c")) is None


def test_remote_provider_policy_is_openai_only() -> None:
    assert require_openai_remote_provider(" OpenAI ") == "openai"
    with pytest.raises(PolicyViolation):
        require_openai_remote_provider("xai")
    with pytest.raises(PolicyViolation):
        require_openai_remote_provider("anthropic")
