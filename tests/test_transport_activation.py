"""Offline transport safety tests, never actual live verification.

The explicit mocked-host integration at the end exercises production gates
through real SDK serialization and frozen HTTP responses. Its simulated stage
observations are not live provider/source evidence and are never published as
conformance proof of real live operation. No private live ledger is populated.
"""

from dataclasses import FrozenInstanceError, replace
import inspect
import pickle

import pytest

from ibae.canonical import canonical_json, domain_fingerprint
from ibae.supervisor import SupervisorProjection
from ibae.supervisor_conformance import reference_supervisor_context
from ibae.synthetic_protocol import FakeSupervisor, NormalizedProposal, ProposalKind
from ibae.transport_activation import (
    MAX_TRANSPORT_CALLS, ActivationController, ActivationError, ActivationStage,
    OperatorStageAuthorization, StageObservation, ToolProfile, TransportCallReservation,
)


@pytest.fixture(scope="module")
def projection():
    context, _, _ = reference_supervisor_context("transport.activation")
    return SupervisorProjection(context).canonical_record()


def _controller(projection, *, budget=8):
    return ActivationController(projection["sources"]["task_id"],
                                projection["sources"]["governance_id"], max_transport_calls=budget,
                                transport_policy_id="c" * 64, credential_reference_id="d" * 64)


def _authorization(controller, stage=ActivationStage.OPENAI_FAKE_TOOLS):
    profile = {ActivationStage.OPENAI_FAKE_TOOLS: ToolProfile.FAKE,
               ActivationStage.OPENAI_DETERMINISTIC_READS: ToolProfile.DETERMINISTIC_READONLY,
               ActivationStage.OPENAI_SELECTED_READS: ToolProfile.SELECTED_READONLY}[stage]
    return OperatorStageAuthorization(stage, controller.task_id, controller.governance_id,
        controller.epoch, "test.operator", profile,
        ("read.github",) if stage is ActivationStage.OPENAI_SELECTED_READS else (),
        transport_policy_id=controller.transport_policy_id, credential_reference_id=controller.credential_reference_id,
        selected_read_selection_ids=("e" * 64,) if stage is ActivationStage.OPENAI_SELECTED_READS else ())


def _stage1(projection, *, budget=8):
    controller = _controller(projection, budget=budget)
    controller.verify_synthetic_stage()
    controller.authorize(_authorization(controller))
    return controller


def _reserve(controller, projection):
    return controller.reserve_call(projection, stage=ActivationStage.OPENAI_FAKE_TOOLS,
                                   tool_profile=ToolProfile.FAKE, **_deployment(controller))


def _deployment(controller):
    return {"transport_policy_id": controller.transport_policy_id,
            "credential_reference_id": controller.credential_reference_id}


def _check(controller, reservation, projection):
    return controller.check_reservation(reservation, projection, **_deployment(controller))


def test_default_synthetic_has_no_gate_or_live_authority(projection):
    controller = _controller(projection)
    record = controller.canonical_record()
    assert controller.stage is ActivationStage.SYNTHETIC
    assert record["stage_observations"] == []
    assert record["consumed_transport_calls"] == 0
    assert record["native_authority"] is False
    assert record["live_recovery_verified"] is False
    assert record["effects_supported"] is False
    with pytest.raises(ActivationError, match="not activated"):
        _reserve(controller, projection)
    with pytest.raises(ActivationError, match="preceding stage"):
        controller.authorize(_authorization(controller))
    assert controller.call_count == 0


def test_synthetic_gate_runs_replay_and_rollback_but_never_live(projection):
    controller = _controller(projection)
    observation = controller.verify_synthetic_stage()
    record = observation.canonical_record()
    assert record["verification"] == "passed"
    assert record["live_transport_observed"] is False
    assert record["live_recovery_verified"] is False
    assert record["grants_native_authority"] is False
    assert record["final_acceptance"] is False
    assert [case["case"] for case in record["evidence"]["cases"]] == [
        "happy_path", "fake_completion_claim", "missing_evidence"]
    assert record["rollback"]["retired_reservation"] is True
    assert record["rollback"]["exhaustion_preserved"] is True
    assert record["rollback"]["budget_refunded"] is False
    assert record["rollback"]["provider_request_cancelled"] is False
    assert controller.stage is ActivationStage.SYNTHETIC
    assert controller.call_count == 0
    with pytest.raises(ActivationError):
        controller.verify_fake_tool_stage()


