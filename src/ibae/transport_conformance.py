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
              "live_gate_status": "blocked_missing_operator_credentials_and_live_stage_evidence"}
    record["conformance_id"] = domain_fingerprint("ibae.openai-readonly-conformance.v1", record)
    return record
