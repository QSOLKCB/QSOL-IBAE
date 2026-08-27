from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one repair anchor, found {count}")
    target.write_text(text.replace(old, new, 1))


def append_once(path: str, marker: str, text_to_append: str) -> None:
    target = ROOT / path
    text = target.read_text()
    if marker in text:
        return
    target.write_text(text.rstrip() + "\n\n" + text_to_append.strip() + "\n")


# ---------------------------------------------------------------------------
# P2: request-cap exhaustion is a first-class bounded terminal outcome.
# ---------------------------------------------------------------------------
replace_once(
    "src/ibae/continuation.py",
    '''class ContinuationPartialReason(str, Enum):\n    LEASE_CEILING_EXHAUSTED = "lease_ceiling_exhausted"\n    NO_PROGRESS = "no_progress"\n''',
    '''class ContinuationPartialReason(str, Enum):\n    LEASE_CEILING_EXHAUSTED = "lease_ceiling_exhausted"\n    REQUEST_LIMIT_EXHAUSTED = "request_limit_exhausted"\n    NO_PROGRESS = "no_progress"\n''',
)

replace_once(
    "src/ibae/continuation.py",
    '''    progress_state: ProgressState\n    terminal_ceiling_receipt_id: str | None = None\n    pending_grant_id: str | None = None\n''',
    '''    progress_state: ProgressState\n    terminal_ceiling_receipt_id: str | None = None\n    terminal_request_limit_receipt_id: str | None = None\n    pending_grant_id: str | None = None\n''',
)

replace_once(
    "src/ibae/continuation.py",
    '''        if self.terminal_ceiling_receipt_id is not None:\n            require_fingerprint(\n                "terminal ceiling receipt id", self.terminal_ceiling_receipt_id\n            )\n            if self.progress_state is not ProgressState.LEASE_EXHAUSTED:\n                raise ValueError(\n                    "a terminal ceiling receipt requires lease-exhausted state"\n                )\n        if (self.pending_grant_id is None) != (\n''',
    '''        if self.terminal_ceiling_receipt_id is not None:\n            require_fingerprint(\n                "terminal ceiling receipt id", self.terminal_ceiling_receipt_id\n            )\n            if self.progress_state is not ProgressState.LEASE_EXHAUSTED:\n                raise ValueError(\n                    "a terminal ceiling receipt requires lease-exhausted state"\n                )\n        if self.terminal_request_limit_receipt_id is not None:\n            require_fingerprint(\n                "terminal request-limit receipt id",\n                self.terminal_request_limit_receipt_id,\n            )\n            if self.progress_state is not ProgressState.LEASE_EXHAUSTED:\n                raise ValueError(\n                    "a terminal request-limit receipt requires lease-exhausted state"\n                )\n        if (\n            self.terminal_ceiling_receipt_id is not None\n            and self.terminal_request_limit_receipt_id is not None\n        ):\n            raise ValueError("continuation state cannot carry two terminal markers")\n        if (self.pending_grant_id is None) != (\n''',
)

replace_once(
    "src/ibae/continuation.py",
    '''        if (\n            self.terminal_ceiling_receipt_id is not None\n            and self.has_pending_grant\n        ):\n            raise ValueError("terminal ceiling state cannot carry a pending grant")\n''',
    '''        if (\n            (\n                self.terminal_ceiling_receipt_id is not None\n                or self.terminal_request_limit_receipt_id is not None\n            )\n            and self.has_pending_grant\n        ):\n            raise ValueError("terminal continuation state cannot carry a pending grant")\n''',
)

replace_once(
    "src/ibae/continuation.py",
    '''        if self.terminal_ceiling_receipt_id is not None and (\n            self.leases_granted != policy.max_leases\n            or self.lease_requests != policy.max_lease_requests\n            or self.has_pending_grant\n        ):\n            raise ValueError(\n                "terminal ceiling receipt does not bind exhausted policy state"\n            )\n\n    def compact_projection''',
    '''        if self.terminal_ceiling_receipt_id is not None and (\n            self.leases_granted != policy.max_leases\n            or self.lease_requests != policy.max_lease_requests\n            or self.has_pending_grant\n        ):\n            raise ValueError(\n                "terminal ceiling receipt does not bind exhausted policy state"\n            )\n        if self.terminal_request_limit_receipt_id is not None and (\n            self.lease_requests != policy.max_lease_requests\n            or self.leases_granted >= policy.max_leases\n            or self.has_pending_grant\n        ):\n            raise ValueError(\n                "terminal request-limit receipt does not bind exhausted request capacity"\n            )\n\n    def compact_projection''',
)