def test_explicit_authorization_only_advances_one_stage(projection):
    controller = _controller(projection)
    controller.verify_synthetic_stage()
    for target in (ActivationStage.OPENAI_DETERMINISTIC_READS, ActivationStage.OPENAI_SELECTED_READS):
        with pytest.raises(ActivationError, match="sequentially"):
            controller.authorize(_authorization(controller, target))
    controller.authorize(_authorization(controller))
    assert controller.stage is ActivationStage.OPENAI_FAKE_TOOLS
    assert controller.epoch == 1
    with pytest.raises(ActivationError, match="preceding stage"):
        controller.authorize(_authorization(controller, ActivationStage.OPENAI_DETERMINISTIC_READS))
    with pytest.raises(ActivationError):
        controller.verify_synthetic_stage()


@pytest.mark.parametrize("stage", [4, -1, True, "1", "effects", None])
def test_unknown_effectful_or_inexact_stages_reject(projection, stage):
    controller = _controller(projection)
    with pytest.raises((TypeError, ValueError)):
        replace(_authorization(controller), stage=stage)


@pytest.mark.parametrize("budget", [0, -1, True, 1.5, "8", MAX_TRANSPORT_CALLS + 1])
def test_budget_requires_exact_finite_positive_integer(projection, budget):
    with pytest.raises((TypeError, ValueError)):
        _controller(projection, budget=budget)


def test_operator_instruction_requires_exact_bound_profile(projection):
    controller = _controller(projection)
    auth = _authorization(controller)
    for changes in ({"tool_profile": ToolProfile.SELECTED_READONLY},
                    {"selected_read_tools": ("read.github",)},
                    {"selected_read_tools": ["read.github"]}, {"epoch": True},
                    {"operator_key": "unbounded operator words"}):
        with pytest.raises((ValueError, TypeError)):
            replace(auth, **changes)
    for names in ((), ("read.b", "read.a"), ("read.a", "read.a"), tuple(f"read.{i}" for i in range(33))):
        with pytest.raises((ValueError, TypeError)):
            replace(_authorization(controller, ActivationStage.OPENAI_SELECTED_READS), selected_read_tools=names)


def test_task_policy_and_epoch_bind_every_operator_instruction(projection):
    controller = _controller(projection)
    controller.verify_synthetic_stage()
    auth = _authorization(controller)
    for changes in ({"task_id": "a" * 64}, {"governance_id": "b" * 64}, {"epoch": 1}):
        with pytest.raises(ActivationError):
            controller.authorize(replace(auth, **changes))
    assert controller.stage is ActivationStage.SYNTHETIC
    assert controller.epoch == 0


def test_reservations_consume_budget_once_and_never_refund(projection):
    controller = _stage1(projection, budget=2)
    first = _reserve(controller, projection)
    assert first.call_index == 0
    assert first.epoch == controller.epoch
    _check(controller, first, projection)
    with pytest.raises(ActivationError, match="already outstanding"):
        _reserve(controller, projection)
    assert controller.call_count == 1
    controller.complete_call(first)
    controller.complete_call(first)
    with pytest.raises(ActivationError, match="retired"):
        _check(controller, first, projection)
    second = _reserve(controller, projection)
    controller.complete_call(second)
    assert controller.call_count == 2
    assert controller.remaining_transport_calls == 0
    with pytest.raises(ActivationError, match="exhausted"):
        _reserve(controller, projection)
    with pytest.raises(ActivationError, match="owned official"):
        controller.verify_fake_tool_stage()


def test_foreign_reservations_and_changed_projection_fail_closed(projection):
    controller = _stage1(projection)
    other = _stage1(projection)
    reservation = _reserve(controller, projection)
    with pytest.raises(ActivationError, match="foreign"):
        _check(other, reservation, projection)
    with pytest.raises(ActivationError, match="another controller"):
        other.complete_call(reservation)
    context, _, _ = reference_supervisor_context("transport.other")
    foreign_projection = SupervisorProjection(context).canonical_record()
    with pytest.raises(ActivationError, match="binding"):
        _check(controller, reservation, foreign_projection)
    changed = {**projection, "data": [{"origin": "model_output", "source_id": "a" * 64,
                                     "text": "New observed data", "control_authority": False}]}
    with pytest.raises(ActivationError, match="this projection"):
        _check(controller, reservation, changed)
    _check(controller, reservation, projection)


def test_rollback_retires_outstanding_calls_and_gates_without_refund(projection):
    controller = _stage1(projection)
    reservation = _reserve(controller, projection)
    stale_auth = _authorization(controller)
    controller.rollback()
    assert controller.stage is ActivationStage.SYNTHETIC
    assert controller.epoch == 2
    assert controller.call_count == 1
    assert controller.canonical_record()["stage_observations"] == []
    with pytest.raises(ActivationError):
        _check(controller, reservation, projection)
    controller.complete_call(reservation)  # Safe finally after cancellation.
    with pytest.raises(ActivationError, match="stale"):
        controller.authorize(stale_auth)
    with pytest.raises(ActivationError, match="preceding stage"):
        controller.authorize(_authorization(controller))
    controller.verify_synthetic_stage()
    controller.authorize(_authorization(controller))
    assert controller.call_count == 1
    assert controller.epoch == 3


