"""Bounded golden-input replay for the offline synthetic integration gate."""
from __future__ import annotations

from .canonical import canonical_json, domain_fingerprint
from .synthetic_protocol import bounded_synthetic_data
from .synthetic_recovery import RecoveryScenario, SYNTHETIC_RECOVERY_SCENARIOS, synthetic_recovery_corpus
from .synthetic_runner import reference_synthetic_transcripts, run_synthetic_transcript

SYNTHETIC_INPUT_VERSION = "IBAE-SYNTHETIC-GOLDEN-INPUT-V1"
SYNTHETIC_CONFORMANCE_VERSION = "IBAE-SYNTHETIC-CONFORMANCE-V1"
MAX_SYNTHETIC_INPUT_BYTES = 1_048_576
MAX_SYNTHETIC_OUTPUT_BYTES = 2_097_152
MAX_CONTROL_TRANSCRIPTS = 16


def synthetic_input_fixture() -> dict:
    """The closed default corpus; persisted inputs are replayed via the parser."""
    return {
        "protocol_version": SYNTHETIC_INPUT_VERSION,
        "offline_only": True,
        "control_transcripts": reference_synthetic_transcripts(),
        "recovery_scenarios": [item.canonical_record() for item in sorted(SYNTHETIC_RECOVERY_SCENARIOS, key=lambda item: item.scenario_id)],
    }


def replay_synthetic_fixture(record: dict) -> dict:
    """Run supplied bounded inputs through fresh native authority, never restore it."""
    record = bounded_synthetic_data(record, max_bytes=MAX_SYNTHETIC_INPUT_BYTES)
    fields = {"protocol_version", "offline_only", "control_transcripts", "recovery_scenarios"}
    if type(record) is not dict or set(record) != fields:
        raise ValueError("synthetic golden input has an invalid closed schema")
    if record["protocol_version"] != SYNTHETIC_INPUT_VERSION or record["offline_only"] is not True:
        raise ValueError("only the versioned offline synthetic profile is supported")
    controls = record["control_transcripts"]
    if type(controls) is not dict or not 1 <= len(controls) <= MAX_CONTROL_TRANSCRIPTS:
        raise ValueError("synthetic control transcript count is out of bounds")
    from ._records import require_symbol
    for key in controls:
        require_symbol("control transcript name", key)
    scenarios = record["recovery_scenarios"]
    if type(scenarios) is not list or not 1 <= len(scenarios) <= 64:
        raise ValueError("synthetic recovery scenario count is out of bounds")
    parsed = tuple(RecoveryScenario.from_record(item) for item in scenarios)
    ids = [item.scenario_id for item in parsed]
    if ids != sorted(set(ids)):
        raise ValueError("recovery scenarios must have unique canonical ordering")
    # Each runner parses and validates the actual input; a name is never an
    # authorization or a substitute for executing that normalized stream.
    results = {key: run_synthetic_transcript(controls[key]).canonical_record() for key in sorted(controls)}
    recovery = synthetic_recovery_corpus(scenarios=parsed)
    telemetry = {
        "profile": "synthetic-exact-counts-v1", "correctness_authority": False,
        "units": "counts-over-the-complete-bounded-input-stream",
        "ratio_threshold": None, "diversification_status": "candidate_not_activated",
        "runs": {key: {
            "proposal_arrivals": len(controls[key]["proposals"]),
            "processed_proposals": len(result["events"]),
            "runtime_requests": result["final_runtime"]["counters"]["requests"],
            "actual_executions": result["final_runtime"]["counters"]["executions"],
            "unresolved_obligations": len(result["summary"]["unresolved_obligation_ids"]),
            "rejections": sum(len(segment["rejections"]) for segment in result["segments"]),
        } for key, result in results.items()},
    }
    body = {
        "protocol_version": SYNTHETIC_CONFORMANCE_VERSION,
        "offline_only": True, "live_recovery_verified": False,
        "restores_native_authority": False, "external_effects_executed": 0,
        "input_id": domain_fingerprint("ibae.synthetic-golden-input.v1", record),
        "control_results": results, "recovery_corpus": recovery, "research_telemetry": telemetry,
        "control_transcript_count": len(results), "recovery_scenario_count": len(parsed),
    }
    if len(canonical_json(body).encode("utf-8")) > MAX_SYNTHETIC_OUTPUT_BYTES - 128:
        raise ValueError("synthetic conformance output exceeds declared bound")
    body["conformance_id"] = domain_fingerprint("ibae.synthetic-conformance.v1", body)
    return body


def v0_6b_reference_fixture() -> dict:
    return replay_synthetic_fixture(synthetic_input_fixture())