replace_once(
    "src/ibae/continuation.py",
    '''            "terminal_ceiling_receipt_id": self.terminal_ceiling_receipt_id,\n        }\n\n    def _decision_lineage_record''',
    '''            "terminal_ceiling_receipt_id": self.terminal_ceiling_receipt_id,\n            "terminal_request_limit_receipt_id": (\n                self.terminal_request_limit_receipt_id\n            ),\n        }\n\n    def _decision_lineage_record''',
)

replace_once(
    "src/ibae/continuation.py",
    '''            "task_id": self.task_id,\n            "terminal_ceiling_receipt_id": self.terminal_ceiling_receipt_id,\n        }\n\n\ndef _observe_continuation_context''',
    '''            "task_id": self.task_id,\n            "terminal_ceiling_receipt_id": self.terminal_ceiling_receipt_id,\n            "terminal_request_limit_receipt_id": (\n                self.terminal_request_limit_receipt_id\n            ),\n        }\n\n\ndef _observe_continuation_context''',
)

replace_once(
    "src/ibae/continuation.py",
    '''    if reason is ContinuationPartialReason.LEASE_CEILING_EXHAUSTED:\n        if state.progress_state is not ProgressState.LEASE_EXHAUSTED:\n''',
    '''    if reason is ContinuationPartialReason.REQUEST_LIMIT_EXHAUSTED:\n        if state.progress_state is not ProgressState.LEASE_EXHAUSTED:\n            raise ValueError("partial reason does not match continuation progress state")\n        if leases_remaining != 0:\n            raise ValueError("request-limit partial requires exhausted lease capacity")\n        if state.terminal_request_limit_receipt_id is None:\n            raise ValueError(\n                "request-limit partial requires a lineage-bound request denial"\n            )\n        return\n    if reason is ContinuationPartialReason.LEASE_CEILING_EXHAUSTED:\n        if state.progress_state is not ProgressState.LEASE_EXHAUSTED:\n''',
)

replace_once(
    "src/ibae/continuation.py",
    '''        if (\n            partial_reason is ContinuationPartialReason.LEASE_CEILING_EXHAUSTED\n            and state.terminal_ceiling_receipt_id is not None\n            and relevant_receipt_id != state.terminal_ceiling_receipt_id\n        ):\n            raise ValueError(\n                "checkpoint must bind the terminal ceiling receipt"\n            )\n        effective_leases_remaining = min(\n''',
    '''        if (\n            partial_reason is ContinuationPartialReason.LEASE_CEILING_EXHAUSTED\n            and state.terminal_ceiling_receipt_id is not None\n            and relevant_receipt_id != state.terminal_ceiling_receipt_id\n        ):\n            raise ValueError(\n                "checkpoint must bind the terminal ceiling receipt"\n            )\n        if (\n            partial_reason is ContinuationPartialReason.REQUEST_LIMIT_EXHAUSTED\n            and state.terminal_request_limit_receipt_id is not None\n            and relevant_receipt_id\n            != state.terminal_request_limit_receipt_id\n        ):\n            raise ValueError(\n                "checkpoint must bind the terminal request-limit receipt"\n            )\n        effective_leases_remaining = min(\n''',
)

