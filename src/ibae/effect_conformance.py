"""Closed deterministic native effect scenarios, never live-effect evidence."""
from __future__ import annotations

from types import SimpleNamespace


from .canonical import canonical_json, domain_fingerprint
from .continuation import ContinuationPolicyReceipt, ContinuationState, experimental_continuation_profile
from .effects import (
    EffectCommand, EffectEntry, EffectProfile,
    EffectReceipt, EffectSession, SyntheticEffectOutcome as Outcome,
)
from .governance import (
    GovernancePolicy, GovernanceWrapper, PrincipalAuthority, ProviderAuthority,
    SUPPORTED_REQUIRED_GATE_KEYS, ToolAuthorityClass, ToolPermission,
)
from .obligations import Obligation
from .orchestration import (
    ActionProposal, Capability, DecisionStatus, OrchestrationState,
    ProposalBatch, ProposalOrdering, ReplaySafety, Strategy, StrategySchema, admit_batch,
)
from .runtime import RustRuntimeSession


def _effect_bundle(
    *, tools=("synthetic_set",), outcomes=None, arguments=None,
    limits=None, initial_cells=None, session_key="effects.reference", commitment=True,
):
    initial_cells = {"counter": 0} if initial_cells is None else initial_cells
    outcomes = ((Outcome.SUCCESS,),) * len(tools) if outcomes is None else outcomes
    arguments = tuple(
        {"key": "counter", "expected_value": index, "value" if name == "synthetic_set" else "delta": index + 1 if name == "synthetic_set" else 1}
        for index, name in enumerate(tools)
    ) if arguments is None else arguments
    policy = GovernancePolicy(
        policy_key="synthetic.effects", policy_version=1, task_profile="tiny", task_profile_version=1,
        provider_authority=ProviderAuthority.OPENAI,
        tool_permissions=(
            ToolPermission("synthetic_set", ToolAuthorityClass.IDEMPOTENT_MUTATION, True, False),
            ToolPermission("synthetic_increment", ToolAuthorityClass.NON_IDEMPOTENT_MUTATION, True, False),
        ),
        required_gate_keys=tuple(sorted(SUPPORTED_REQUIRED_GATE_KEYS)),
    )
    capabilities = {
        name: Capability(name, ReplaySafety.OCCURRENCE_SENSITIVE, "Closed synthetic effect.",
            semantic_argument_keys=("expected_value", "key", "value") if name == "synthetic_set" else ("delta", "expected_value", "key"))
        for name in sorted(set(tools))
    }
    obligation = Obligation("synthetic.effects", "Verify the declared synthetic effects.")
    schema = StrategySchema("effects")
    state = OrchestrationState.create((obligation,), capabilities=tuple(capabilities.values()), strategy_schemas=(schema,))
    proposals = tuple(ActionProposal(
        f"effect.{index}", name, argument, target_obligation_ids=(obligation.obligation_id,), occurrence_key=f"occurrence.{index}",
    ) for index, (name, argument) in enumerate(zip(tools, arguments)))
    batch = ProposalBatch("effects", Strategy("effects", {}, schema=schema), proposals, ProposalOrdering.DECLARED_SEQUENCE)
    admitted = admit_batch(state, batch)
    if not all(decision.status is DecisionStatus.ADMITTED for decision in admitted.receipt.decisions):
        raise AssertionError("closed effect corpus failed actual typed admission")
    dependency = state.epistemic_state.dependency_digest(())
    entries = tuple(EffectEntry(capabilities[proposal.capability], proposal, decision, dependency, outcome)
        for proposal, decision, outcome in zip(proposals, admitted.receipt.decisions, outcomes))
    profile = EffectProfile(policy.governance_id, entries, initial_cells=initial_cells, limits=limits)
    wrapper = GovernanceWrapper(policy)
    task, governance = wrapper.admit_task("synthetic.effects", {"effect_profile_id": profile.profile_id} if commitment else {"goal": "unbound effects"}, requester=PrincipalAuthority.OPENAI_SUPERVISOR)
    admissions = tuple(wrapper.admit_tool(
        task, governance, decision, proposal, capabilities[proposal.capability],
        ToolAuthorityClass.IDEMPOTENT_MUTATION if proposal.capability == "synthetic_set" else ToolAuthorityClass.NON_IDEMPOTENT_MUTATION,
        dependency_state_id=dependency, requester=PrincipalAuthority.DETERMINISTIC_ORCHESTRATOR,
    ) for proposal, decision in zip(proposals, admitted.receipt.decisions))
    continuation = experimental_continuation_profile("tiny")
    continuation_receipt = ContinuationPolicyReceipt(continuation, policy, governance)
    runtime, authority = RustRuntimeSession.create_continuation(session_key, continuation_policy=continuation, continuation_policy_receipt=continuation_receipt)
    continuation_state = ContinuationState.create(policy=continuation, policy_receipt=continuation_receipt, runtime_session=runtime, orchestration_state=admitted.next_state, runtime_snapshot=runtime.snapshot)
    return SimpleNamespace(continuation_state=continuation_state, profile=profile, policy=policy, task=task, governance=governance,
        admissions=admissions, runtime=runtime, authority=authority, entries=entries, proposals=proposals,
        capabilities=capabilities, decisions=admitted.receipt.decisions, dependency=dependency)


