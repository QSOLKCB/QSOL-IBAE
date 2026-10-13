"""Closed offline transport/fixture conformance, never live activation proof."""
from __future__ import annotations

from .canonical import canonical_json, domain_fingerprint
from .evidence import EvidenceAccumulator, EvidenceLimits
from .governance import (
    GovernancePolicy, GovernanceWrapper, PrincipalAuthority, ProviderAuthority,
    SUPPORTED_REQUIRED_GATE_KEYS, ToolAuthorityClass, ToolPermission,
)
from .obligations import Obligation
from .orchestration import Capability, DecisionStatus, OrchestrationState, ReplaySafety, admit_batch
from .runtime import RuntimeLimits, RustRuntimeSession
from .synthetic_protocol import AdapterInterface, FakeReadUniverse, NormalizedProposal, SyntheticReadFixture
from .synthetic_runner import _SCHEMA, _proposal_batch, _source_state, reference_synthetic_transcripts

FIXTURE_EQUIVALENCE_VERSION = "IBAE-READONLY-FIXTURE-EQUIVALENCE-V1"


def _fixture_probe(*, readonly: bool) -> dict:
    # This deliberately closed smoke profile has no caller-selected predicates,
    # arbitrary backend or success callback. Both variants get fresh authority.
    from .readonly_adapters import FrozenReadAdapter

    source = reference_synthetic_transcripts()["happy_path"]
    epistemic = _source_state(source["source_version"])
    dependency = epistemic.dependency_digest(("frozen-source",))
    fixtures = tuple(SyntheticReadFixture(item["tool_name"], item["arguments"], dependency, item["output"],
                                               interface=AdapterInterface.FILESYSTEM)
                     for item in source["fixtures"])
    adapter = FrozenReadAdapter(fixtures) if readonly else FakeReadUniverse(fixtures)
    capability = Capability("read.frozen", ReplaySafety.CACHEABLE_READ, "Closed deterministic fixture read.",
                            required_state_keys=("frozen-source",), semantic_argument_keys=("path",))
    state = OrchestrationState.create(
        tuple(Obligation(rule["obligation_key"], "Verify closed read-only fixture.")
              for rule in source["acceptance_rules"]),
        epistemic_state=epistemic, capabilities=(capability,), strategy_schemas=(_SCHEMA,),
    )
    policy = GovernancePolicy("transport.fixture.probe", 1, "transport.fixture.probe", 1,
                              ProviderAuthority.OPENAI,
                              (ToolPermission("read.frozen", ToolAuthorityClass.SNAPSHOT_READ, False, True),),
                              tuple(SUPPORTED_REQUIRED_GATE_KEYS))
    wrapper = GovernanceWrapper(policy)
    task, governance = wrapper.admit_task(
        "transport.fixture.probe", {"profile": "fixed-readonly-equivalence", "source": source["fixtures"]},
        requester=PrincipalAuthority.OPENAI_SUPERVISOR,
    )
    runtime = RustRuntimeSession("transport.fixture.probe", RuntimeLimits(max_requests=4, max_executions=4,
                                                                          max_retries=1, max_history=6))
    proposal = NormalizedProposal.from_record(source["proposals"][0])
    batch = _proposal_batch(proposal, 0)
    admitted = admit_batch(state, batch)
    by_id = {item.proposal_id: item for item in batch.proposals}
    decisions = admitted.receipt.decisions
    if len(decisions) != 2 or any(item.status is not DecisionStatus.ADMITTED for item in decisions):
        raise ValueError("closed fixture smoke admission changed")
    authorizations = tuple(wrapper.admit_tool(
        task, governance, decision, by_id[decision.proposal_id], capability,
        ToolAuthorityClass.SNAPSHOT_READ, dependency_state_id=dependency,
        requester=PrincipalAuthority.DETERMINISTIC_ORCHESTRATOR,
    ) for decision in decisions)
    orchestration = wrapper.bind_orchestration(task, governance, admitted.receipt, authorizations)
    accumulator = EvidenceAccumulator(task.task_id, governance.governance_id, orchestration.orchestration_id,
                                      authorization_manifest=orchestration.authorization_manifest,
                                      limits=EvidenceLimits(max_cases=2, max_failure_details=1))
    observations, receipts = [], []
    for decision in decisions:
        action = by_id[decision.proposal_id]

        def operation(action=action):
            if readonly:
                return adapter.lookup(action.capability, action.arguments, dependency)
            return adapter.lookup(action.capability, action.arguments, dependency,
                                  interface=AdapterInterface.FILESYSTEM)

        result = runtime.execute_admitted_read(decision, action, capability, dependency, operation)
        if result.receipt.status != "accepted":
            raise ValueError("closed fixture read was rejected")
        expected = next(item["output"] for item in source["fixtures"]
                        if canonical_json(item["arguments"]) == canonical_json(action.arguments))
        if canonical_json(result.observation) != canonical_json(expected):
            raise ValueError("closed fixture output differs from declared source")
        accumulator.record_runtime_case(result.receipt)
        observations.append(result.observation)
        receipts.append(result.receipt.canonical_record())
    execution = wrapper.bind_execution(task, governance, orchestration, accumulator.aggregate_summary())
    compact = accumulator.finalize(execution.execution_id)
    if not compact.source_bound:
        raise ValueError("closed fixture probe lacks native source evidence")
    return {"task_id": task.task_id, "governance_id": governance.governance_id,
            "admission": admitted.receipt.canonical_record(),
            "tool_authorizations": [item.canonical_record() for item in authorizations],
            "orchestration": orchestration.canonical_record(), "execution": execution.canonical_record(),
            "compact": compact.canonical_record(), "observations": observations,
            "runtime_receipts": receipts, "runtime": runtime.snapshot.canonical_record()}