replace_once(
    "src/ibae/continuation.py",
    '''        if (\n            reason is ContinuationPartialReason.LEASE_CEILING_EXHAUSTED\n            and state.terminal_ceiling_receipt_id is not None\n        ):\n            terminal_receipt_id = state.terminal_ceiling_receipt_id\n            checkpoint_receipt_id = checkpoint.relevant_receipt_id\n            if type(terminal_receipt_id) is not str or type(\n                checkpoint_receipt_id\n            ) is not str:\n                raise TypeError(\n                    "terminal ceiling receipt binding must remain exact"\n                )\n            require_fingerprint("terminal ceiling receipt id", terminal_receipt_id)\n            require_fingerprint(\n                "partial checkpoint relevant receipt id", checkpoint_receipt_id\n            )\n            if checkpoint_receipt_id != terminal_receipt_id:\n                raise ValueError(\n                    "partial checkpoint no longer binds the terminal ceiling receipt"\n                )\n        _validate_semantic_partial_reason(\n''',
    '''        if (\n            reason is ContinuationPartialReason.LEASE_CEILING_EXHAUSTED\n            and state.terminal_ceiling_receipt_id is not None\n        ):\n            terminal_receipt_id = state.terminal_ceiling_receipt_id\n            checkpoint_receipt_id = checkpoint.relevant_receipt_id\n            if type(terminal_receipt_id) is not str or type(\n                checkpoint_receipt_id\n            ) is not str:\n                raise TypeError(\n                    "terminal ceiling receipt binding must remain exact"\n                )\n            require_fingerprint("terminal ceiling receipt id", terminal_receipt_id)\n            require_fingerprint(\n                "partial checkpoint relevant receipt id", checkpoint_receipt_id\n            )\n            if checkpoint_receipt_id != terminal_receipt_id:\n                raise ValueError(\n                    "partial checkpoint no longer binds the terminal ceiling receipt"\n                )\n        if (\n            reason is ContinuationPartialReason.REQUEST_LIMIT_EXHAUSTED\n            and state.terminal_request_limit_receipt_id is not None\n        ):\n            terminal_receipt_id = state.terminal_request_limit_receipt_id\n            checkpoint_receipt_id = checkpoint.relevant_receipt_id\n            if type(terminal_receipt_id) is not str or type(\n                checkpoint_receipt_id\n            ) is not str:\n                raise TypeError(\n                    "terminal request-limit receipt binding must remain exact"\n                )\n            require_fingerprint(\n                "terminal request-limit receipt id", terminal_receipt_id\n            )\n            require_fingerprint(\n                "partial checkpoint relevant receipt id", checkpoint_receipt_id\n            )\n            if checkpoint_receipt_id != terminal_receipt_id:\n                raise ValueError(\n                    "partial checkpoint no longer binds the terminal request-limit receipt"\n                )\n        _validate_semantic_partial_reason(\n''',
)

replace_once(
    "src/ibae/continuation.py",
    '''    if reason is not None:\n        terminal_ceiling_without_request_slot = (\n            reason is LeaseDenialReason.LEASE_CEILING_REACHED\n            and state.leases_granted >= policy.max_leases\n            and state.lease_requests >= policy.max_lease_requests\n        )\n        denied = _deny_continuation(\n            state,\n            request,\n            progress,\n            reason,\n            policy=policy,\n            blocking_evidence_id=blocking_id,\n            record_decision=(\n                reason is not LeaseDenialReason.UNAUTHORIZED_REQUESTER\n                and not terminal_ceiling_without_request_slot\n                and state.lease_requests < policy.max_lease_requests\n            ),\n        )\n        if not terminal_ceiling_without_request_slot:\n            return denied\n        if state.terminal_ceiling_receipt_id is not None:\n            return denied\n        return _ContinuationEvaluationResult(\n            replace(\n                state,\n                _decision_lineage_capability=None,\n                progress_state=ProgressState.LEASE_EXHAUSTED,\n                terminal_ceiling_receipt_id=denied.receipt.receipt_id,\n            ),\n            denied.receipt,\n        )\n''',
    '''    if reason is not None:\n        terminal_ceiling_without_request_slot = (\n            reason is LeaseDenialReason.LEASE_CEILING_REACHED\n            and state.leases_granted >= policy.max_leases\n            and state.lease_requests >= policy.max_lease_requests\n        )\n        terminal_request_limit_without_request_slot = (\n            reason is LeaseDenialReason.LEASE_REQUEST_LIMIT\n            and state.lease_requests >= policy.max_lease_requests\n            and state.leases_granted < policy.max_leases\n        )\n        special_terminal_without_request_slot = (\n            terminal_ceiling_without_request_slot\n            or terminal_request_limit_without_request_slot\n        )\n        denied = _deny_continuation(\n            state,\n            request,\n            progress,\n            reason,\n            policy=policy,\n            blocking_evidence_id=blocking_id,\n            record_decision=(\n                reason is not LeaseDenialReason.UNAUTHORIZED_REQUESTER\n                and not special_terminal_without_request_slot\n                and state.lease_requests < policy.max_lease_requests\n            ),\n        )\n        if not special_terminal_without_request_slot:\n            return denied\n        if terminal_ceiling_without_request_slot:\n            if state.terminal_ceiling_receipt_id is not None:\n                return denied\n            return _ContinuationEvaluationResult(\n                replace(\n                    state,\n                    _decision_lineage_capability=None,\n                    progress_state=ProgressState.LEASE_EXHAUSTED,\n                    terminal_ceiling_receipt_id=denied.receipt.receipt_id,\n                ),\n                denied.receipt,\n            )\n        if state.terminal_request_limit_receipt_id is not None:\n            return denied\n        return _ContinuationEvaluationResult(\n            replace(\n                state,\n                _decision_lineage_capability=None,\n                progress_state=ProgressState.LEASE_EXHAUSTED,\n                terminal_request_limit_receipt_id=denied.receipt.receipt_id,\n            ),\n            denied.receipt,\n        )\n''',
)

