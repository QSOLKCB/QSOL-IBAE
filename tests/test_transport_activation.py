"""Offline transport safety tests. No mocked response passes a live gate."""

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
                                tool_name="read.github", selection_id="e" * 64)
    assert controller.call_count == 0


def test_closed_gate_methods_have_no_caller_evidence_or_success_parameters():
    for name in ("verify_synthetic_stage", "verify_fake_tool_stage", "verify_fixture_stage",
                 "verify_selected_read_stage"):
        assert tuple(inspect.signature(getattr(ActivationController, name)).parameters) == ("self",)


def test_selected_read_stage_verifier_is_explicitly_unavailable(projection):
    controller = _controller(projection)
    with pytest.raises(ActivationError, match="verification is unavailable"):
        controller.verify_selected_read_stage()
    for claimed in (True, {"live_verified": True}, "a" * 64):
        with pytest.raises(TypeError):
            controller.verify_selected_read_stage(claimed)
    assert controller.canonical_record()["active_stage_verification"] == "not_verified"
    assert controller.canonical_record()["selected_read_stage_verifier"] == "unavailable"
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
