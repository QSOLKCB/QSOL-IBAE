"""Offline transport safety tests, never actual live verification.

The explicit simulator exercises shared admission and accounting through inert
fake/frozen adapters. Production SDK mocks are negative provenance tests only:
their successful decoding never qualifies a live gate. No live ledger is seeded.
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
    OperatorStageAuthorization, SimulationActivationController, StageObservation, ToolProfile, TransportCallReservation,
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
        selected_read_selection_ids=("e" * 64,) if stage is ActivationStage.OPENAI_SELECTED_READS else (),
        simulation_only=controller.simulation_only)


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
def simulated_selected_host(monkeypatch, request):
    """Explicit offline controller; production dispatch paths are tripwires."""
    import json
    import ibae.openai_transport as transport
    import ibae.readonly_adapters as reads
    from ibae.supervisor import FreshContextHandoff
    from ibae.synthetic_runner import reference_synthetic_transcripts

    def forbidden(*args, **kwargs):
        pytest.fail("simulation reached production credential/network dispatch")

    monkeypatch.setattr(transport.OpenAICredentialBroker, "_request", forbidden)
    monkeypatch.setattr(reads.http.client, "HTTPSConnection", forbidden)
    options = getattr(request, "param", {})
    context, selection, proposal, dependency = _selected_context()
    selections = [selection]
    for index in range(1, options.get("selection_count", 1)):
        selections.append(reads.GitHubReadSelection("a" * 39, f"r{index:02d}" + "r" * 97,
            branch="b" * 256, commit_sha="a" * 40, pull_number=(1 << 31) - 1))
    projection = SupervisorProjection(context)
    detached = projection.canonical_record()
    handoff = FreshContextHandoff(projection).canonical_record()
    controller = SimulationActivationController(context.task.task_id, context.governance.governance_id,
        transport_policy_id="c" * 64, credential_reference_id="d" * 64,
        max_transport_calls=options.get("budget", 16))
    smoke = tuple(NormalizedProposal.from_record(item) for item in reference_synthetic_transcripts()["happy_path"]["proposals"])
    controller.verify_synthetic_stage()
    for stage in (ActivationStage.OPENAI_FAKE_TOOLS, ActivationStage.OPENAI_DETERMINISTIC_READS):
        controller.authorize(_authorization(controller, stage))
        supervisor = FakeSupervisor(smoke)
        for index in range(len(smoke)):
            controller.propose(supervisor, detached, index=index, fresh_handoff=handoff)
        observed = (controller.verify_fake_tool_stage() if stage is ActivationStage.OPENAI_FAKE_TOOLS
                    else controller.verify_fixture_stage()).canonical_record()
        assert observed["live_transport_observed"] is False and observed["simulation_only"] is True
    controller.authorize(replace(_authorization(controller, ActivationStage.OPENAI_SELECTED_READS),
        selected_read_tools=("github.repository",),
        selected_read_selection_ids=tuple(sorted(item.selection_id for item in selections))))
    for item in selections[:options.get("register_count", len(selections))]:
        controller.register_selected_read(item)
    supervisor = FakeSupervisor((proposal,))
    owned = controller.propose(supervisor, detached, index=0, fresh_handoff=handoff)
    calls = {"openai_inputs": [transport._model_input_record(detached, handoff, controller.last_capture_surface)]}
    body = json.dumps({"full_name": "example/project", "default_branch": "main",
                       "private": False, "archived": False}).encode()
    settings = {"body": body, "selections": selections}
    adapter = reads.SimulatedGitHubReadAdapter(selection, controller, task_id=controller.task_id,
                                               governance_id=controller.governance_id, body=body)
    return controller, context, selection, owned, dependency, adapter, calls, settings


def _simulated_adapter(controller, selection, settings, **changes):
    from ibae.readonly_adapters import SimulatedGitHubReadAdapter
    return SimulatedGitHubReadAdapter(selection, controller, task_id=controller.task_id,
        governance_id=controller.governance_id, **({"body": settings["body"]} | changes))


def test_simulated_host_full_stage3_capture_and_native_gate(simulated_selected_host):
    """End-to-end control coverage under offline HTTP mocks, not live evidence."""
    controller, context, _, proposal, dependency, adapter, calls, _ = simulated_selected_host
    native_before = context.runtime_session.snapshot.canonical_record()
    with pytest.raises(ActivationError, match="governed capture plan"):
        adapter.observe(proposal, dependency)
    assert controller.call_count == 7 and adapter.call_count == 0
    with pytest.raises(ActivationError, match="cover every"):
        controller.verify_selected_read_stage()
    batch = _selected_batch(context, proposal, controller.capture_occurrence_key)
    capture = controller.capture_selected_read(adapter, proposal, dependency, context=context, batch=batch)
    assert controller.call_count == 8 and adapter.call_count == 1
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
    assert evidence["http_captures"] == 0 and evidence["simulated_http_captures"] == 1
    assert observed["live_transport_observed"] is False and observed["simulation_only"] is True
    assert evidence["native_proof_transport_calls"] == 0
    assert evidence["http_capture_native_accounted"] is False
    assert evidence["native_proof"]["native_compact_source_bound"] is True
    assert evidence["native_proof"]["counters"]["requests"] == 2
    assert evidence["native_proof"]["counters"]["executions"] == 1
    assert evidence["native_proof"]["counters"]["cache_hits"] == 1
    assert evidence["fresh_native_runs"] == 2
    assert evidence["native_total_counters"]["requests"] == 4
    assert evidence["native_total_counters"]["executions"] == 2
    assert context.runtime_session.snapshot.canonical_record() == native_before
    assert controller.canonical_record()["active_stage_verification"] == "simulation_passed"
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
    assert adapter.call_count == 0
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
    assert adapter.call_count == 0
    assert controller.call_count == 7
    assert record["selected_http_reservations"] == 0
    assert record["selected_capture_attempts"] == []
    assert record["consumed_selected_proposals"] == 0


@pytest.mark.parametrize("failure", ["transport", "http", "malformed_body"])
def test_simulated_failed_capture_preserves_partial_admission_and_budget(simulated_selected_host, failure):
    from ibae.transport_activation import SelectedReadCaptureError

    controller, context, selection, proposal, dependency, adapter, calls, settings = simulated_selected_host
    changes = ({"failure_reason": "transport_unavailable"} if failure == "transport" else
               {"status_code": 503} if failure == "http" else {"body": b"not a JSON observation"})
    adapter = _simulated_adapter(controller, selection, settings, **changes)
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
    assert adapter.call_count == 1
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
    assert adapter.call_count == 1
    prior_attempt = record["selected_capture_attempts"][0]
    controller.rollback()
    after = controller.canonical_record()
    assert after["selected_capture_attempts"] == [prior_attempt]
    assert after["selected_capture_attempts_remaining"] == 15
    assert after["selected_http_reservations"] == 1
    assert after["consumed_transport_calls"] == 8


@pytest.mark.parametrize("simulated_selected_host", [{"budget": 32}], indirect=True)
def test_failed_capture_next_state_survives_rollback_and_regating(simulated_selected_host):
    """Offline HTTP failure cannot discard the already admitted host transition."""
    from ibae.continuation import (default_obligation_progress_contract, evaluate_progress,
                                   observe_continuation_context)
    from ibae.supervisor import FreshContextHandoff
    from ibae.synthetic_runner import reference_synthetic_transcripts
    from ibae.transport_activation import SelectedReadCaptureError

    controller, context, selection, proposal, dependency, adapter, calls, settings = simulated_selected_host
    adapter = _simulated_adapter(controller, selection, settings, failure_reason="transport_unavailable")
    with pytest.raises(SelectedReadCaptureError) as caught:
        controller.capture_selected_read(adapter, proposal, dependency, context=context,
            batch=_selected_batch(context, proposal, controller.capture_occurrence_key))
    next_state = caught.value.attempt.next_orchestration_state
    prior_attempt = caught.value.attempt.canonical_record()
    controller.rollback()
    # A transport-only deployment reset also cannot drop admitted host history.
    controller.configure_transport(transport_policy_id="e" * 64, credential_reference_id="f" * 64)
    controller.configure_transport(transport_policy_id="c" * 64, credential_reference_id="d" * 64)
    detached = SupervisorProjection(context).canonical_record()
    handoff = FreshContextHandoff(SupervisorProjection(context)).canonical_record()
    smoke = [NormalizedProposal.from_record(item) for item in reference_synthetic_transcripts()["happy_path"]["proposals"]]
    controller.verify_synthetic_stage()
    for stage, profile in ((ActivationStage.OPENAI_FAKE_TOOLS, ToolProfile.FAKE),
                            (ActivationStage.OPENAI_DETERMINISTIC_READS, ToolProfile.DETERMINISTIC_READONLY)):
        controller.authorize(_authorization(controller, stage))
        supervisor = FakeSupervisor(tuple(smoke))
        for index in range(len(smoke)):
            controller.propose(supervisor, detached, index=index, fresh_handoff=handoff)
        if stage is ActivationStage.OPENAI_FAKE_TOOLS:
            controller.verify_fake_tool_stage()
        else:
            controller.verify_fixture_stage()
    controller.authorize(replace(_authorization(controller, ActivationStage.OPENAI_SELECTED_READS),
        selected_read_tools=("github.repository",), selected_read_selection_ids=(selection.selection_id,)))
    controller.register_selected_read(selection)
    supervisor = FakeSupervisor((proposal,))
    owned = controller.propose(supervisor, detached, index=0, fresh_handoff=handoff)
    with pytest.raises(ActivationError, match="did not advance"):
        controller.capture_selected_read(adapter, owned, dependency, context=context,
            batch=_selected_batch(context, owned, controller.capture_occurrence_key))
    assert adapter.call_count == 1
    assert controller.canonical_record()["selected_capture_attempts"] == [prior_attempt]
    assert "host_orchestration_state_not_advanced" in controller.selected_capture_surface(detached)["blocking_reasons"]
    # Replacing Python state alone is stale; use the existing native observer.
    with pytest.raises((ValueError, RuntimeError)):
        SupervisorProjection(replace(context, orchestration_state=next_state))
    progress = evaluate_progress(task_id=context.task.task_id, governance_id=context.governance.governance_id,
        contract=default_obligation_progress_contract(), prior_state=context.orchestration_state,
        current_state=next_state)
    continuation = observe_continuation_context(context.continuation_state,
        runtime_session=context.runtime_session, policy=context.continuation_policy,
        orchestration_state=next_state, runtime_snapshot=context.runtime_session.snapshot, progress=progress)
    advanced = replace(context, continuation_state=continuation, orchestration_state=next_state)
    next_proposal = NormalizedProposal(ProposalKind.READ, {**proposal.payload, "proposal_key": "capture.retry"})
    supervisor = FakeSupervisor((next_proposal,))
    projected = SupervisorProjection(advanced)
    owned = controller.propose(supervisor, projected.canonical_record(), index=0,
                                fresh_handoff=FreshContextHandoff(projected).canonical_record())
    adapter = _simulated_adapter(controller, selection, settings)
    capture = controller.capture_selected_read(adapter, owned, dependency, context=advanced,
        batch=_selected_batch(advanced, owned, controller.capture_occurrence_key))
    assert capture.next_orchestration_state.logical_tick == next_state.logical_tick + 1
    assert adapter.call_count == 1
    assert controller.canonical_record()["selected_http_reservations"] == 2
    assert controller.call_count == 17
    assert controller.canonical_record()["selected_capture_outcomes"]["captured"] == 1


@pytest.mark.parametrize("simulated_selected_host", [{"selection_count": 16}], indirect=True)
def test_capture_surface_preserves_combined_maximum_source_counts_and_long_keys(simulated_selected_host):
    from ibae.epistemic import EpistemicClass, EpistemicRecord, EpistemicState
    from ibae.obligations import Obligation
    from ibae.orchestration import OrchestrationState
    from ibae.transport_activation import MAX_SELECTED_CAPTURE_SURFACE_BYTES
    from test_supervisor import _context

    controller, context, _, _, _, _, _, _ = simulated_selected_host
    obligations = tuple(Obligation(f"o{index:03d}." + "x" * 123, "Ready") for index in range(128))
    records = tuple(EpistemicRecord(f"e{index:03d}." + "x" * 123,
        EpistemicClass.DERIVED, index) for index in range(256))
    state = OrchestrationState.create(obligations, capabilities=context.orchestration_state.capabilities,
        strategy_schemas=context.orchestration_state.strategy_schemas, epistemic_state=EpistemicState(records))
    dense, _, _ = _context(state=state, permissions=context.governance_policy.tool_permissions)
    projection = SupervisorProjection(dense).canonical_record()
    original = canonical_json(projection)
    captured = controller.selected_capture_surface(projection)
    assert len(captured["ready_targets"]) == 128
    assert len(captured["resolved_dependency_records"]) == 256
    assert len(captured["candidates"]) == 16
    assert all(len(item["key"]) == 128 for item in captured["ready_targets"] + captured["resolved_dependency_records"])
    assert all(item["may_propose_candidate"] for item in captured["candidates"])
    assert 65_536 < len(canonical_json(captured).encode()) <= MAX_SELECTED_CAPTURE_SURFACE_BYTES
    assert canonical_json(projection) == original
    # Output is inert and mutation-isolated, including source lists over 128.
    captured["ready_targets"].clear()
    assert len(controller.selected_capture_surface(projection)["ready_targets"]) == 128


def test_capture_surface_candidate_is_conditional_and_exact_request_bound(simulated_selected_host):
    controller, context, selection, proposal, _, _, calls, _ = simulated_selected_host
    projection = SupervisorProjection(context).canonical_record()
    prior = canonical_json(projection)
    surface = calls["openai_inputs"][-1]["selected_capture_surface"]
    candidate, = surface["candidates"]
    assert candidate["arguments"] == selection.arguments_for("github.repository") == proposal.payload["arguments"]
    assert candidate["may_propose_candidate"] is True
    assert surface["host_admission_required"] is True and surface["execution_authorized"] is False
    assert set(surface["unresolved_admission_checks"]) >= {
        "exact_argument_schema", "current_orchestration_tick", "exact_dependency_fingerprint",
        "declared_sequence_occurrence", "deterministic_batch_admission", "governed_volatile_tool_admission"}
    assert surface["current_openai_call_reserved"] is True
    assert surface["remaining_after_current_openai_call"] == controller.remaining_transport_calls
    assert surface["host_next_capture_occurrence_key"] == controller.capture_occurrence_key
    assert "eligible" not in candidate and surface["control_authority"] is False
    reservation = controller.reserve_call(projection, stage=controller.stage, tool_profile=controller.tool_profile,
        selected_read_tools=controller.selected_read_tools, **_deployment(controller))
    try:
        bound = controller.selected_capture_surface(projection, reservation=reservation)
        controller.check_reservation(reservation, projection, capture_surface_id=bound["surface_id"], **_deployment(controller))
        with pytest.raises(ActivationError, match="capture surface"):
            controller.check_reservation(reservation, projection, capture_surface_id=surface["surface_id"], **_deployment(controller))
        assert bound["remaining_after_current_openai_call"] == controller.remaining_transport_calls
    finally:
        controller.complete_call(reservation)
    assert canonical_json(projection) == prior


def test_capture_surface_excludes_every_visible_definitive_admission_blocker(simulated_selected_host):
    """Detached schema observations may narrow candidates; they grant nothing."""
    controller, context, _, _, _, _, _, _ = simulated_selected_host
    cases = [
        (("capabilities", 0, "available"), False, "capability_unavailable"),
        (("capabilities", 0, "replay_safety"), "cacheable_read", "capture_requires_occurrence_sensitive_capability"),
        (("capabilities", 0, "granted_authority_class"), "pure_read", "volatile_read_permission_missing"),
        (("capabilities", 0, "permission_id"), None, "volatile_read_permission_missing"),
        (("capabilities", 0, "cache_reuse_granted"), True, "remote_http_cache_reuse_forbidden"),
        (("capabilities", 0, "unresolved_state_count"), 1, "unresolved_capability_dependencies"),
        (("capabilities", 0, "semantic_argument_count"), 1, "argument_schema_cannot_cover_selection"),
        (("capabilities",), [], "capability_unavailable"),
        (("ready_obligation_ids",), [], "no_ready_obligation"),
        (("strategy_schema_ids",), [], "no_declared_strategy_schema"),
        (("budgets", "orchestration_capacity", "max_batch_proposals"), 0, "no_batch_capacity"),
        (("budgets", "orchestration_capacity", "occurrence_owners"), 0, "no_occurrence_capacity"),
        (("authority", "supervisor_capability_present"), False, "native_authority_unavailable"),
        (("control_classification",), "governance_blocked", "native_control_not_ready"),
    ]
    for path, value, reason in cases:
        projection = SupervisorProjection(context).canonical_record()
        destination = projection["decision_surface"]
        for part in path[:-1]:
            destination = destination[part]
        destination[path[-1]] = value
        result = controller.selected_capture_surface(projection)
        assert result["may_propose_candidate"] is False, reason
        assert reason in result["candidates"][0]["blocking_reasons"]
    projection = SupervisorProjection(context).canonical_record()
    # Spend the finite transport allowance without dispatch; it never refunds.
    while controller.remaining_transport_calls > 1:
        reservation = controller.reserve_call(projection, stage=controller.stage, tool_profile=controller.tool_profile,
            selected_read_tools=controller.selected_read_tools, **_deployment(controller))
        controller.complete_call(reservation)
    surface = controller.selected_capture_surface(projection)
    assert surface["may_propose_candidate"] is False
    assert "no_transport_capacity_after_model_call" in surface["blocking_reasons"]
    controller.rollback()
    surface = controller.selected_capture_surface(projection)
    assert surface["may_propose_candidate"] is False
    assert "stage3_not_active" in surface["blocking_reasons"]
    assert surface["candidates"] == []


@pytest.mark.parametrize("simulated_selected_host", [{"selection_count": 2, "register_count": 1}], indirect=True)
def test_selected_target_registration_is_approved_and_fixed_before_owned_proposal(simulated_selected_host):
    from ibae.readonly_adapters import GitHubReadSelection

    controller, context, selection, _, _, adapter, calls, settings = simulated_selected_host
    captured = controller.selected_capture_surface(SupervisorProjection(context).canonical_record())
    known = next(item for item in captured["candidates"] if item["selection_id"] == selection.selection_id)
    absent = next(item for item in captured["candidates"] if item["selection_id"] != selection.selection_id)
    assert known["may_propose_candidate"] is True
    assert absent["may_propose_candidate"] is False and absent["arguments"] is None
    assert "selected_resource_not_registered" in absent["blocking_reasons"]
    controller.register_selected_read(selection)  # Exact repeat changes nothing.
    with pytest.raises(ActivationError, match="cannot change"):
        controller.register_selected_read(settings["selections"][1])
    with pytest.raises(ActivationError, match="operator selection"):
        controller.register_selected_read(GitHubReadSelection("unselected", "project"))
    assert adapter.call_count == 0


def test_simulation_mode_cannot_authorize_or_dispatch_production(simulated_selected_host):
    from ibae.readonly_adapters import GitHubReadAdapter
    from test_openai_transport import _setup

    simulated, context, selection, _, _, _, _, _ = simulated_selected_host
    actual, live, projection, handoff, _ = _setup()
    assert simulated.simulation_only is True and live.simulation_only is False
    for record in simulated.canonical_record()["stage_observations"]:
        assert record["simulation_only"] is True
        assert record["live_transport_observed"] is False
    assert simulated.canonical_record()["network_dispatch_allowed"] is False
    with pytest.raises(AttributeError):
        simulated.simulation_only = False
    with pytest.raises(ActivationError, match="different simulation mode"):
        live.authorize(replace(_authorization(live, ActivationStage.OPENAI_DETERMINISTIC_READS), simulation_only=True))
    with pytest.raises(TypeError, match="activation controller"):
        actual.propose(projection, index=0, activation=simulated, fresh_handoff=handoff)
    with pytest.raises(TypeError, match="live activation controller"):
        ActivationController.propose(simulated, actual, projection, index=0, fresh_handoff=handoff)
    with pytest.raises(TypeError, match="activation controller"):
        GitHubReadAdapter(selection, simulated, task_id=context.task.task_id, governance_id=context.governance.governance_id)
    assert live.call_count == 0
    assert simulated.call_count == 7


def test_official_sdk_mock_stream_never_qualifies_any_live_gate(monkeypatch):
    import logging
    from collections import deque
    from ibae.openai_transport import OPENAI_SDK_VERSION
    from ibae.synthetic_runner import reference_synthetic_transcripts
    from test_openai_transport import _body, _setup, _ENVIRONMENT, _PLACEHOLDER

    sdk = pytest.importorskip("openai")
    if sdk.__version__ != OPENAI_SDK_VERSION:
        pytest.skip("optional exact SDK is not installed")
    import httpx2

    supervisor, controller, projection, handoff, _ = _setup()
    smoke = deque(NormalizedProposal.from_record(item)
                  for item in reference_synthetic_transcripts()["happy_path"]["proposals"])
    monkeypatch.setenv(_ENVIRONMENT, _PLACEHOLDER)
    for name in ("OPENAI_CUSTOM_HEADERS", "OPENAI_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    for name in ("openai", "openai._base_client", "httpx2", "httpcore2", "httpx", "httpcore"):
        monkeypatch.setattr(logging.getLogger(name), "level", logging.WARNING)
    requests = []

    def respond(request):
        requests.append(request)
        return httpx2.Response(200, headers={"content-type": "application/json"}, content=_body(smoke.popleft()))

    original = sdk.DefaultHttpx2Client
    monkeypatch.setattr(sdk, "DefaultHttpx2Client",
                        lambda **kwargs: original(transport=httpx2.MockTransport(respond), **kwargs))
    for index in range(len(smoke)):
        with pytest.raises(ActivationError, match="verified live network outcome"):
            controller.propose(supervisor, projection, index=index, fresh_handoff=handoff)
        assert supervisor.last_observation.canonical_record()["status"] == "received"
        assert supervisor._consume_live_outcome(controller, requests[-1]) is None
    assert len(requests) == controller.call_count == 3
    with pytest.raises(ActivationError, match="owned official"):
        controller.verify_fake_tool_stage()
    with pytest.raises(ActivationError, match="preceding stage"):
        controller.authorize(_authorization(controller, ActivationStage.OPENAI_DETERMINISTIC_READS))
    with pytest.raises(ActivationError):
        controller.verify_fixture_stage()
    assert controller.stage is ActivationStage.OPENAI_FAKE_TOOLS
    assert all(not record["live_transport_observed"] for record in controller.canonical_record()["stage_observations"])
