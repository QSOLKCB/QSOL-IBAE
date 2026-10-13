"""Ordinary v0.6A epoch/revocation conformance, without callback mutation."""

from __future__ import annotations

import json

import pytest

from ibae._runtime import NativeContinuationSupervisorAuthority
from ibae.canonical import canonical_json, domain_fingerprint
from ibae.continuation import (
    ContinuationRequest,
    ContinuationRequester,
    commit_lease_application,
    evaluate_continuation,
    observe_continuation_context,
)
from ibae.runtime import RUNTIME_PROTOCOL_VERSION, RustRuntimeSession
from test_continuation import (
    _authority,
    _request_and_decide,
    _state_and_progress,
)


def _native(runtime):
    return object.__getattribute__(runtime, "_RustRuntimeSession__native")


def _request(bundle):
    policy, _, _, _, _, runtime, _, _, progress, state = bundle
    return ContinuationRequest.from_state(
        state,
        progress=progress,
        requested_resources=policy.lease_schedule[0],
        requester=ContinuationRequester.OPENAI_SUPERVISOR,
        requester_authority=_authority(runtime),
    )


def test_epoch_status_is_native_read_only_canonical_and_separately_versioned():
    bundle = _state_and_progress()
    policy, _, task, governance, _, runtime, _, _, _, state = bundle
    authority = _authority(runtime)
    before_runtime = runtime.snapshot._canonical_text()
    before_state = state._decision_lineage_text()
    text = authority.authority_epoch_status()
    status = json.loads(text)
    assert status == {
        "protocol_version": "IBAE-AUTHORITY-EPOCH-V1",
        "authority_epoch": 0,
        "revoked": False,
        "task_id": task.task_id,
        "governance_id": governance.governance_id,
        "continuation_policy_id": policy.continuation_policy_id,
        "runtime_session_id": runtime.snapshot.session_id,
        "authority_epoch_status_id": status["authority_epoch_status_id"],
    }
    identity = status.pop("authority_epoch_status_id")
    assert identity == domain_fingerprint("ibae.authority-epoch-status-id.v1", status)
    assert canonical_json(json.loads(text)) == text
    assert authority.authority_epoch == 0
    assert authority.revoked is False
    assert text == _native(runtime).authority_epoch_status()
    assert text == _native(runtime).continuation_authority_status(authority, state)
    for name, value in (("authority_epoch", 12), ("revoked", False), ("binding", {})):
        with pytest.raises(AttributeError):
            setattr(authority, name, value)
    assert not hasattr(_native(runtime), "revoke_all")
    assert not hasattr(authority, "__dict__")
    with pytest.raises(TypeError):
        NativeContinuationSupervisorAuthority()
    assert runtime.snapshot._canonical_text() == before_runtime
    assert state._decision_lineage_text() == before_state


def test_revoke_all_is_terminal_idempotent_and_preserves_legacy_records():
    bundle = _state_and_progress()
    _, _, _, _, _, runtime, _, _, _, state = bundle
    request = _request(bundle)
    authority = _authority(runtime)
    before_runtime = runtime.snapshot._canonical_text()
    before_state = state._decision_lineage_text()
    before_request = request._canonical_text()
    initial_status = authority.authority_epoch_status()

    revoked = authority.revoke_all()
    assert authority.authority_epoch == 1
    assert authority.revoked is True
    assert revoked != initial_status
    assert revoked == authority.revoke_all()
    assert revoked == _native(runtime).continuation_authority_status(authority, state)
    assert revoked == _native(runtime).authority_epoch_status()
    assert runtime.snapshot._canonical_text() == before_runtime
    assert state._decision_lineage_text() == before_state
    assert request._canonical_text() == before_request
    assert "authority_epoch" not in json.loads(before_request)
    assert state._native_lineage_seal().validates(before_state)
    runtime._validate_continuation_checkpoint_snapshot(
        state._native_lineage_seal(), state, runtime.snapshot
    )
    with pytest.raises(ValueError, match="revoked or stale"):
        authority.authorize_request(before_request)


def test_revoke_all_invalidates_every_outstanding_request_seal_state_neutrally():
    bundle = _state_and_progress()
    policy, _, _, _, policy_receipt, runtime, _, _, progress, state = bundle
    requests = [_request(bundle) for _ in range(4)]
    seals = [request._native_request_authority() for request in requests]
    before_runtime = runtime.snapshot._canonical_text()
    before_state = state._decision_lineage_text()
    _authority(runtime).revoke_all()
    for request, seal in zip(requests, seals):
        assert not seal.validates(request._canonical_text())
        with pytest.raises(ValueError, match="exact native authority"):
            evaluate_continuation(
                state, request, runtime_session=runtime, policy=policy,
                policy_receipt=policy_receipt, progress=progress,
            )
        with pytest.raises(ValueError, match="revoked or stale"):
            seal.evaluate(
                _native(runtime), state, request, runtime, policy, policy_receipt, progress
            )
    assert runtime.snapshot._canonical_text() == before_runtime
    assert state._decision_lineage_text() == before_state
    assert state._native_lineage_seal().validates(before_state)


def test_revoked_pending_grant_cannot_apply_even_with_retained_native_seal():
    policy, _, _, _, policy_receipt, runtime, _, _, progress, state = (
        _state_and_progress()
    )
    _, decision = _request_and_decide(policy, policy_receipt, runtime, progress, state)
    grant = decision.receipt
    seal = grant._native_source_seal()
    grant_text = grant._canonical_text()
    pending_text = decision.next_state._decision_lineage_text()
    before = runtime.snapshot._canonical_text()
    _authority(runtime).revoke_all()
    assert not seal.validates(grant_text)
    with pytest.raises(ValueError, match="native source seal no longer matches"):
        runtime.apply_lease_transition(grant)
    with pytest.raises(ValueError, match="revoked or stale"):
        runtime.dispatch_canonical(
            canonical_json({
                "command_type": "apply_lease",
                "grant_receipt": grant.canonical_record(),
                "protocol_version": RUNTIME_PROTOCOL_VERSION,
            }),
            _lease_grant_seal=seal,
        )
    assert runtime.snapshot._canonical_text() == before
    assert grant._canonical_text() == grant_text
    assert decision.next_state._decision_lineage_text() == pending_text
    assert decision.next_state._native_lineage_seal().validates(pending_text)


