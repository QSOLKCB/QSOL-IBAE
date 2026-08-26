"""Render deterministic bounded-state compact-evidence stress observations."""

from ibae import canonical_json, domain_fingerprint
from ibae.evidence import (
    MAX_COMPACT_EVIDENCE_BYTES,
    EvidenceAccumulator,
    EvidenceCounters,
    EvidenceLimits,
)

CASE_COUNTS = (1, 1_000, 100_000)


def _identity(domain: str, case_count: int, index: int | None = None) -> str:
    record: dict[str, object] = {"case_count": case_count}
    if index is not None:
        record["index"] = index
    return domain_fingerprint(domain, record)


def _run(case_count: int) -> dict[str, object]:
    task_id = _identity("ibae.v0.4-stress-task.v1", case_count)
    governance_id = _identity("ibae.v0.4-stress-governance.v1", case_count)
    orchestration_id = _identity(
        "ibae.v0.4-stress-orchestration.v1", case_count
    )
    accumulator = EvidenceAccumulator(
        task_id,
        governance_id,
        orchestration_id,
        authorization_manifest=(),
        limits=EvidenceLimits(
            max_cases=case_count,
            max_failure_details=1,
        ),
    )
    counters = EvidenceCounters(requests=1, actual_executions=1)
    for index in range(case_count):
        accumulator.record_case(
            case_id=_identity("ibae.v0.4-stress-case.v1", case_count, index),
            input_identity=_identity(
                "ibae.v0.4-stress-input.v1", case_count, index
            ),
            result_identity=_identity(
                "ibae.v0.4-stress-result.v1", case_count, index
            ),
            receipt_identity=_identity(
                "ibae.v0.4-stress-case-receipt.v1", case_count, index
            ),
            status="passed",
            counters=counters,
        )
    summary = accumulator.aggregate_summary()
    execution_id = domain_fingerprint(
        "ibae.v0.4-stress-execution.v1",
        {
            "aggregate_admissions": summary.aggregate_admission_identity,
            "aggregate_inputs": summary.aggregate_input_identity,
            "aggregate_receipts": summary.aggregate_receipt_identity,
            "aggregate_results": summary.aggregate_result_identity,
            "authorization_manifest": summary.authorization_manifest_identity,
            "case_count": case_count,
        },
    )
    receipt = accumulator.finalize(execution_id)
    compact_bytes = len(receipt.canonical_text.encode("utf-8"))
    if compact_bytes > MAX_COMPACT_EVIDENCE_BYTES:
        raise AssertionError("stress receipt exceeded the compact byte ceiling")
    if receipt.case_counts.total != case_count:
        raise AssertionError("stress receipt did not account for every input case")
    if receipt.source_bound:
        raise AssertionError("synthetic stress evidence must remain structural-only")
    return {
        "aggregate_result_id": receipt.aggregate_result_identity,
        "bounded_state": {
            "aggregate_identity_fields": 4,
            "authorization_manifest_count": (
                receipt.authorization_manifest_count
            ),
            "failure_detail_limit": 1,
            "retained_success_records": 0,
            "runtime_boundary_present": receipt.runtime_session_id is not None,
        },
        "case_count": case_count,
        "compact_bytes": compact_bytes,
        "compact_limit_bytes": MAX_COMPACT_EVIDENCE_BYTES,
        "receipt_id": receipt.receipt_id,
        "source_bound": receipt.source_bound,
        "status": receipt.status,
        "verification_scope": receipt.verification_scope,
        "within_compact_limit": compact_bytes <= MAX_COMPACT_EVIDENCE_BYTES,
    }


def main() -> None:
    print(
        canonical_json(
            {
                "cases": [_run(case_count) for case_count in CASE_COUNTS],
                "claim_scope": "structural_boundedness_only",
                "source_bound_final_governance_claim": False,
            }
        )
    )


if __name__ == "__main__":
    main()
