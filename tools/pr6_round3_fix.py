from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one patch anchor, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


# 1. Continuation policy authority must not depend on hostile container methods.
replace_once(
    "src/ibae/continuation.py",
    '''        object.__setattr__(self, "admitted_progress", admitted)\n\n        if self.initial_budget.mutation_delta != 0:\n''',
    '''        object.__setattr__(self, "admitted_progress", admitted)\n        self._validate_authority_fields()\n\n        if self.initial_budget.mutation_delta != 0:\n''',
)
replace_once(
    "src/ibae/continuation.py",
    '''    def _validate_runtime_hard_limits(self) -> None:\n''',
    '''    def _validate_authority_fields(self) -> None:\n        if type(self.admitted_progress) is not tuple:\n            raise TypeError("admitted_progress must remain an exact tuple")\n        if self.admitted_progress != (ProgressClassification.MEASURABLE_PROGRESS,):\n            raise ValueError(\n                "only measurable_progress may independently justify continuation"\n            )\n\n    def _validate_runtime_hard_limits(self) -> None:\n''',
)
replace_once(
    "src/ibae/continuation.py",
    '''    def canonical_record(self) -> dict[str, Any]:\n        return {\n            "admitted_progress": [item.value for item in self.admitted_progress],\n''',
    '''    def canonical_record(self) -> dict[str, Any]:\n        self._validate_authority_fields()\n        return {\n            "admitted_progress": [item.value for item in self.admitted_progress],\n''',
)
replace_once(
    "src/ibae/continuation.py",
    '''        if type(policy) is not ContinuationPolicy:\n            raise TypeError("policy must be an exact ContinuationPolicy")\n        if policy.continuation_policy_id != self.continuation_policy_id:\n''',
    '''        if type(policy) is not ContinuationPolicy:\n            raise TypeError("policy must be an exact ContinuationPolicy")\n        policy._validate_authority_fields()\n        if policy.continuation_policy_id != self.continuation_policy_id:\n''',
)
replace_once(
    "src/ibae/continuation.py",
    '''    progress_admitted = (\n        progress.classification in policy.admitted_progress\n        and progress.progress_id != state.last_consumed_progress_id\n    )\n''',
    '''    progress_admitted = (\n        progress.classification is ProgressClassification.MEASURABLE_PROGRESS\n        and progress.progress_id != state.last_consumed_progress_id\n    )\n''',
)

# 2/3/6. Keep compact recovery actions honest about the live strategy/recovery state.
replace_once(
    "src/ibae/continuation.py",
    '''        recovery_actions: list[str] = []\n        if request_decisions_remaining == 0 or schedule_slots_remaining == 0:\n            recovery_actions = []\n        elif self.progress_state is ProgressState.STALLED:\n            if progress_observations_remaining > 0:\n                recovery_actions.append("provide_objective_progress")\n            if (\n                self.current_strategy_material_id is not None\n                and self.strategy_recoveries < policy.max_strategy_recoveries\n            ):\n                recovery_actions.append("propose_material_strategy_change")\n        elif self.progress_state is ProgressState.CYCLE_BLOCKED:\n            if self.strategy_recoveries < policy.max_strategy_recoveries:\n                recovery_actions.append("propose_cycle_breaking_strategy")\n        elif self.progress_state is ProgressState.STRATEGY_CHANGE_REJECTED:\n            recovery_actions.append("provide_material_semantic_difference")\n''',
    '''        recovery_actions: list[str] = []\n        strategy_recovery_available = (\n            self.current_strategy_material_id is not None\n            and self.strategy_recoveries < policy.max_strategy_recoveries\n        )\n        if request_decisions_remaining == 0 or schedule_slots_remaining == 0:\n            recovery_actions = []\n        elif self.progress_state is ProgressState.STALLED:\n            if progress_observations_remaining > 0:\n                recovery_actions.append("provide_objective_progress")\n            if strategy_recovery_available:\n                recovery_actions.append("propose_material_strategy_change")\n        elif self.progress_state is ProgressState.CYCLE_BLOCKED:\n            if strategy_recovery_available:\n                recovery_actions.append("propose_cycle_breaking_strategy")\n        elif self.progress_state is ProgressState.STRATEGY_CHANGE_REJECTED:\n            if strategy_recovery_available:\n                recovery_actions.append("provide_material_semantic_difference")\n''',
)