def test_equal_id_duplicate_session_cannot_revoke_or_observe_original_authority():
    left = _state_and_progress()
    right = _state_and_progress()
    policy, _, _, _, policy_receipt, runtime, _, _, progress, state = left
    duplicate, duplicate_state = right[5], right[-1]
    assert runtime.snapshot.session_id == duplicate.snapshot.session_id
    assert state.continuation_state_id == duplicate_state.continuation_state_id
    assert _authority(runtime).authority_epoch_status() == _authority(duplicate).authority_epoch_status()
    with pytest.raises(ValueError, match="does not bind native session"):
        _native(runtime).continuation_authority_status(_authority(duplicate), state)
    with pytest.raises(ValueError, match="does not bind native session"):
        _native(runtime).continuation_authority_status(_authority(runtime), duplicate_state)
    _authority(duplicate).revoke_all()
    assert _authority(runtime).revoked is False
    assert _authority(runtime).authority_epoch == 0
    _, decision = _request_and_decide(policy, policy_receipt, runtime, progress, state)
    application = runtime.apply_lease(decision.receipt)
    assert application.status == "accepted"
    committed = commit_lease_application(
        decision.next_state, runtime_session=runtime, policy=policy,
        grant=decision.receipt, application=application, runtime_snapshot=runtime.snapshot,
    )
    assert committed.has_pending_grant is False


def test_revocation_blocks_observation_and_preserves_live_checkpoint_lineage():
    policy, _, _, _, _, runtime, _, current, progress, state = _state_and_progress()
    before = state._decision_lineage_text()
    snapshot = runtime.snapshot._canonical_text()
    _authority(runtime).revoke_all()
    with pytest.raises(ValueError, match="revoked or stale"):
        observe_continuation_context(
            state, runtime_session=runtime, policy=policy, orchestration_state=current,
            runtime_snapshot=runtime.snapshot, progress=progress,
        )
    assert state._native_lineage_seal().validates(before)
    assert runtime.snapshot._canonical_text() == snapshot


def test_revocation_retains_applied_limits_but_blocks_later_application_commit():
    policy, _, _, _, policy_receipt, runtime, _, _, progress, state = _state_and_progress()
    _, decision = _request_and_decide(policy, policy_receipt, runtime, progress, state)
    application = runtime.apply_lease(decision.receipt)
    applied = runtime.snapshot._canonical_text()
    pending = decision.next_state._decision_lineage_text()
    _authority(runtime).revoke_all()
    with pytest.raises(ValueError, match="revoked or stale"):
        commit_lease_application(
            decision.next_state, runtime_session=runtime, policy=policy,
            grant=decision.receipt, application=application, runtime_snapshot=runtime.snapshot,
        )
    assert runtime.snapshot._canonical_text() == applied
    assert decision.next_state._native_lineage_seal().validates(pending)
    assert runtime.snapshot.continuation.leases_applied == 1


def test_epoch_status_records_cannot_reconstruct_capability_and_stale_state_denies():
    bundle = _state_and_progress()
    policy, _, _, _, policy_receipt, runtime, _, _, progress, state = bundle
    status = json.loads(_authority(runtime).authority_epoch_status())
    with pytest.raises(TypeError, match="requester_authority is not trusted"):
        ContinuationRequest.from_state(
            state, progress=progress, requested_resources=policy.lease_schedule[0],
            requester=ContinuationRequester.OPENAI_SUPERVISOR,
            requester_authority=status,
        )
    _, decision = _request_and_decide(policy, policy_receipt, runtime, progress, state)
    with pytest.raises(ValueError, match="lineage does not match state"):
        _native(runtime).continuation_authority_status(_authority(runtime), state)
    assert _native(runtime).continuation_authority_status(
        _authority(runtime), decision.next_state
    ) == _authority(runtime).authority_epoch_status()
    with pytest.raises(ValueError, match="no continuation authority"):
        _native(RustRuntimeSession("plain-runtime")).authority_epoch_status()


def test_revocation_blocks_future_read_and_retry_dispatch_without_state_change():
    bundle = _state_and_progress()
    runtime = bundle[5]
    before = runtime.snapshot._canonical_text()
    _authority(runtime).revoke_all()
    with pytest.raises(ValueError, match="revoked or stale"):
        runtime.record_retry()
    # An ordinary canonical read command needs no operation supplied because
    # terminal authority rejection precedes execution dispatch entirely.
    with pytest.raises(ValueError, match="revoked or stale"):
        runtime.dispatch_canonical(canonical_json({
            "command_type": "execute_read",
            "protocol_version": RUNTIME_PROTOCOL_VERSION,
            "tool_name": "read",
            "arguments": {"path": "README.md"},
            "dependency_fingerprint": "a" * 64,
            "admission_id": "b" * 64,
        }))
    assert runtime.snapshot._canonical_text() == before
    assert runtime.terminal_cycle_period() is None
    # No continuation authority means this additive boundary does not apply.
    plain = RustRuntimeSession("unaffected-v03-session")
    plain.record_retry()
    assert plain.snapshot.retries == 1
    assert plain.snapshot.logical_tick == 1