def _create(bundle, *, enabled=True):
    return EffectSession.create(bundle.runtime, bundle.authority, profile=bundle.profile,
        task=bundle.task, governance_policy=bundle.policy, governance=bundle.governance,
        tool_admissions=bundle.admissions, enabled=enabled)


def _perform(session, bundle, kind=EffectCommand.EXECUTE, index=0):
    command = session.command(kind, bundle.entries[index].action_id)
    return session.dispatch(command, session.authorize(command, bundle.authority))


def _snapshot(session):
    return canonical_json(session.snapshot.canonical_record())


def reference_effect_inputs() -> dict:
    """Closed golden plans; caller records never supply executors or success gates."""
    cases = {}
    for tool in ("synthetic_set", "synthetic_increment"):
        for case, outcomes, steps, statuses, final_value in (
            ("success", ["success"], ["execute_effect"], ["applied"], 1),
            ("failure_then_retry", ["fail_before", "success"], ["execute_effect", "retry_effect"], ["not_applied", "applied"], 1),
            ("lost_ack_after", ["crash_after"], ["execute_effect", "reconcile_effect"], ["ambiguous", "reconciled_applied"], 1),
            ("lost_ack_before", ["crash_before", "success"], ["execute_effect", "reconcile_effect", "retry_effect"], ["ambiguous", "reconciled_not_applied", "applied"], 1),
            ("unknown", ["ambiguous_unknown"], ["execute_effect", "reconcile_effect"], ["ambiguous", "ambiguous"], 1),
            ("cancel_before", ["success"], ["cancel_effect"], ["cancelled"], 0),
            ("cancel_ambiguous", ["crash_after"], ["execute_effect", "cancel_effect", "reconcile_effect"], ["ambiguous", "ambiguous", "reconciled_applied"], 1),
        ):
            cases[f"{tool}.{case}"] = {"tools": [tool], "outcomes": [outcomes],
                "steps": [[step, 0] for step in steps], "expected_statuses": statuses,
                "initial_cells": {"counter": 0}, "arguments": [{"key": "counter", "expected_value": 0,
                    "value" if tool == "synthetic_set" else "delta": 1}],
                "expected_cells": {"counter": final_value}, "expected_complete": statuses[-1] in {"applied", "reconciled_applied"}}
    cases["ordered.partial_completion"] = {
        "tools": ["synthetic_set", "synthetic_increment"], "outcomes": [["success"], ["fail_before"]],
        "steps": [["execute_effect", 0], ["execute_effect", 1]], "expected_statuses": ["applied", "not_applied"],
        "initial_cells": {"counter": 0}, "arguments": [{"key": "counter", "expected_value": 0, "value": 1}, {"key": "counter", "expected_value": 1, "delta": 1}],
        "expected_cells": {"counter": 1}, "expected_complete": False}
    cases["ordered.distinct_same_payload"] = {
        "tools": ["synthetic_set", "synthetic_set"], "outcomes": [["success"], ["success"]],
        "steps": [["execute_effect", 0], ["execute_effect", 1]], "expected_statuses": ["applied", "applied"],
        "initial_cells": {"counter": 1}, "arguments": [{"key": "counter", "expected_value": 1, "value": 1}] * 2,
        "expected_cells": {"counter": 1}, "expected_complete": True}
    cases["preserve.uncommitted_content"] = {
        "tools": ["synthetic_set"], "outcomes": [["success"]],
        "steps": [["execute_effect", 0]], "expected_statuses": ["not_applied"],
        "initial_cells": {"counter": 99}, "arguments": [{"key": "counter", "expected_value": 0, "value": 1}],
        "expected_cells": {"counter": 99}, "expected_complete": False}
    cases["ordered.cancel_reconciled_not_applied"] = {
        "tools": ["synthetic_set", "synthetic_increment"], "outcomes": [["crash_before"], ["success"]],
        "steps": [["execute_effect", 0], ["cancel_effect", 0], ["reconcile_effect", 0], ["execute_effect", 1]],
        "expected_statuses": ["ambiguous", "ambiguous", "reconciled_not_applied", "applied"],
        "initial_cells": {"counter": 0}, "arguments": [{"key": "counter", "expected_value": 0, "value": 1}, {"key": "counter", "expected_value": 0, "delta": 1}],
        "expected_cells": {"counter": 1}, "expected_complete": False}
    return {"protocol_version": "IBAE-SYNTHETIC-EFFECT-INPUTS-V1", "cases": cases}