# 5. Give an already-exhausted schedule priority over the ordinary request cap.
replace_once(
    "src/ibae/continuation.py",
    '''    elif state.lease_requests >= policy.max_lease_requests:\n        reason = LeaseDenialReason.LEASE_REQUEST_LIMIT\n    elif request.lease_index != state.leases_granted + 1:\n        reason = LeaseDenialReason.LEASE_INDEX_MISMATCH\n    elif state.leases_granted >= policy.max_leases:\n        reason = LeaseDenialReason.LEASE_CEILING_REACHED\n''',
    '''    elif state.leases_granted >= policy.max_leases:\n        reason = LeaseDenialReason.LEASE_CEILING_REACHED\n    elif state.lease_requests >= policy.max_lease_requests:\n        reason = LeaseDenialReason.LEASE_REQUEST_LIMIT\n    elif request.lease_index != state.leases_granted + 1:\n        reason = LeaseDenialReason.LEASE_INDEX_MISMATCH\n''',
)
replace_once(
    "src/ibae/continuation.py",
    '''    if reason is not None:\n        return _deny_continuation(\n            state,\n            request,\n            progress,\n            reason,\n            policy=policy,\n            blocking_evidence_id=blocking_id,\n            record_decision=(\n                reason is not LeaseDenialReason.UNAUTHORIZED_REQUESTER\n                and state.lease_requests < policy.max_lease_requests\n            ),\n        )\n''',
    '''    if reason is not None:\n        terminal_ceiling_without_request_slot = (\n            reason is LeaseDenialReason.LEASE_CEILING_REACHED\n            and state.leases_granted >= policy.max_leases\n            and state.lease_requests >= policy.max_lease_requests\n        )\n        denied = _deny_continuation(\n            state,\n            request,\n            progress,\n            reason,\n            policy=policy,\n            blocking_evidence_id=blocking_id,\n            record_decision=(\n                reason is not LeaseDenialReason.UNAUTHORIZED_REQUESTER\n                and not terminal_ceiling_without_request_slot\n                and state.lease_requests < policy.max_lease_requests\n            ),\n        )\n        if not terminal_ceiling_without_request_slot:\n            return denied\n        if state.progress_state is ProgressState.LEASE_EXHAUSTED:\n            return denied\n        return _ContinuationEvaluationResult(\n            replace(\n                state,\n                _decision_lineage_capability=None,\n                progress_state=ProgressState.LEASE_EXHAUSTED,\n            ),\n            denied.receipt,\n        )\n''',
)
replace_once(
    "src/ibae/continuation.py",
    '''    if reason is ContinuationPartialReason.WATCHDOG_EXPIRED:\n        return\n    required_state = {\n''',
    '''    if reason is ContinuationPartialReason.WATCHDOG_EXPIRED:\n        return\n    if reason is ContinuationPartialReason.LEASE_CEILING_EXHAUSTED:\n        if state.progress_state is not ProgressState.LEASE_EXHAUSTED:\n            raise ValueError("partial reason does not match continuation progress state")\n        if leases_remaining != 0:\n            raise ValueError("lease-ceiling partial requires exhausted lease capacity")\n        return\n    required_state = {\n''',
)

# 2. Preserve exact unmet benchmark demand at the lease ceiling.
replace_once(
    "src/ibae/continuation_benchmark.py",
    '''    partial_reason: str | None = None\n    completed = scenario.completion_after_grants == 0\n''',
    '''    partial_reason: str | None = None\n    unmet_lease_demand = BudgetVector.zero()\n    completed = scenario.completion_after_grants == 0\n''',
)
replace_once(
    "src/ibae/continuation_benchmark.py",
    '''        if len(granted) >= policy.max_leases:\n            partial_reason = ContinuationPartialReason.LEASE_CEILING_EXHAUSTED.value\n            break\n''',
    '''        if len(granted) >= policy.max_leases:\n            unmet_lease_demand = requested\n            partial_reason = ContinuationPartialReason.LEASE_CEILING_EXHAUSTED.value\n            break\n''',
)
replace_once(
    "src/ibae/continuation_benchmark.py",
    '''        "unused_continuation_budget": unused.canonical_record(),\n''',
    '''        "unmet_lease_demand": unmet_lease_demand.canonical_record(),\n        "unused_continuation_budget": unused.canonical_record(),\n''',
)