def verify_readonly_fixture_stage() -> dict:
    """Execute the two closed native paths; this alone verifies no live stage."""
    fake = _fixture_probe(readonly=False)
    fixture = _fixture_probe(readonly=True)
    if canonical_json(fake) != canonical_json(fixture):
        raise ValueError("read-only fixture adapter changed native admission or evidence")
    stream = reference_synthetic_transcripts()["happy_path"]["proposals"]
    record = {"protocol_version": FIXTURE_EQUIVALENCE_VERSION,
              "equivalent": True, "live_verification": False,
              "task_id": fake["task_id"], "governance_id": fake["governance_id"],
              "proposal_stream_id": domain_fingerprint("ibae.transport-proposal-stream.v1", stream),
              "fake_path": fake, "fixture_path": fixture}
    if len(canonical_json(record).encode()) > 65_536:
        raise ValueError("fixture equivalence report exceeds bound")
    record["report_id"] = domain_fingerprint("ibae.readonly-fixture-equivalence.v1", record)
    return record


TRANSPORT_CONFORMANCE_VERSION = "IBAE-OPENAI-READONLY-CONFORMANCE-V1"


def offline_response_bytes(proposal: NormalizedProposal, index: int) -> bytes:
    """Provider-shaped frozen wire data, never evidence of an API request."""
    from .openai_transport import encode_proposal_envelope
    if type(proposal) is not NormalizedProposal or type(index) is not int or not 0 <= index < 128:
        raise ValueError("invalid closed offline response input")
    return canonical_json({"object": "response", "id": f"resp_offline_{index}",
        "status": "completed", "model": "offline-conformance-model", "error": None,
        "incomplete_details": None, "output": [{"type": "message", "role": "assistant",
        "status": "completed", "content": [{"type": "output_text",
        "text": encode_proposal_envelope(proposal)}]}]}).encode()


