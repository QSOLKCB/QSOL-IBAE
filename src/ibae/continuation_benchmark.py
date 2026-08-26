"""Deterministic model-free v0.5 continuation-policy experiments.

The report is observational research.  It compares exact finite schedules but
does not grant leases, alter correctness identities, or declare one schedule
universally optimal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from .canonical import domain_fingerprint
from .continuation import (
    BudgetVector,
    ContinuationPartialReason,
    ContinuationPolicy,
    ProgressClassification,
    experimental_continuation_profile,
)

BUDGET_BENCHMARK_VERSION: Final = "IBAE-BUDGET-PROFILE-BENCHMARK-V1"
BUDGET_BENCHMARK_REPORT_ID_DOMAIN: Final = "ibae.budget-profile-benchmark-id.v1"


@dataclass(frozen=True, slots=True)
class _Scenario:
    key: str
    base_consumed: BudgetVector
    requests: tuple[BudgetVector, ...]
    progress: tuple[ProgressClassification, ...]
    material_strategy: tuple[bool, ...]
    terminal_cycle: tuple[bool, ...]
    completion_after_grants: int | None
    paraphrase: bool = False

    def __post_init__(self) -> None:
        width = len(self.requests)
        if len(self.progress) != width:
            raise ValueError("benchmark progress schedule width mismatch")
        if len(self.material_strategy) != width:
            raise ValueError("benchmark strategy schedule width mismatch")
        if len(self.terminal_cycle) != width:
            raise ValueError("benchmark cycle schedule width mismatch")


def _sum(values: tuple[BudgetVector, ...]) -> BudgetVector:
    total = BudgetVector.zero()
    for value in values:
        total = total.add_checked(value)
    return total


def _bounded_consumption(
    demand: BudgetVector, ceiling: BudgetVector
) -> BudgetVector:
    return BudgetVector(
        **{
            name: min(value, ceiling.canonical_record()[name])
            for name, value in demand.canonical_record().items()
        }
    )


def _policy(
    key: str,
    base: BudgetVector,
    schedule: tuple[BudgetVector, ...],
) -> ContinuationPolicy:
    return ContinuationPolicy(
        policy_key=f"benchmark.{key}",
        policy_version=1,
        task_profile="benchmark",
        task_profile_version=1,
        initial_budget=base,
        lease_schedule=schedule,
        total_ceiling=base.add_checked(_sum(schedule)),
        max_lease_requests=len(schedule) * 2,
        max_strategy_recoveries=1,
    )


def benchmark_policies() -> tuple[ContinuationPolicy, ...]:
    base = BudgetVector(8, 4, 2, 0, 8)
    return (
        _policy(
            "fixed_equal",
            base,
            (
                BudgetVector(4, 2, 1, 0, 4),
                BudgetVector(4, 2, 1, 0, 4),
                BudgetVector(4, 2, 1, 0, 4),
            ),
        ),
        _policy(
            "front_loaded",
            base,
            (
                BudgetVector(6, 3, 1, 0, 6),
                BudgetVector(4, 2, 1, 0, 4),
                BudgetVector(2, 1, 1, 0, 2),
            ),
        ),
        _policy(
            "geometric_candidate",
            base,
            (
                BudgetVector(7, 3, 2, 0, 7),
                BudgetVector(3, 2, 1, 0, 3),
                BudgetVector(2, 1, 0, 0, 2),
            ),
        ),
        _policy(
            "small_base_larger_recovery",
            BudgetVector(4, 2, 1, 0, 4),
            (
                BudgetVector(8, 4, 2, 0, 8),
                BudgetVector(4, 2, 1, 0, 4),
                BudgetVector(2, 1, 1, 0, 2),
            ),
        ),
    )


def _scenarios() -> tuple[_Scenario, ...]:
    none = BudgetVector.zero()
    return (
        _Scenario(
            "short_success",
            BudgetVector(2, 1, 0, 0, 1),
            (),
            (),
            (),
            (),
            0,
        ),
        _Scenario(
            "long_genuinely_progressing",
            BudgetVector(8, 4, 1, 0, 8),
            (BudgetVector(4, 2, 1, 0, 4), BudgetVector(2, 1, 0, 0, 2)),
            (
                ProgressClassification.MEASURABLE_PROGRESS,
                ProgressClassification.MEASURABLE_PROGRESS,
            ),
            (False, False),
            (False, False),
            2,
        ),
        _Scenario(
            "activity_without_progress",
            BudgetVector(8, 3, 0, 0, 8),
            (BudgetVector(2, 1, 0, 0, 2),),
            (ProgressClassification.NO_PROGRESS,),
            (False,),
            (False,),
            None,
        ),
        _Scenario(
            "periodic_loop",
            BudgetVector(8, 2, 0, 0, 8),
            (BudgetVector(2, 1, 0, 0, 2),),
            (ProgressClassification.NO_PROGRESS,),
            (False,),
            (True,),
            None,
        ),
        _Scenario(
            "material_strategy_recovery",
            BudgetVector(8, 4, 1, 0, 8),
            (BudgetVector(2, 1, 0, 0, 2),),
            (ProgressClassification.NO_PROGRESS,),
            (True,),
            (False,),
            1,
        ),
        _Scenario(
            "strategy_paraphrase",
            BudgetVector(8, 4, 1, 0, 8),
            (BudgetVector(2, 1, 0, 0, 2),),
            (ProgressClassification.NO_PROGRESS,),
            (False,),
            (False,),
            None,
            paraphrase=True,
        ),
        _Scenario(
            "cache_heavy",
            BudgetVector(8, 2, 0, 0, 8),
            (BudgetVector(4, 1, 0, 0, 4),),
            (ProgressClassification.MEASURABLE_PROGRESS,),
            (False,),
            (False,),
            1,
        ),
        _Scenario(
            "retry_heavy",
            BudgetVector(1, 0, 2, 0, 1),
            (BudgetVector(0, 0, 1, 0, 0),),
            (ProgressClassification.MEASURABLE_PROGRESS,),
            (False,),
            (False,),
            1,
        ),
        _Scenario(
            "ceiling_exhaustion",
            none,
            (),
            (),
            (),
            (),
            None,
        ),
    )


def _simulate(policy: ContinuationPolicy, scenario: _Scenario) -> dict[str, Any]:
    granted: list[BudgetVector] = []
    consumed: list[BudgetVector] = []
    progress_events = 0
    strategy_events = 0
    cycle_denials = 0
    no_progress_denials = 0
    denial_reason: str | None = None
    partial_reason: str | None = None
    completed = scenario.completion_after_grants == 0
    base_consumed = _bounded_consumption(
        scenario.base_consumed, policy.initial_budget
    )

    if scenario.key == "ceiling_exhaustion":
        requests = (*policy.lease_schedule, BudgetVector(request_delta=1))
        classifications = (ProgressClassification.MEASURABLE_PROGRESS,) * len(requests)
        strategies = (False,) * len(requests)
        cycles = (False,) * len(requests)
    else:
        requests = scenario.requests
        classifications = scenario.progress
        strategies = scenario.material_strategy
        cycles = scenario.terminal_cycle

    for index, requested in enumerate(requests):
        classification = classifications[index]
        material_strategy = strategies[index]
        cycle = cycles[index]
        progress_events += 1
        if material_strategy or scenario.paraphrase:
            strategy_events += 1
        if cycle and not material_strategy:
            cycle_denials += 1
            denial_reason = "terminal_cycle"
            break
        if scenario.paraphrase:
            denial_reason = "strategy_change_not_material"
            no_progress_denials += 1
            break
        if (
            classification not in policy.admitted_progress
            and not material_strategy
        ):
            no_progress_denials += 1
            denial_reason = "no_measurable_progress"
            break
        if len(granted) >= policy.max_leases:
            partial_reason = ContinuationPartialReason.LEASE_CEILING_EXHAUSTED.value
            break
        maximum = policy.lease_schedule[len(granted)]
        if not requested.is_within(maximum):
            denial_reason = "amount_exceeds_schedule"
            break
        granted.append(requested)
        consumed.append(requested)
        if scenario.completion_after_grants == len(granted):
            completed = True
            break

    total_granted = _sum(tuple(granted))
    unused = policy.continuation_capacity.subtract_checked(total_granted)
    if completed:
        outcome = "complete"
    elif partial_reason is not None:
        outcome = "partial"
    else:
        outcome = "denied"
    return {
        "base_budget": policy.initial_budget.canonical_record(),
        "base_budget_consumed": base_consumed.canonical_record(),
        "cycle_denials": cycle_denials,
        "denial_reason": denial_reason,
        "lease_count": len(granted),
        "lease_resources_consumed": _sum(tuple(consumed)).canonical_record(),
        "lease_resources_granted": total_granted.canonical_record(),
        "no_progress_denials": no_progress_denials,
        "partial_finalization_reason": partial_reason,
        "policy_id": policy.continuation_policy_id,
        "policy_key": policy.policy_key,
        "progress_events": progress_events,
        "scenario": scenario.key,
        "strategy_change_events": strategy_events,
        "task_outcome": outcome,
        "unused_continuation_budget": unused.canonical_record(),
    }


def run_budget_profile_benchmark() -> dict[str, Any]:
    policies = benchmark_policies()
    scenarios = _scenarios()
    named_profiles = tuple(
        experimental_continuation_profile(name)
        for name in ("tiny", "standard", "extended", "repository")
    )
    body: dict[str, Any] = {
        "benchmark_only": True,
        "correctness_authority": False,
        "named_experimental_profiles": [
            {
                "continuation_policy_id": item.continuation_policy_id,
                "policy": item.canonical_record(),
            }
            for item in named_profiles
        ],
        "policy_comparisons": [
            {
                "continuation_policy_id": item.continuation_policy_id,
                "policy": item.canonical_record(),
            }
            for item in policies
        ],
        "protocol_version": BUDGET_BENCHMARK_VERSION,
        "results": [
            _simulate(policy, scenario)
            for policy in policies
            for scenario in scenarios
        ],
        "wall_clock_in_correctness_identity": False,
    }
    return {
        **body,
        "report_id": domain_fingerprint(BUDGET_BENCHMARK_REPORT_ID_DOMAIN, body),
    }