# ---------------------------------------------------------------------------
# P1: validate observer inputs before any Python authority comparison can fire.
# ---------------------------------------------------------------------------
replace_once(
    "rust/src/lib.rs",
    '''        self.binding.observer_integrity.validate(py)?;\n        let transition = self\n            .binding\n            .begin_lineage_transition(self.generation, self.canonical_lineage.as_ref())?;\n''',
    '''        self.binding.observer_integrity.validate(py)?;\n        if !orchestration_state\n            .get_type()\n            .is(self.binding.orchestration_state_type.bind(py))\n        {\n            return Err(PyValueError::new_err(\n                "continuation observer orchestration state must have the exact trusted type",\n            ));\n        }\n        if !runtime_snapshot\n            .get_type()\n            .is(self.binding.runtime_snapshot_type.bind(py))\n        {\n            return Err(PyValueError::new_err(\n                "continuation observer runtime snapshot must have the exact trusted type",\n            ));\n        }\n        if let Some(value) = progress {\n            if !value.get_type().is(self.binding.progress_record_type.bind(py)) {\n                return Err(PyValueError::new_err(\n                    "continuation observer progress must have the exact trusted type",\n                ));\n            }\n            value.call_method0("_validate_authority_fields")?;\n            self.binding.observer_integrity.validate(py)?;\n            value.call_method0("_validate_bound_claims")?;\n            self.binding.observer_integrity.validate(py)?;\n        }\n        if let Some(value) = strategy {\n            if !value\n                .get_type()\n                .is(self.binding.strategy_materialization_type.bind(py))\n            {\n                return Err(PyValueError::new_err(\n                    "continuation observer strategy must have the exact trusted type",\n                ));\n            }\n        }\n        let transition = self\n            .binding\n            .begin_lineage_transition(self.generation, self.canonical_lineage.as_ref())?;\n''',
)