def test_terminal_revocation_never_regrants_or_refunds(projection):
    controller = _stage1(projection)
    reservation = _reserve(controller, projection)
    controller.revoke()
    epoch = controller.epoch
    controller.revoke()
    assert controller.epoch == epoch
    assert controller.revoked is True
    assert controller.call_count == 1
    for operation in (lambda: _reserve(controller, projection), controller.rollback,
                      controller.verify_synthetic_stage,
                      lambda: _check(controller, reservation, projection),
                      lambda: controller.authorize(_authorization(controller))):
        with pytest.raises(ActivationError):
            operation()
    controller.complete_call(reservation)


def test_projection_declared_native_revocation_blocks_before_reservation():
    context, _, _ = reference_supervisor_context("transport.revoked")
    initial = SupervisorProjection(context).canonical_record()
    controller = _stage1(initial)
    context.supervisor_authority.revoke_all()
    revoked = SupervisorProjection(context).canonical_record()
    with pytest.raises(ActivationError, match="unavailable supervisor"):
        _reserve(controller, revoked)
    assert controller.call_count == 0
    assert controller.canonical_record()["epoch_scope"] == "python_transport_only"


def test_stage_records_are_immutable_observations_not_serializable_gates(projection):
    controller = _controller(projection)
    observation = controller.verify_synthetic_stage()
    identity = observation.observation_id
    detached = observation.canonical_record()
    detached["verification"] = "fake_success"
    assert observation.observation_id == identity
    with pytest.raises(FrozenInstanceError):
        observation._text = "{}"
    restored_observation = StageObservation(observation.canonical_record())
    other = _controller(projection)
    for claimed in (observation, restored_observation, observation.canonical_record(),
                    observation.observation_id, True, controller.canonical_record()):
        with pytest.raises(TypeError):
            other.authorize(claimed)
    with pytest.raises(ActivationError, match="preceding stage"):
        other.authorize(_authorization(other))
    assert not hasattr(ActivationController, "from_record")
    assert not hasattr(ActivationController, "restore")


def test_reservations_cannot_be_constructed_or_restored(projection):
    controller = _stage1(projection)
    reservation = _reserve(controller, projection)
    with pytest.raises(TypeError):
        TransportCallReservation()
    for value in (controller, reservation):
        with pytest.raises(TypeError, match="serialized"):
            pickle.dumps(value)
    with pytest.raises(FrozenInstanceError):
        reservation.epoch = 0
    for name, value in (("epoch", 0), ("stage", ActivationStage.OPENAI_SELECTED_READS),
                        ("remaining_transport_calls", 999)):
        with pytest.raises(AttributeError):
            setattr(controller, name, value)


def test_synthetic_normalization_cannot_supply_live_gate_proof(projection):
    controller = _stage1(projection)
    proposal = NormalizedProposal(ProposalKind.STOP, {})
    supervisor = FakeSupervisor((proposal,))
    assert supervisor.propose(projection, index=0) == proposal
    with pytest.raises(TypeError, match="official supervisor"):
        controller.propose(supervisor, projection, index=0)
    for claimed in (proposal, proposal.canonical_record(), True, "a" * 64):
        with pytest.raises(TypeError):
            controller.verify_fake_tool_stage(claimed)
        with pytest.raises(TypeError):
            controller.verify_fixture_stage(claimed)
    with pytest.raises(ActivationError, match="owned official"):
        controller.verify_fake_tool_stage()
    with pytest.raises(ActivationError):
        controller.verify_fixture_stage()
    with pytest.raises(ActivationError, match="preceding stage"):
        controller.authorize(_authorization(controller, ActivationStage.OPENAI_DETERMINISTIC_READS))
    assert all(not item["live_transport_observed"]
               for item in controller.canonical_record()["stage_observations"])


def test_no_stage_or_read_profile_can_be_selected_through_call_arguments(projection):
    controller = _stage1(projection)
    for stage, profile, names in (
        (ActivationStage.SYNTHETIC, ToolProfile.FAKE, ()),
        (ActivationStage.OPENAI_DETERMINISTIC_READS, ToolProfile.DETERMINISTIC_READONLY, ()),
        (ActivationStage.OPENAI_SELECTED_READS, ToolProfile.SELECTED_READONLY, ("read.github",)),
        (ActivationStage.OPENAI_FAKE_TOOLS, ToolProfile.FAKE, ("read.github",)),
    ):
        with pytest.raises(ActivationError):
            controller.reserve_call(projection, stage=stage, tool_profile=profile, selected_read_tools=names, **_deployment(controller))
    with pytest.raises(ActivationError, match="stage 3"):
        controller.reserve_read(task_id=controller.task_id, governance_id=controller.governance_id,
                                tool_name="read.github", selection_id="e" * 64,
                                proposal_id="a" * 64, dependency_fingerprint="b" * 64)
    assert controller.call_count == 0