def v0_6c_reference_fixture() -> dict:
    """Independent normalized wire replay plus concrete native fixture reads."""
    from .openai_transport import OpenAITransportPolicy, decode_openai_response, openai_interface_manifest
    from .readonly_adapters import readonly_interface_manifest
    from .synthetic_runner import run_synthetic_transcript

    policy = OpenAITransportPolicy("offline-conformance-model", ("offline-conformance-model",))
    streams = {}
    for name, source in sorted(reference_synthetic_transcripts().items()):
        decoded = []
        for index, item in enumerate(source["proposals"]):
            proposed = NormalizedProposal.from_record(item)
            wire = offline_response_bytes(proposed, index)
            restored, _ = decode_openai_response(wire, policy=policy)
            if restored.canonical_record() != item:
                raise ValueError("official wire normalization changed a proposal")
            decoded.append(restored.canonical_record())
        altered = {**source, "proposals": decoded}
        fake_run = run_synthetic_transcript(source)
        fake = fake_run.canonical_record()
        wire_replay = run_synthetic_transcript(altered).canonical_record()
        if canonical_json(fake) != canonical_json(wire_replay):
            raise ValueError("official normalized wire path changed deterministic admission")
        streams[name] = {"proposal_count": len(decoded), "equivalent": True,
                         "normalized_stream_id": domain_fingerprint("ibae.transport-proposal-stream.v1", decoded),
                         "run_id": fake_run.report_id}
    fixture = verify_readonly_fixture_stage()
    record = {"protocol_version": TRANSPORT_CONFORMANCE_VERSION, "provider": "openai",
              "offline_only": True, "live_verification": False, "live_recovery_verified": False,
              "external_effects_executed": 0, "transport_policy": policy.canonical_record(),
              "openai_interfaces": openai_interface_manifest(), "readonly_interfaces": readonly_interface_manifest(),
              "equivalent_streams": streams, "fixture_equivalence": fixture,
              "observed_snapshot_equivalence": synthetic_snapshot_conformance(),
              "selected_capture_admission": selected_capture_admission_conformance(),
              "simulated_activation": simulation_activation_conformance(),
              "live_gate_status": "blocked_missing_operator_credentials_and_live_stage_evidence"}
    record["conformance_id"] = domain_fingerprint("ibae.openai-readonly-conformance.v1", record)
    return record


def synthetic_snapshot_conformance() -> dict:
    """Frozen HTTP-shaped bytes → immutable snapshot → real native parity."""
    from .observed_snapshots import ObservedReadSnapshot, verify_observed_snapshot_stage
    from .readonly_adapters import GitHubReadSelection, GitHubRequestPlan, parse_github_response
    from .synthetic_protocol import ProposalKind
    selection = GitHubReadSelection("example", "frozen-project", "main", "a" * 40, 1)
    proposal = NormalizedProposal(ProposalKind.READ, {"proposal_key": "inspect.frozen.repo",
        "tool_name": "github.repository", "arguments": selection.arguments_for("github.repository"),
        "target_obligation_keys": ["inspect"]})
    plan = GitHubRequestPlan(proposal, selection, "1" * 64)
    response = {"full_name": "example/frozen-project", "default_branch": "main",
                "private": False, "archived": False}
    receipt = parse_github_response(plan, 200, canonical_json(response).encode())
    snapshot = ObservedReadSnapshot.from_receipt(receipt)
    proof = verify_observed_snapshot_stage((snapshot,))
    return {"profile": "synthetic_http_shape_only", "live_capture_verified": False,
            "transport_calls": 0, "request_id": plan.request_id,
            "source_receipt_id": receipt.receipt_id, "snapshot_id": snapshot.snapshot_id,
            "native_consumption_equivalence": proof}


def _selected_capture_fixture_context():
    """Closed task inputs shared by admission and isolated simulation probes."""
    from .continuation import ContinuationPolicyReceipt, ContinuationState, experimental_continuation_profile
    from .epistemic import EpistemicClass, EpistemicRecord, EpistemicState
    from .orchestration import StrategySchema
    from .readonly_adapters import GITHUB_READ_TOOLS, GitHubReadSelection
    from .supervisor import SupervisorContext

    selection = GitHubReadSelection("example", "frozen-project", "main", "a" * 40, 1)
    epistemic = EpistemicState((EpistemicRecord("selected-source", EpistemicClass.DERIVED,
                                             selection.canonical_record()),))
    dependency = epistemic.dependency_digest(("selected-source",))
    capabilities = tuple(Capability(name, ReplaySafety.OCCURRENCE_SENSITIVE,
        "Selected volatile HTTP observation capture, never native cache reuse.",
        required_state_keys=("selected-source",),
        semantic_argument_keys=tuple(sorted(selection.arguments_for(name)))) for name in sorted(GITHUB_READ_TOOLS))
    schema = StrategySchema("transport.capture.fixture")
    state = OrchestrationState.create((Obligation("inspect", "Inspect a selected observation."),),
        epistemic_state=epistemic, capabilities=capabilities, strategy_schemas=(schema,))
    governance_policy = GovernancePolicy("transport.capture.fixture", 1, "tiny", 1, ProviderAuthority.OPENAI,
        tuple(ToolPermission(name, ToolAuthorityClass.VOLATILE_READ, False, False) for name in sorted(GITHUB_READ_TOOLS)),
        tuple(SUPPORTED_REQUIRED_GATE_KEYS))
    task, governance = GovernanceWrapper(governance_policy).admit_task("transport.capture.fixture",
        {"profile": "offline_volatile_admission_equivalence", "selection": selection.canonical_record()},
        requester=PrincipalAuthority.OPENAI_SUPERVISOR)
    policy = experimental_continuation_profile("tiny")
    policy_receipt = ContinuationPolicyReceipt(policy, governance_policy, governance)
    runtime, authority = RustRuntimeSession.create_continuation("transport.capture.fixture",
        continuation_policy=policy, continuation_policy_receipt=policy_receipt)
    continuation = ContinuationState.create(policy=policy, policy_receipt=policy_receipt,
        runtime_session=runtime, orchestration_state=state, runtime_snapshot=runtime.snapshot)
    context = SupervisorContext(task, governance, governance_policy, policy, continuation, state, runtime, authority)
    return context, selection, dependency, schema