# ---------------------------------------------------------------------------
# Targeted regressions.
# ---------------------------------------------------------------------------
append_once(
    "tests/test_continuation.py",
    "def test_round6_observer_rejects_transient_progress_callback_before_reseal",
    r'''
def test_round6_observer_rejects_transient_progress_callback_before_reseal():
    import ibae.continuation as continuation_module

    policy, _, task, governance, policy_receipt, runtime, _, current, progress, state = (
        _state_and_progress("standard", progressing=True)
    )
    _, granted = _request_and_decide(
        policy, policy_receipt, runtime, progress, state
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
    assert state.last_consumed_progress_id == progress.progress_id

    observed_progress = _progress(task, governance, current, current)
    original_task_id = observed_progress.task_id
    original_replace = continuation_module.replace

    class Trigger(str):
        fired = False

        def __ne__(self, other):
            type(self).fired = True

            def hostile_replace(instance, *args, **kwargs):
                continuation_module.replace = original_replace
                result = original_replace(instance, *args, **kwargs)
                if type(result) is ContinuationState:
                    return original_replace(
                        result,
                        last_consumed_progress_id=None,
                    )
                return result

            continuation_module.replace = hostile_replace
            return str.__ne__(self, other)

    object.__setattr__(
        observed_progress,
        "task_id",
        Trigger(original_task_id),
    )
    try:
        with pytest.raises(TypeError, match="must remain an exact string"):
            observe_continuation_context(
                state,
                runtime_session=runtime,
                policy=policy,
                orchestration_state=current,
                runtime_snapshot=runtime.snapshot,
                progress=observed_progress,
            )
    finally:
        continuation_module.replace = original_replace
        object.__setattr__(observed_progress, "task_id", original_task_id)

    assert Trigger.fired is False
    assert state.last_consumed_progress_id == progress.progress_id
    state._require_policy(policy)


def test_round6_request_cap_exhaustion_has_exact_semantic_partial():
    policy, _, task, governance, policy_receipt, runtime = _governed_runtime(
        "standard", session="round6-request-cap-terminal"
    )
    states = tuple(_obligation_states(total=5, satisfied=index) for index in range(3))
    stalled = _progress(task, governance, states[0], states[0])
    state = ContinuationState.create(
        policy=policy,
        policy_receipt=policy_receipt,
        runtime_session=runtime,
        orchestration_state=states[0],
        runtime_snapshot=runtime.snapshot,
        progress=stalled,
    )

    for _ in range(3):
        _, denied = _request_and_decide(
            policy, policy_receipt, runtime, stalled, state
        )
        assert denied.receipt.denial_reason is LeaseDenialReason.NO_MEASURABLE_PROGRESS
        state = denied.next_state

    progressing = _progress(task, governance, states[0], states[1])
    state = observe_continuation_context(
        state,
        runtime_session=runtime,
        policy=policy,
        orchestration_state=states[1],
        runtime_snapshot=runtime.snapshot,
        progress=progressing,
    )
    _, granted = _request_and_decide(
        policy, policy_receipt, runtime, progressing, state
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
    assert state.leases_granted == 1
    assert state.leases_granted < policy.max_leases

    terminal_progress = _progress(task, governance, states[1], states[1])
    state = observe_continuation_context(
        state,
        runtime_session=runtime,
        policy=policy,
        orchestration_state=states[1],
        runtime_snapshot=runtime.snapshot,
        progress=terminal_progress,
    )
    _, terminal = _request_and_decide(
        policy,
        policy_receipt,
        runtime,
        terminal_progress,
        state,
        requested_resources=policy.lease_schedule[state.leases_granted],
    )
    terminal_state = terminal.next_state
    assert terminal.receipt.denial_reason is LeaseDenialReason.LEASE_REQUEST_LIMIT
    assert terminal_state.lease_requests == policy.max_lease_requests
    assert terminal_state.leases_granted == 1
    assert terminal_state.progress_state is ProgressState.LEASE_EXHAUSTED
    assert (
        terminal_state.terminal_request_limit_receipt_id
        == terminal.receipt.receipt_id
    )

    checkpoint = ContinuationCheckpoint(
        state=terminal_state,
        runtime_session=runtime,
        policy=policy,
        orchestration_state=states[1],
        runtime_snapshot=runtime.snapshot,
        progress=terminal_progress,
        relevant_receipt_id=terminal.receipt.receipt_id,
        partial_reason=ContinuationPartialReason.REQUEST_LIMIT_EXHAUSTED,
    )
    partial = ContinuationPartialReceipt(
        state=terminal_state,
        checkpoint=checkpoint,
        reason=ContinuationPartialReason.REQUEST_LIMIT_EXHAUSTED,
        execution_receipt_id=terminal.receipt.receipt_id,
    )
    assert partial.reason is ContinuationPartialReason.REQUEST_LIMIT_EXHAUSTED
    assert checkpoint.leases_remaining == 0

    _, repeated = _request_and_decide(
        policy,
        policy_receipt,
        runtime,
        terminal_progress,
        terminal_state,
        requested_resources=policy.lease_schedule[terminal_state.leases_granted],
    )
    assert repeated.receipt.denial_reason is LeaseDenialReason.LEASE_REQUEST_LIMIT
    assert repeated.next_state is terminal_state
    assert (
        repeated.next_state.terminal_request_limit_receipt_id
        == terminal.receipt.receipt_id
    )
''',
)

append_once(
    "CONTINUATION_PROTOCOL.md",
    "### Request-decision-cap exhaustion",
    '''### Request-decision-cap exhaustion\n\nExhausting `max_lease_requests` while scheduled lease slots remain is a normal deterministic bounded outcome, not a watchdog event. The first post-cap request is denied as `LEASE_REQUEST_LIMIT` and its exact receipt is bound once as `terminal_request_limit_receipt_id` in native continuation lineage without incrementing the already exhausted ordinary request ledger, logical tick, decision aggregate, or retained decision history. Repeated probes are state-neutral. A semantic partial uses `request_limit_exhausted` and must cite the exact lineage-bound marker receipt.\n\nObserver resealing also validates exact progress authority fields and bound claims before the pinned Python observer can perform authority comparisons, with native integrity rechecked at those callback boundaries. Callback-bearing scalar substitutions therefore fail before they can transiently rewrite observer dependencies or consumed-progress lineage.''',
)

append_once(
    "CHANGELOG.md",
    "request-cap exhaustion now has a first-class semantic partial",
    '''- v0.5 review hardening: observer inputs are validated before authority comparisons so transient callback substitution cannot alter resealed lineage; request-cap exhaustion now has a first-class semantic partial with an exact lineage-bound terminal receipt marker instead of requiring watchdog expiry.''',
)

print("round6 repair applied")