def test_closed_gate_methods_have_no_caller_evidence_or_success_parameters():
    for name in ("verify_synthetic_stage", "verify_fake_tool_stage", "verify_fixture_stage",
                 "verify_selected_read_stage"):
        assert tuple(inspect.signature(getattr(ActivationController, name)).parameters) == ("self",)


def test_selected_read_stage_requires_owned_captures_never_supplied_proof(projection):
    controller = _controller(projection)
    with pytest.raises(ActivationError, match="idle stage 3"):
        controller.verify_selected_read_stage()
    for claimed in (True, {"live_verified": True}, "a" * 64):
        with pytest.raises(TypeError):
            controller.verify_selected_read_stage(claimed)
    assert controller.canonical_record()["active_stage_verification"] == "not_verified"
    assert controller.canonical_record()["selected_read_stage_verifier"] == "owned_capture_and_native_snapshot_parity"
    controller.verify_synthetic_stage()
    assert controller.canonical_record()["active_stage_verification"] == "passed"
    controller.authorize(_authorization(controller))
    assert controller.canonical_record()["active_stage_verification"] == "not_verified"


def test_exact_transport_configuration_is_bound_before_any_reservation(projection):
    controller = _stage1(projection)
    for changed in ({"transport_policy_id": "a" * 64}, {"credential_reference_id": "b" * 64}):
        binding = {**_deployment(controller), **changed}
        with pytest.raises(ActivationError, match="deployment"):
            controller.reserve_call(projection, stage=controller.stage,
                                    tool_profile=controller.tool_profile, **binding)
        assert controller.call_count == 0
    reservation = _reserve(controller, projection)
    for changed in ({"transport_policy_id": "a" * 64}, {"credential_reference_id": "b" * 64}):
        with pytest.raises(ActivationError, match="deployment"):
            controller.check_reservation(reservation, projection, **{**_deployment(controller), **changed})
    assert reservation.transport_policy_id == controller.transport_policy_id
    assert reservation.credential_reference_id == controller.credential_reference_id
    assert controller.canonical_record()["stage_observations"][0]["transport_policy_id"] == controller.transport_policy_id


def test_configuration_change_retires_old_gate_permit_and_operator_instruction(projection):
    controller = _stage1(projection)
    permit = _reserve(controller, projection)
    old_authorization = _authorization(controller)
    old_epoch = controller.epoch
    controller.configure_transport(**_deployment(controller))
    assert controller.epoch == old_epoch
    _check(controller, permit, projection)
    controller.configure_transport(transport_policy_id="a" * 64, credential_reference_id="b" * 64)
    assert controller.stage is ActivationStage.SYNTHETIC
    assert controller.epoch == old_epoch + 1
    assert controller.call_count == 1
    assert controller.canonical_record()["stage_observations"] == []
    with pytest.raises(ActivationError, match="retired"):
        _check(controller, permit, projection)
    with pytest.raises(ActivationError, match="deployment"):
        controller.authorize(old_authorization)
    with pytest.raises(ActivationError, match="preceding stage"):
        controller.authorize(_authorization(controller))
    controller.verify_synthetic_stage()
    controller.authorize(_authorization(controller))
    assert controller.call_count == 1


def test_unconfigured_offline_gate_cannot_be_reused_after_configuration(projection):
    controller = ActivationController(projection["sources"]["task_id"], projection["sources"]["governance_id"])
    controller.verify_synthetic_stage()
    controller.configure_transport(transport_policy_id="c" * 64, credential_reference_id="d" * 64)
    with pytest.raises(ActivationError, match="preceding stage"):
        controller.authorize(_authorization(controller))
    assert controller.epoch == 1
    assert controller.call_count == 0


def test_stage3_resource_selection_requires_exact_bounded_fingerprints(projection):
    controller = _controller(projection)
    auth = _authorization(controller, ActivationStage.OPENAI_SELECTED_READS)
    assert auth.selected_read_selection_ids == ("e" * 64,)
    for values in ((), ["e" * 64], ("not-a-fingerprint",), ("f" * 64, "e" * 64),
                   ("e" * 64, "e" * 64), tuple(f"{i:064x}" for i in range(33))):
        with pytest.raises((ValueError, TypeError)):
            replace(auth, selected_read_selection_ids=values)
    with pytest.raises(ValueError):
        replace(_authorization(controller), selected_read_selection_ids=("e" * 64,))