def selected_capture_admission_conformance() -> dict:
    """All selected GET kinds use identical wire/frozen governance admission."""
    from .obligations import canonical_obligation_id
    from .openai_transport import OpenAITransportPolicy, decode_openai_response
    from .orchestration import ActionProposal, ProposalBatch, ProposalOrdering, Strategy
    from .readonly_adapters import GITHUB_READ_TOOLS, GitHubRequestPlan
    from .synthetic_protocol import ProposalKind
    from .transport_activation import _admit_selected_read

    context, selection, dependency, schema = _selected_capture_fixture_context()
    transport_policy = OpenAITransportPolicy("offline-conformance-model", ("offline-conformance-model",))
    records = []
    for index, name in enumerate(sorted(GITHUB_READ_TOOLS)):
        proposal = NormalizedProposal(ProposalKind.READ, {"proposal_key": f"capture-{index}", "tool_name": name,
            "arguments": selection.arguments_for(name), "target_obligation_keys": ["inspect"]})
        decoded, _ = decode_openai_response(offline_response_bytes(proposal, index), policy=transport_policy)
        occurrence = f"capture-0-{index}"
        action = ActionProposal(f"capture-{index}", name, selection.arguments_for(name),
            target_obligation_ids=(canonical_obligation_id("inspect"),), required_state_keys=("selected-source",),
            occurrence_key=occurrence)
        batch = ProposalBatch(f"capture-batch-{index}", Strategy(schema.strategy_key, {}, schema=schema), (action,),
                              ordering=ProposalOrdering.DECLARED_SEQUENCE)
        _, first, first_tool = _admit_selected_read(context, proposal, batch, dependency, occurrence)
        _, second, second_tool = _admit_selected_read(context, decoded, batch, dependency, occurrence)
        if (first.receipt.canonical_record() != second.receipt.canonical_record()
                or first.next_state.state_id != second.next_state.state_id
                or first_tool.canonical_record() != second_tool.canonical_record()):
            raise ValueError("wire and frozen capture admission differ")
        plan = GitHubRequestPlan(proposal, selection, dependency)
        records.append({"tool_name": name, "proposal_id": proposal.proposal_id,
            "request_id": plan.request_id, "admission_receipt_id": first.receipt.receipt_id,
            "tool_admission_receipt_id": first_tool.receipt_id, "next_state_id": first.next_state.state_id,
            "equivalent": True, "authority_class": "volatile_read", "cache_reuse": False})
    return {"profile": "offline_capture_admission_equivalence", "live_verification": False,
            "http_dispatches": 0, "native_requests": context.runtime_session.snapshot.requests,
            "selection_id": selection.selection_id, "cases": records}