def replay_effect_inputs(inputs: dict) -> dict:
    """Reconstruct fresh native authority for each exact closed input scenario."""
    # The fixture verifier intentionally accepts only the fixed reviewed corpus.
    # It cannot be repurposed to introduce arbitrary tools or acceptance rules.
    from .effects import _json_copy
    copied = _json_copy(inputs)
    if canonical_json(copied) != canonical_json(reference_effect_inputs()):
        raise ValueError("effect conformance input differs from the closed reference corpus")
    results = {}
    for name, case in sorted(copied["cases"].items()):
        bundle = _effect_bundle(tools=tuple(case["tools"]),
            outcomes=tuple(tuple(Outcome(item) for item in sequence) for sequence in case["outcomes"]),
            arguments=tuple(case["arguments"]), initial_cells=case["initial_cells"], session_key=name)
        session = _create(bundle)
        initial = session.snapshot.canonical_record()
        legacy_before = bundle.runtime.snapshot._canonical_text()
        receipts = []
        for (command, index), expected in zip(case["steps"], case["expected_statuses"]):
            receipt = _perform(session, bundle, EffectCommand(command), index)
            if not session.validates_receipt(receipt) or receipt.status != expected:
                raise AssertionError("native effect receipt/source did not satisfy the declared predicate")
            if EffectReceipt(receipt.canonical_record()).source_bound:
                raise AssertionError("serialized effect receipt reconstructed native authority")
            receipts.append(receipt.canonical_record())
        final = session.snapshot.canonical_record()
        if final["cells"] != case["expected_cells"] or session.snapshot.manifest_complete is not case["expected_complete"]:
            raise AssertionError("native synthetic state did not satisfy the declared predicate")
        if bundle.runtime.snapshot._canonical_text() != legacy_before:
            raise AssertionError("effect work changed accepted legacy read accounting")
        results[name] = {"profile_id": bundle.profile.profile_id, "task_id": bundle.task.task_id,
            "initial_snapshot": initial, "receipts": receipts, "final_snapshot": final,
            "manifest_complete": session.snapshot.manifest_complete, "partial": session.snapshot.partial,
            "native_source_verified": True, "serialized_receipts_authoritative": False,
            "legacy_runtime_unchanged": True, "global_task_acceptance": False}
    body = {"protocol_version": "IBAE-SYNTHETIC-EFFECT-CONFORMANCE-V1",
        "input_id": domain_fingerprint("ibae.synthetic-effect-inputs-id.v1", copied),
        "cases": results, "scenario_count": len(results), "live_effects_enabled": False,
        "live_recovery_verified": False, "external_mutations": 0,
        "evidence_scope": "closed-synthetic-native-in-process"}
    return {**body, "fixture_id": domain_fingerprint("ibae.synthetic-effect-conformance-id.v1", body)}


def v0_6d_reference_fixture() -> dict:
    return replay_effect_inputs(reference_effect_inputs())