def test_verification_fence_detects_ordinary_control_changes(projection):
    controller = _stage1(projection)
    fence = controller._verification_fence()
    controller._check_verification_fence(fence)
    reservation = _reserve(controller, projection)
    controller.complete_call(reservation)
    with pytest.raises(ActivationError, match="state changed"):
        controller._check_verification_fence(fence)
    fence = controller._verification_fence()
    controller.rollback()
    with pytest.raises(ActivationError, match="state changed"):
        controller._check_verification_fence(fence)
    assert controller.canonical_record()["stage_observations"] == []


def test_offline_records_are_deterministic_and_detached(projection):
    first, second = _controller(projection), _controller(projection)
    one, two = first.verify_synthetic_stage(), second.verify_synthetic_stage()
    assert one.observation_id == two.observation_id
    assert canonical_json(first.canonical_record()) == canonical_json(second.canonical_record())
    changed = first.canonical_record()
    changed["stage"] = 3
    changed["stage_observations"].clear()
    assert first.stage is ActivationStage.SYNTHETIC
    assert len(first.canonical_record()["stage_observations"]) == 1
    assert domain_fingerprint("test.activation.v1", first.canonical_record()) == domain_fingerprint(
        "test.activation.v1", second.canonical_record())


def _selected_context(tool_name="github.repository"):
    from ibae.governance import ToolAuthorityClass, ToolPermission
    from ibae.orchestration import Capability, ReplaySafety
    from ibae.readonly_adapters import GitHubReadSelection
    from test_supervisor import _context

    selection = GitHubReadSelection("example", "project", pull_number=1)
    arguments = selection.arguments_for(tool_name)
    capability = Capability(tool_name, ReplaySafety.OCCURRENCE_SENSITIVE,
                            "Separately governed volatile HTTP capture.",
                            semantic_argument_keys=tuple(sorted(arguments)))
    context, _, _ = _context(session="selected.capture", capabilities=(capability,),
        permissions=(ToolPermission(tool_name, ToolAuthorityClass.VOLATILE_READ, False, False),))
    proposal = NormalizedProposal(ProposalKind.READ, {"proposal_key": "capture.repository",
        "tool_name": tool_name, "arguments": arguments,
        "target_obligation_keys": ["first"]})
    dependency = context.orchestration_state.epistemic_state.dependency_digest(())
    return context, selection, proposal, dependency


@pytest.mark.parametrize("changed_number", [True, 1.0])
def test_capture_action_arguments_use_canonical_equality_not_numeric_coercion(changed_number):
    from ibae.orchestration import ActionProposal
    from ibae.transport_activation import _admit_selected_read

    context, _, proposal, dependency = _selected_context("github.pull_request")
    batch = _selected_batch(context, proposal, "capture.3.7")
    original = batch.proposals[0]
    changed = ActionProposal(original.proposal_key, original.capability,
        {**original.arguments, "pull_number": changed_number}, target_obligation_ids=original.target_obligation_ids,
        occurrence_key=original.occurrence_key)
    assert changed.arguments == original.arguments  # Python conflates these values.
    with pytest.raises(ActivationError, match="differs"):
        _admit_selected_read(context, proposal, replace(batch, proposals=(changed,)), dependency, "capture.3.7")


def _selected_batch(context, proposal, occurrence):
    from ibae.obligations import canonical_obligation_id
    from ibae.orchestration import ActionProposal, ProposalBatch, ProposalOrdering, Strategy

    payload = proposal.payload
    action = ActionProposal(payload["proposal_key"], payload["tool_name"], payload["arguments"],
        target_obligation_ids=tuple(canonical_obligation_id(key) for key in payload["target_obligation_keys"]),
        occurrence_key=occurrence)
    schema = context.orchestration_state.strategy_schemas[0]
    return ProposalBatch("selected.capture", Strategy(schema.strategy_key, {}, schema=schema),
                         (action,), ordering=ProposalOrdering.DECLARED_SEQUENCE)


def test_selected_capture_recomputes_same_real_admission_for_normalized_frozen_inputs():
    from ibae.governance import ToolAuthorityClass
    from ibae.transport_activation import _admit_selected_read

    context, _, proposal, dependency = _selected_context()
    batch = _selected_batch(context, proposal, "capture.3.7")
    before = context.runtime_session.snapshot.canonical_record()
    projection, admitted, governed = _admit_selected_read(context, proposal, batch, dependency, "capture.3.7")
    copied = NormalizedProposal.from_record(proposal.canonical_record())
    frozen = FakeSupervisor((copied,)).propose(projection, index=0)
    _, replay, governed_replay = _admit_selected_read(context, frozen, batch, dependency, "capture.3.7")
    assert admitted.receipt.canonical_record() == replay.receipt.canonical_record()
    assert governed.canonical_record() == governed_replay.canonical_record()
    assert admitted.next_state.logical_tick == context.orchestration_state.logical_tick + 1
    assert governed.authority_class is ToolAuthorityClass.VOLATILE_READ
    assert governed.cache_reuse_permitted is False
    assert governed.occurrence_key == "capture.3.7"
    assert context.runtime_session.snapshot.canonical_record() == before
    # Pure admission is neither an HTTP call nor native execution evidence.
    assert governed.canonical_record()["authority_class"] == "volatile_read"