def simulation_activation_conformance() -> dict:
    """Full isolated ladder; no production broker, SDK or HTTP request path."""
    from .obligations import canonical_obligation_id
    from .orchestration import ActionProposal, ProposalBatch, ProposalOrdering, Strategy
    from .readonly_adapters import SimulatedGitHubReadAdapter
    from .supervisor import FreshContextHandoff, SupervisorProjection
    from .synthetic_protocol import FakeSupervisor, ProposalKind
    from .transport_activation import (
        ActivationStage, OperatorStageAuthorization, SimulationActivationController, ToolProfile,
    )

    context, selection, dependency, schema = _selected_capture_fixture_context()
    projection = SupervisorProjection(context)
    detached = projection.canonical_record()
    handoff = FreshContextHandoff(projection).canonical_record()
    controller = SimulationActivationController(context.task.task_id, context.governance.governance_id,
        transport_policy_id=domain_fingerprint("ibae.offline-stage-deployment.v1", "simulation-only"),
        credential_reference_id=domain_fingerprint("ibae.offline-stage-credential.v1", "no-secret-source"))
    observations = [controller.verify_synthetic_stage().canonical_record()]
    smoke = tuple(NormalizedProposal.from_record(item)
                  for item in reference_synthetic_transcripts()["happy_path"]["proposals"])
    for stage, profile in ((ActivationStage.OPENAI_FAKE_TOOLS, ToolProfile.FAKE),
                           (ActivationStage.OPENAI_DETERMINISTIC_READS, ToolProfile.DETERMINISTIC_READONLY),
                           (ActivationStage.OPENAI_SELECTED_READS, ToolProfile.SELECTED_READONLY)):
        selected = stage is ActivationStage.OPENAI_SELECTED_READS
        controller.authorize(OperatorStageAuthorization(stage, controller.task_id, controller.governance_id,
            controller.epoch, "offline.fixture.operator", profile,
            ("github.repository",) if selected else (),
            transport_policy_id=controller.transport_policy_id,
            credential_reference_id=controller.credential_reference_id,
            selected_read_selection_ids=(selection.selection_id,) if selected else (), simulation_only=True))
        if selected:
            controller.register_selected_read(selection)
            proposal = NormalizedProposal(ProposalKind.READ, {"proposal_key": "capture.simulated.repository",
                "tool_name": "github.repository", "arguments": selection.arguments_for("github.repository"),
                "target_obligation_keys": ["inspect"]})
            owned = controller.propose(FakeSupervisor((proposal,)), detached, index=0, fresh_handoff=handoff)
            action = ActionProposal(proposal.payload["proposal_key"], "github.repository", proposal.payload["arguments"],
                target_obligation_ids=(canonical_obligation_id("inspect"),), required_state_keys=("selected-source",),
                occurrence_key=controller.capture_occurrence_key)
            batch = ProposalBatch("capture.simulated.batch", Strategy(schema.strategy_key, {}, schema=schema),
                                  (action,), ordering=ProposalOrdering.DECLARED_SEQUENCE)
            body = canonical_json({"full_name": "example/frozen-project", "default_branch": "main",
                                   "private": False, "archived": False}).encode()
            adapter = SimulatedGitHubReadAdapter(selection, controller, task_id=controller.task_id,
                                                governance_id=controller.governance_id, body=body)
            controller.capture_selected_read(adapter, owned, dependency, context=context, batch=batch)
            observation = controller.verify_selected_read_stage()
        else:
            supervisor = FakeSupervisor(smoke)
            for index in range(len(smoke)):
                controller.propose(supervisor, detached, index=index, fresh_handoff=handoff)
            observation = (controller.verify_fake_tool_stage() if stage is ActivationStage.OPENAI_FAKE_TOOLS
                           else controller.verify_fixture_stage())
        observations.append(observation.canonical_record())
    before = controller.canonical_record()
    if any(not item["simulation_only"] or item["live_transport_observed"] for item in observations):
        raise ValueError("offline activation incorrectly claimed live provenance")
    controller.rollback()
    after = controller.canonical_record()
    if before["consumed_transport_calls"] != after["consumed_transport_calls"]:
        raise ValueError("simulation rollback replenished its finite call budget")
    record = {"protocol_version": "IBAE-SIMULATED-ACTIVATION-CONFORMANCE-V1",
        "simulation_only": True, "live_verification": False, "network_dispatches": 0,
        "credential_resolutions": 0, "stage_observations": observations,
        "before_rollback": before, "after_rollback": after, "production_gate_authority": False}
    record["report_id"] = domain_fingerprint("ibae.simulated-activation-conformance.v1", record)
    return record