# 4. Bind mutable Python closure cells in the native integrity graph.
replace_once(
    "rust/src/lib.rs",
    '''struct PythonFunctionIntegrity {\n    function: Py<PyAny>,\n    code: Py<PyAny>,\n    globals: Py<PyDict>,\n    defaults: Py<PyAny>,\n    keyword_defaults: PythonDictIntegrity,\n    closure: Py<PyAny>,\n    dependencies: Vec<PythonIdentityBinding>,\n}\n''',
    '''struct PythonClosureCellIntegrity {\n    cell: Py<PyAny>,\n    contents: Py<PyAny>,\n    nested: Option<Box<PythonIntegrityNode>>,\n}\n\nstruct PythonFunctionIntegrity {\n    function: Py<PyAny>,\n    code: Py<PyAny>,\n    globals: Py<PyDict>,\n    defaults: Py<PyAny>,\n    keyword_defaults: PythonDictIntegrity,\n    closure: Py<PyAny>,\n    closure_cells: Vec<PythonClosureCellIntegrity>,\n    dependencies: Vec<PythonIdentityBinding>,\n}\n''',
)
replace_once(
    "rust/src/lib.rs",
    '''        Ok(Self {\n            function: function.clone().unbind(),\n            code: code.unbind(),\n            globals: globals.clone().unbind(),\n            defaults: function.getattr("__defaults__")?.unbind(),\n            keyword_defaults: capture_dict_integrity(&function.getattr("__kwdefaults__")?)?,\n            closure: function.getattr("__closure__")?.unbind(),\n            dependencies,\n        })\n''',
    '''        let closure = function.getattr("__closure__")?;\n        let mut closure_cells = Vec::new();\n        if !closure.is_none() {\n            let cells = closure\n                .downcast::<PyTuple>()\n                .map_err(|_| continuation_integrity_error())?;\n            closure_cells.reserve(cells.len());\n            for cell in cells.iter() {\n                let contents = cell\n                    .getattr("cell_contents")\n                    .map_err(|_| continuation_integrity_error())?;\n                let nested = capture_integrity_node(py, &contents, visited)?;\n                closure_cells.push(PythonClosureCellIntegrity {\n                    cell: cell.unbind(),\n                    contents: contents.unbind(),\n                    nested,\n                });\n            }\n        }\n        Ok(Self {\n            function: function.clone().unbind(),\n            code: code.unbind(),\n            globals: globals.clone().unbind(),\n            defaults: function.getattr("__defaults__")?.unbind(),\n            keyword_defaults: capture_dict_integrity(&function.getattr("__kwdefaults__")?)?,\n            closure: closure.unbind(),\n            closure_cells,\n            dependencies,\n        })\n''',
)
replace_once(
    "rust/src/lib.rs",
    '''        self.keyword_defaults\n            .validate(py, &function.getattr("__kwdefaults__")?)?;\n        let globals = self.globals.bind(py);\n''',
    '''        self.keyword_defaults\n            .validate(py, &function.getattr("__kwdefaults__")?)?;\n        let closure = function.getattr("__closure__")?;\n        if closure.is_none() {\n            if !self.closure_cells.is_empty() {\n                return Err(continuation_integrity_error());\n            }\n        } else {\n            let cells = closure\n                .downcast::<PyTuple>()\n                .map_err(|_| continuation_integrity_error())?;\n            if cells.len() != self.closure_cells.len() {\n                return Err(continuation_integrity_error());\n            }\n            for (cell, expected) in cells.iter().zip(self.closure_cells.iter()) {\n                if !cell.is(expected.cell.bind(py)) {\n                    return Err(continuation_integrity_error());\n                }\n                let contents = cell\n                    .getattr("cell_contents")\n                    .map_err(|_| continuation_integrity_error())?;\n                if !contents.is(expected.contents.bind(py)) {\n                    return Err(continuation_integrity_error());\n                }\n                if let Some(nested) = &expected.nested {\n                    nested.validate(py)?;\n                }\n            }\n        }\n        let globals = self.globals.bind(py);\n''',
)

# Targeted regressions. Keeping them in the existing v0.5 test module gives
# direct access to the established exact-head harness without new test helpers.
test_path = Path("tests/test_continuation.py")
tests = test_path.read_text(encoding="utf-8")
marker = "\n\ndef test_round3_hostile_admitted_progress_container_fails_closed():\n"
if marker in tests:
    raise SystemExit("round3 regressions already present")