def test_selected_capture_admission_rejects_wrong_order_occurrence_dependency_and_args():
    from ibae.governance import GovernanceRejected
    from ibae.orchestration import ProposalOrdering
    from ibae.transport_activation import _admit_selected_read

    context, _, proposal, dependency = _selected_context()
    batch = _selected_batch(context, proposal, "capture.3.7")
    with pytest.raises(ActivationError, match="declared-sequence"):
        _admit_selected_read(context, proposal, replace(batch, ordering=ProposalOrdering.CANONICAL_INDEPENDENT),
                             dependency, "capture.3.7")
    with pytest.raises(ActivationError, match="occurrence"):
        _admit_selected_read(context, proposal, batch, dependency, "capture.3.8")
    with pytest.raises(GovernanceRejected):
        _admit_selected_read(context, proposal, batch, "a" * 64, "capture.3.7")
    changed = NormalizedProposal(ProposalKind.READ,
        {**proposal.payload, "arguments": {"owner": "example", "repository": "other"}})
    with pytest.raises(ActivationError, match="differs"):
        _admit_selected_read(context, changed, batch, dependency, "capture.3.7")
    context.supervisor_authority.revoke_all()
    # A live revoked context may still be inspected, but capture's projection
    # guard must reject it before issuing a transport reservation.
    controller = _controller(SupervisorProjection(context).canonical_record())
    with pytest.raises(ActivationError, match="unavailable supervisor"):
        controller._projection(SupervisorProjection(context).canonical_record())


@pytest.fixture
def simulated_selected_host(monkeypatch):
    """Synthetic host integration. No real credential or network operation."""
    import json
    import logging
    from collections import deque
    import ibae.readonly_adapters as reads
    from ibae.openai_transport import (OPENAI_SDK_VERSION, OpenAICredentialBroker,
                                      OpenAIResponsesSupervisor, OpenAITransportPolicy)
    from ibae.supervisor import FreshContextHandoff
    from ibae.synthetic_runner import reference_synthetic_transcripts
    from test_openai_transport import _body

    sdk = pytest.importorskip("openai")
    if sdk.__version__ != OPENAI_SDK_VERSION:
        pytest.skip("optional exact SDK is not installed")
    import httpx2

    context, selection, proposal, dependency = _selected_context()
    projection = SupervisorProjection(context)
    detached = projection.canonical_record()
    handoff = FreshContextHandoff(projection).canonical_record()
    policy = OpenAITransportPolicy("gpt-5.4", ("gpt-5.4",), live_enabled=True, max_calls=16)
    broker = OpenAICredentialBroker(context.governance_policy, context.task, context.governance,
                                   handle="cred:openai.synthetic", environment_name="IBAE_SYNTHETIC_CAPTURE_TEST")
    controller = ActivationController(context.task.task_id, context.governance.governance_id,
        transport_policy_id=policy.policy_id, credential_reference_id=broker.reference.reference_id,
        max_transport_calls=16)
    smoke = [NormalizedProposal.from_record(item) for item in reference_synthetic_transcripts()["happy_path"]["proposals"]]
    responses = deque(smoke + smoke + [proposal])
    calls = {"openai": 0, "github": 0}
    placeholder = "synthetic-placeholder-not-a-real-credential"
    monkeypatch.setenv("IBAE_SYNTHETIC_CAPTURE_TEST", placeholder)
    for name in ("OPENAI_CUSTOM_HEADERS", "OPENAI_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    for name in ("openai", "openai._base_client", "httpx2", "httpcore2", "httpx", "httpcore"):
        monkeypatch.setattr(logging.getLogger(name), "level", logging.WARNING)

    def respond(request):
        assert str(request.url) == "https://api.openai.com/v1/responses"
        assert request.headers["authorization"] == "Bearer " + placeholder
        calls["openai"] += 1
        return httpx2.Response(200, headers={"content-type": "application/json"}, content=_body(responses.popleft()))

    original = sdk.DefaultHttpx2Client
    monkeypatch.setattr(sdk, "DefaultHttpx2Client",
        lambda **kwargs: original(transport=httpx2.MockTransport(respond), **kwargs))
    controller.verify_synthetic_stage()
    for stage, profile in ((ActivationStage.OPENAI_FAKE_TOOLS, ToolProfile.FAKE),
                            (ActivationStage.OPENAI_DETERMINISTIC_READS, ToolProfile.DETERMINISTIC_READONLY)):
        controller.authorize(_authorization(controller, stage))
        supervisor = OpenAIResponsesSupervisor(policy, broker, broker.reference, stage=stage, tool_profile=profile)
        for index in range(len(smoke)):
            controller.propose(supervisor, detached, index=index, fresh_handoff=handoff)
        observed = (controller.verify_fake_tool_stage() if stage is ActivationStage.OPENAI_FAKE_TOOLS
                    else controller.verify_fixture_stage())
        assert observed.canonical_record()["live_recovery_verified"] is False
    controller.authorize(replace(_authorization(controller, ActivationStage.OPENAI_SELECTED_READS),
        selected_read_tools=("github.repository",), selected_read_selection_ids=(selection.selection_id,)))
    supervisor = OpenAIResponsesSupervisor(policy, broker, broker.reference,
        stage=ActivationStage.OPENAI_SELECTED_READS, tool_profile=ToolProfile.SELECTED_READONLY,
        selected_read_tools=("github.repository",))
    owned = controller.propose(supervisor, detached, index=0, fresh_handoff=handoff)
    assert owned == proposal and not responses
    body = json.dumps({"full_name": "example/project", "default_branch": "main",
                       "private": False, "archived": False}).encode()
    settings = {"status": 200, "body": body, "transport_error": False}

    class Response:
        def __init__(self):
            self.body = settings["body"]
            self.remaining = self.body
            self.status = settings["status"]
        def getheader(self, name):
            return {"Content-Length": str(len(self.body)), "Content-Type": "application/json"}.get(name)
        def read(self, amount):
            chunk, self.remaining = self.remaining[:amount], self.remaining[amount:]
            return chunk

    class Connection:
        def __init__(self, host, **kwargs):
            assert host == "api.github.com" and kwargs["port"] == 443
        def request(self, method, path, *, headers):
            assert method == "GET" and path == "/repos/example/project"
            calls["github"] += 1
            if settings["transport_error"]:
                raise OSError("synthetic HTTP interruption; diagnostic text must not escape")
        def getresponse(self):
            return Response()
        def close(self):
            pass

    monkeypatch.setattr(reads.http.client, "HTTPSConnection", Connection)
    adapter = reads.GitHubReadAdapter(selection, controller, task_id=controller.task_id,
                                      governance_id=controller.governance_id)
    return controller, context, selection, owned, dependency, adapter, calls, settings


def test_simulated_host_full_stage3_capture_and_native_gate(simulated_selected_host):
    """End-to-end control coverage under offline HTTP mocks, not live evidence."""
    controller, context, _, proposal, dependency, adapter, calls, _ = simulated_selected_host
    native_before = context.runtime_session.snapshot.canonical_record()
    with pytest.raises(ActivationError, match="governed capture plan"):
        adapter.observe(proposal, dependency)
    assert calls == {"openai": 7, "github": 0}
    with pytest.raises(ActivationError, match="cover every"):
        controller.verify_selected_read_stage()
    batch = _selected_batch(context, proposal, controller.capture_occurrence_key)
    capture = controller.capture_selected_read(adapter, proposal, dependency, context=context, batch=batch)
    assert calls == {"openai": 7, "github": 1}
    assert controller.call_count == 8
    assert context.runtime_session.snapshot.canonical_record() == native_before
    assert capture.next_orchestration_state.logical_tick == context.orchestration_state.logical_tick + 1
    assert capture.snapshot.canonical_record()["live_capture_verified"] is False
    assert capture.canonical_record()["http_capture_native_accounted"] is False
    with pytest.raises(ActivationError, match="already consumed"):
        controller.capture_selected_read(adapter, proposal, dependency, context=context, batch=batch)
    with pytest.raises(TypeError):
        controller.verify_selected_read_stage(capture.snapshot)
    observed = controller.verify_selected_read_stage().canonical_record()
    evidence = observed["evidence"]
    assert observed["stage"] == 3 and observed["live_recovery_verified"] is False
    assert observed["final_acceptance"] is False
    assert evidence["http_captures"] == 1 and evidence["native_proof_transport_calls"] == 0
    assert evidence["http_capture_native_accounted"] is False
    assert evidence["native_proof"]["native_compact_source_bound"] is True
    assert evidence["native_proof"]["counters"]["requests"] == 2
    assert evidence["native_proof"]["counters"]["executions"] == 1
    assert evidence["native_proof"]["counters"]["cache_hits"] == 1
    assert evidence["fresh_native_runs"] == 2
    assert evidence["native_total_counters"]["requests"] == 4
    assert evidence["native_total_counters"]["executions"] == 2
    assert context.runtime_session.snapshot.canonical_record() == native_before
    assert controller.canonical_record()["active_stage_verification"] == "passed"
    controller.rollback()
    assert controller.call_count == 8
    assert controller.canonical_record()["selected_capture_count"] == 0
    assert controller.canonical_record()["consumed_selected_proposals"] == 0
    assert controller.canonical_record()["selected_capture_outcomes"]["captured"] == 1
    assert controller.canonical_record()["selected_capture_attempts"][0]["transport_reservation_consumed"] is True
    assert capture.snapshot.source_receipt.output["full_name"] == "example/project"


def test_simulated_host_rejects_unowned_proposals_and_native_revocation(simulated_selected_host):
    controller, context, _, proposal, dependency, adapter, calls, _ = simulated_selected_host
    unowned = NormalizedProposal(ProposalKind.READ, {**proposal.payload, "proposal_key": "unowned"})
    with pytest.raises(ActivationError, match="owned live proposal"):
        controller.capture_selected_read(adapter, unowned, dependency, context=context,
            batch=_selected_batch(context, unowned, controller.capture_occurrence_key))
    context.supervisor_authority.revoke_all()
    with pytest.raises(ActivationError, match="unavailable supervisor"):
        controller.capture_selected_read(adapter, proposal, dependency, context=context,
            batch=_selected_batch(context, proposal, controller.capture_occurrence_key))
    assert calls["github"] == 0
    assert controller.call_count == 7
    assert controller.canonical_record()["selected_capture_count"] == 0


def test_simulated_denied_or_stale_capture_admission_makes_no_get(simulated_selected_host):
    from ibae.governance import GovernanceRejected
    from ibae.orchestration import ProposalOrdering

    controller, context, _, proposal, dependency, adapter, calls, _ = simulated_selected_host
    batch = _selected_batch(context, proposal, controller.capture_occurrence_key)
    with pytest.raises(ActivationError, match="declared-sequence"):
        controller.capture_selected_read(adapter, proposal, dependency, context=context,
            batch=replace(batch, ordering=ProposalOrdering.CANONICAL_INDEPENDENT))
    with pytest.raises(GovernanceRejected):
        controller.capture_selected_read(adapter, proposal, "a" * 64, context=context, batch=batch)
    stale_context = replace(context, orchestration_state=replace(context.orchestration_state, logical_tick=1))
    with pytest.raises((ValueError, RuntimeError)):
        controller.capture_selected_read(adapter, proposal, dependency, context=stale_context, batch=batch)
    record = controller.canonical_record()
    assert calls["github"] == 0
    assert controller.call_count == 7
    assert record["selected_http_reservations"] == 0
    assert record["selected_capture_attempts"] == []
    assert record["consumed_selected_proposals"] == 0


@pytest.mark.parametrize("failure", ["transport", "http", "malformed_body"])
def test_simulated_failed_capture_preserves_partial_admission_and_budget(simulated_selected_host, failure):
    from ibae.transport_activation import SelectedReadCaptureError

    controller, context, _, proposal, dependency, adapter, calls, settings = simulated_selected_host
    if failure == "transport":
        settings["transport_error"] = True
    elif failure == "http":
        settings["status"] = 503
    else:
        settings["body"] = b"not a JSON observation"
    native_before = context.runtime_session.snapshot.canonical_record()
    batch = _selected_batch(context, proposal, controller.capture_occurrence_key)
    with pytest.raises(SelectedReadCaptureError) as caught:
        controller.capture_selected_read(adapter, proposal, dependency, context=context, batch=batch)
    error = caught.value
    assert error.__context__ is None
    assert "diagnostic text" not in str(error)
    assert error.attempt.next_orchestration_state.logical_tick == context.orchestration_state.logical_tick + 1
    assert error.attempt.snapshot_id is None
    assert error.attempt.transport_call_index == 7
    assert error.attempt.admission_receipt.prior_state_id == context.orchestration_state.state_id
    assert calls["github"] == 1
    record = controller.canonical_record()
    assert record["selected_capture_count"] == 0
    assert record["selected_http_reservations"] == 1
    assert record["openai_transport_calls"] == 7
    assert record["consumed_transport_calls"] == 8
    assert record["selected_capture_incomplete"] == 0
    assert sum(record["selected_capture_outcomes"].values()) == 1
    assert record["selected_capture_attempts"][0]["transport_reservation_consumed"] is True
    assert context.runtime_session.snapshot.canonical_record() == native_before
    with pytest.raises(ActivationError, match="already consumed"):
        controller.capture_selected_read(adapter, proposal, dependency, context=context, batch=batch)
    with pytest.raises(ActivationError, match="governed capture plan"):
        adapter.observe(proposal, dependency)
    with pytest.raises(ActivationError, match="cover every"):
        controller.verify_selected_read_stage()
    assert calls["github"] == 1
    prior_attempt = record["selected_capture_attempts"][0]
    controller.rollback()
    after = controller.canonical_record()
    assert after["selected_capture_attempts"] == [prior_attempt]
    assert after["selected_capture_attempts_remaining"] == 15
    assert after["selected_http_reservations"] == 1
    assert after["consumed_transport_calls"] == 8