tests += r'''


def test_round3_hostile_admitted_progress_container_fails_closed():
    class HostileTuple(tuple):
        def __contains__(self, _item):
            return True

    policy, _, _, _, policy_receipt, runtime, _, _, progress, state = (
        _state_and_progress(progressing=False)
    )
    object.__setattr__(policy, "admitted_progress", HostileTuple(policy.admitted_progress))
    before = runtime.snapshot.canonical_record()
    with pytest.raises((TypeError, ValueError), match="admitted_progress|measurable_progress"):
        _request_and_decide(policy, policy_receipt, runtime, progress, state)
    assert runtime.snapshot.canonical_record() == before


def test_round3_strategy_change_rejected_projection_requires_live_recovery_capacity():
    policy, _, task, governance, policy_receipt, runtime = _governed_runtime(
        "standard", session="round3-strategy-projection"
    )
    orchestration, primary, alternate = _strategy_state()
    stalled = _progress(task, governance, orchestration, orchestration)
    state = ContinuationState.create(
        policy=policy,
        policy_receipt=policy_receipt,
        runtime_session=runtime,
        orchestration_state=orchestration,
        runtime_snapshot=runtime.snapshot,
        strategy=primary,
        progress=stalled,
    )
    first_change = evaluate_strategy_change(
        task_id=task.task_id,
        governance_id=governance.governance_id,
        orchestration_state=orchestration,
        prior_strategy=primary,
        proposed_strategy=alternate,
    )
    _, first = _request_and_decide(
        policy, policy_receipt, runtime, stalled, state, strategy_change=first_change
    )
    application = runtime.apply_lease(first.receipt)
    state = commit_lease_application(
        first.next_state,
        runtime_session=runtime,
        policy=policy,
        grant=first.receipt,
        application=application,
        runtime_snapshot=runtime.snapshot,
    )
    rejected_change = evaluate_strategy_change(
        task_id=task.task_id,
        governance_id=governance.governance_id,
        orchestration_state=orchestration,
        prior_strategy=alternate,
        proposed_strategy=alternate,
    )
    _, rejected = _request_and_decide(
        policy,
        policy_receipt,
        runtime,
        stalled,
        state,
        strategy_change=rejected_change,
    )
    assert rejected.next_state.progress_state is ProgressState.STRATEGY_CHANGE_REJECTED
    projection = rejected.next_state.compact_projection(policy)
    assert "provide_material_semantic_difference" not in projection["legal_recovery_actions"]
    assert projection["material_strategy_change_admissible"] is False

    policy2, _, task2, governance2, receipt2, runtime2 = _governed_runtime(
        "standard", session="round3-strategyless-rejected"
    )
    orchestration2, unrelated_prior, proposed = _strategy_state()
    stalled2 = _progress(task2, governance2, orchestration2, orchestration2)
    state2 = ContinuationState.create(
        policy=policy2,
        policy_receipt=receipt2,
        runtime_session=runtime2,
        orchestration_state=orchestration2,
        runtime_snapshot=runtime2.snapshot,
        progress=stalled2,
    )
    change2 = evaluate_strategy_change(
        task_id=task2.task_id,
        governance_id=governance2.governance_id,
        orchestration_state=orchestration2,
        prior_strategy=unrelated_prior,
        proposed_strategy=proposed,
    )
    _, rejected2 = _request_and_decide(
        policy2, receipt2, runtime2, stalled2, state2, strategy_change=change2
    )
    projection2 = rejected2.next_state.compact_projection(policy2)
    assert rejected2.next_state.progress_state is ProgressState.STRATEGY_CHANGE_REJECTED
    assert "provide_material_semantic_difference" not in projection2["legal_recovery_actions"]
    assert projection2["material_strategy_change_admissible"] is False


def test_round3_strategyless_cycle_projection_has_no_impossible_recovery():
    policy, _, task, governance, policy_receipt, runtime = _governed_runtime(
        "tiny", session="round3-strategyless-cycle"
    )
    for _ in range(2):
        runtime.execute_read(
            "read", {"path": "same"}, "cycle", lambda: {"value": "same"}
        )
    orchestration = _obligation_states(total=2)
    stalled = _progress(task, governance, orchestration, orchestration)
    state = ContinuationState.create(
        policy=policy,
        policy_receipt=policy_receipt,
        runtime_session=runtime,
        orchestration_state=orchestration,
        runtime_snapshot=runtime.snapshot,
        progress=stalled,
    )
    _, denied = _request_and_decide(
        policy, policy_receipt, runtime, stalled, state
    )
    assert denied.receipt.denial_reason is LeaseDenialReason.TERMINAL_CYCLE
    assert denied.next_state.progress_state is ProgressState.CYCLE_BLOCKED
    projection = denied.next_state.compact_projection(policy)
    assert "propose_cycle_breaking_strategy" not in projection["legal_recovery_actions"]
    assert projection["material_strategy_change_admissible"] is False


def test_round3_native_engine_rejects_mutated_closure_cell_contents():
    closure = ContinuationState.__init__.__closure__
    assert closure
    cell = closure[0]
    original = cell.cell_contents
    try:
        cell.cell_contents = object()
        with pytest.raises(ValueError, match="engine integrity"):
            _state_and_progress()
    finally:
        cell.cell_contents = original


def test_round3_terminal_ceiling_survives_exhausted_ordinary_decision_budget():
    policy, _, task, governance, policy_receipt, runtime = _governed_runtime(
        "standard", session="round3-terminal-ceiling"
    )
    states = tuple(_obligation_states(total=4, satisfied=i) for i in range(4))
    stalled = _progress(task, governance, states[0], states[0])
    state = ContinuationState.create(
        policy=policy,
        policy_receipt=policy_receipt,
        runtime_session=runtime,
        orchestration_state=states[0],
        runtime_snapshot=runtime.snapshot,
        progress=stalled,
    )
    for _ in range(2):
        _, denied = _request_and_decide(
            policy, policy_receipt, runtime, stalled, state
        )
        assert denied.receipt.denial_reason is LeaseDenialReason.NO_MEASURABLE_PROGRESS
        state = denied.next_state

    for index in range(2):
        fresh = _progress(task, governance, states[index], states[index + 1])
        state = observe_continuation_context(
            state,
            runtime_session=runtime,
            policy=policy,
            orchestration_state=states[index + 1],
            runtime_snapshot=runtime.snapshot,
            progress=fresh,
        )
        _, granted = _request_and_decide(
            policy, policy_receipt, runtime, fresh, state
        )
        application = runtime.apply_lease(granted.receipt)
        state = commit_lease_application(
            granted.next_state,
            runtime_session=runtime,
            policy=policy,
            grant=granted.receipt,
            application=application,
            runtime_snapshot=runtime.snapshot,
        )

    assert state.lease_requests == policy.max_lease_requests
    assert state.leases_granted == policy.max_leases
    terminal_progress = _progress(task, governance, states[2], states[3])
    state = observe_continuation_context(
        state,
        runtime_session=runtime,
        policy=policy,
        orchestration_state=states[3],
        runtime_snapshot=runtime.snapshot,
        progress=terminal_progress,
    )
    _, terminal = _request_and_decide(
        policy,
        policy_receipt,
        runtime,
        terminal_progress,
        state,
        requested_resources=BudgetVector(request_delta=1),
    )
    assert terminal.receipt.denial_reason is LeaseDenialReason.LEASE_CEILING_REACHED
    assert terminal.next_state.progress_state is ProgressState.LEASE_EXHAUSTED
    assert terminal.next_state.lease_requests == policy.max_lease_requests
    checkpoint = ContinuationCheckpoint(
        state=terminal.next_state,
        runtime_session=runtime,
        policy=policy,
        orchestration_state=states[3],
        runtime_snapshot=runtime.snapshot,
        progress=terminal_progress,
        partial_reason=ContinuationPartialReason.LEASE_CEILING_EXHAUSTED,
    )
    partial = ContinuationPartialReceipt(
        state=terminal.next_state,
        checkpoint=checkpoint,
        reason=ContinuationPartialReason.LEASE_CEILING_EXHAUSTED,
    )
    assert partial.canonical_record()["status"] == "partial"
    _, repeated = _request_and_decide(
        policy,
        policy_receipt,
        runtime,
        terminal_progress,
        terminal.next_state,
        requested_resources=BudgetVector(request_delta=1),
    )
    assert repeated.receipt.denial_reason is LeaseDenialReason.LEASE_CEILING_REACHED
    assert repeated.next_state.continuation_state_id == terminal.next_state.continuation_state_id
    assert repeated.next_state.lease_requests == policy.max_lease_requests


def test_round3_budget_benchmark_preserves_exact_unmet_ceiling_demand():
    report = run_budget_profile_benchmark()
    partials = [
        item
        for item in report["results"]
        if item["scenario"] == "ceiling_exhaustion"
        and item["task_outcome"] == "partial"
    ]
    assert partials
    expected = BudgetVector(request_delta=1).canonical_record()
    assert all(item["unmet_lease_demand"] == expected for item in partials)
    assert all("unmet_lease_demand" in item for item in report["results"])
'''
test_path.write_text(tests, encoding="utf-8")

print("PR #6 round-three hardening patch applied")
