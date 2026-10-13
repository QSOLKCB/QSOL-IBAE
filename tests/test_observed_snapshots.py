"""Synthetic captured-content parity only; no live GET provenance is created."""

from dataclasses import FrozenInstanceError
import json

import pytest

from ibae.canonical import canonical_json, domain_fingerprint
from ibae.observed_snapshots import (
    MAX_OBSERVED_SNAPSHOT_BYTES, MAX_OBSERVED_SNAPSHOTS, MAX_SNAPSHOT_REPORT_BYTES,
    ObservedReadSnapshot, SnapshotReadAdapter, SNAPSHOT_TOOL_NAME,
    verify_observed_snapshot_stage, verify_snapshot_native_equivalence,
)
from ibae.readonly_adapters import GitHubReadSelection, GitHubRequestPlan, parse_github_response
from ibae.synthetic_protocol import (
    AdapterInterface, FakeReadUniverse, NormalizedProposal, ProposalKind, SyntheticReadFixture,
)


def _synthetic_receipt(index=0, *, archived=False, status=200, metadata=None):
    """Explicit frozen source fixture, never an activation-owned live capture."""
    selection = GitHubReadSelection("example", f"project-{index}", "main", "a" * 40, index + 1)
    proposal = NormalizedProposal(ProposalKind.READ, {"proposal_key": "inspect.selected",
        "tool_name": "github.repository", "arguments": selection.arguments_for("github.repository"),
        "target_obligation_keys": ["inspect"]})
    plan = GitHubRequestPlan(proposal, selection, "1" * 64)
    body = {"full_name": f"example/project-{index}", "default_branch": "main",
            "private": False, "archived": archived}
    return parse_github_response(plan, status, json.dumps(body).encode(), metadata)


def _synthetic_snapshot(index=0, **kwargs):
    return ObservedReadSnapshot.from_receipt(_synthetic_receipt(index, **kwargs))


def _large_synthetic_snapshot(index):
    """Full one-page CI shape and maximum bounded proposal target strings."""
    selection = GitHubReadSelection("example", f"large-project-{index}", "main", "a" * 40, index + 1)
    proposal = NormalizedProposal(ProposalKind.READ, {"proposal_key": "inspect.selected",
        "tool_name": "github.check_runs", "arguments": selection.arguments_for("github.check_runs"),
        "target_obligation_keys": [f"obligation.{item:03d}." + "x" * 113 for item in range(128)]})
    plan = GitHubRequestPlan(proposal, selection, "1" * 64)
    body = {"total_count": 100, "check_runs": [{"id": item + 1,
        "name": f"check-{item:03d}." + "x" * 246, "head_sha": "a" * 40,
        "status": "completed", "conclusion": "success"} for item in range(100)]}
    return ObservedReadSnapshot(parse_github_response(plan, 200, json.dumps(body).encode()))


def _proposal(snapshot):
    return NormalizedProposal(ProposalKind.READ, {"proposal_key": "consume.snapshot",
        "tool_name": SNAPSHOT_TOOL_NAME, "arguments": snapshot.arguments,
        "target_obligation_keys": ["inspect"]})


def test_public_snapshot_construction_only_freezes_unverified_content():
    snapshot = _synthetic_snapshot()
    record = snapshot.canonical_record()
    assert record["content_immutable"] is True
    assert record["consumption_scope"] == "exact_retained_observation_content"
    assert record["live_capture_verified"] is False
    assert record["current_remote_state_verified"] is False
    assert record["remote_producer_authenticated"] is False
    assert record["native_authority"] is False
    assert record["source_receipt_id"] == snapshot.source_receipt.receipt_id
    assert ObservedReadSnapshot.from_record(record) == snapshot
    assert snapshot.arguments == {"snapshot_id": snapshot.snapshot_id}
    assert snapshot.snapshot_id != snapshot.dependency_fingerprint
    assert snapshot.source_receipt.canonical_record()["source_semantics"]["network_operation_cacheable"] is False


def test_snapshot_values_and_source_receipts_are_detached_and_immutable():
    snapshot = _synthetic_snapshot()
    identity = snapshot.snapshot_id
    record = snapshot.canonical_record()
    record["source_receipt"]["output"]["archived"] = True
    snapshot.source_receipt.output["archived"] = True
    snapshot.arguments["snapshot_id"] = "0" * 64
    assert snapshot.source_receipt.output["archived"] is False
    assert snapshot.snapshot_id == identity
    with pytest.raises(FrozenInstanceError):
        snapshot._text = "{}"


def test_changed_observation_content_or_source_metadata_gets_a_new_content_identity():
    original = _synthetic_snapshot()
    changed = _synthetic_snapshot(archived=True)
    assert changed.source_receipt.canonical_record()["request"]["selection"] == original.source_receipt.canonical_record()["request"]["selection"]
    assert changed.snapshot_id != original.snapshot_id
    assert changed.dependency_fingerprint != original.dependency_fingerprint
    assert changed.tool_key != original.tool_key
    metadata = {"request_id": "AB:12", "etag": '"abc123"', "has_next_page": False}
    observed_later = _synthetic_snapshot(metadata=metadata)
    assert observed_later.source_receipt.observation_id == original.source_receipt.observation_id
    assert observed_later.snapshot_id != original.snapshot_id
    assert observed_later.dependency_fingerprint != original.dependency_fingerprint


@pytest.mark.parametrize(("field", "value"), [
    ("live_capture_verified", True), ("current_remote_state_verified", True),
    ("remote_producer_authenticated", True), ("native_authority", True),
    ("content_immutable", 1), ("consumption_scope", "current_remote_state"),
    ("source_receipt_id", "0" * 64), ("unknown_field", False),
])
def test_reconstruction_cannot_claim_provenance_or_change_the_closed_scope(field, value):
    record = _synthetic_snapshot().canonical_record()
    record[field] = value
    with pytest.raises((TypeError, ValueError)):
        ObservedReadSnapshot.from_record(record)


def test_snapshot_reader_matches_the_exact_frozen_source_fixture():
    snapshot = _synthetic_snapshot()
    fixture = SyntheticReadFixture(SNAPSHOT_TOOL_NAME, snapshot.arguments, snapshot.dependency_fingerprint,
        snapshot.canonical_record(), interface=AdapterInterface.READ)
    frozen = FakeReadUniverse((fixture,))
    adapter = SnapshotReadAdapter((snapshot,))
    expected = frozen.lookup(SNAPSHOT_TOOL_NAME, snapshot.arguments, snapshot.dependency_fingerprint)
    assert adapter.lookup(SNAPSHOT_TOOL_NAME, snapshot.arguments, snapshot.dependency_fingerprint) == expected
    assert adapter.read(_proposal(snapshot), snapshot.dependency_fingerprint) == expected
    first = adapter.read(_proposal(snapshot), snapshot.dependency_fingerprint)
    first["source_receipt"]["output"]["archived"] = True
    assert adapter.read(_proposal(snapshot), snapshot.dependency_fingerprint) == expected


def test_snapshot_reader_never_refetches_or_falls_back_on_wrong_arguments():
    snapshot = _synthetic_snapshot()
    adapter = SnapshotReadAdapter((snapshot,))
    with pytest.raises(LookupError):
        adapter.lookup(SNAPSHOT_TOOL_NAME, snapshot.arguments, "0" * 64)
    with pytest.raises(LookupError):
        adapter.lookup(SNAPSHOT_TOOL_NAME, {"snapshot_id": "0" * 64}, snapshot.dependency_fingerprint)
    for args in ({}, {"snapshot_id": snapshot.snapshot_id, "refresh": True}, {"snapshot_id": True}):
        with pytest.raises((TypeError, ValueError)):
            adapter.lookup(SNAPSHOT_TOOL_NAME, args, snapshot.dependency_fingerprint)
    with pytest.raises(ValueError):
        adapter.lookup("github.repository", snapshot.arguments, snapshot.dependency_fingerprint)
    with pytest.raises(ValueError):
        adapter.read(NormalizedProposal(ProposalKind.CONTINUE, {}), snapshot.dependency_fingerprint)


def test_snapshot_set_is_unique_bounded_ordered_and_exact_typed():
    left, right = _synthetic_snapshot(), _synthetic_snapshot(1)
    assert SnapshotReadAdapter((left, right)).canonical_record() == SnapshotReadAdapter((right, left)).canonical_record()
    with pytest.raises(ValueError):
        SnapshotReadAdapter((left, left))
    with pytest.raises(ValueError):
        SnapshotReadAdapter((left,) * (MAX_OBSERVED_SNAPSHOTS + 1))
    with pytest.raises(TypeError):
        SnapshotReadAdapter([left])
    with pytest.raises(TypeError):
        SnapshotReadAdapter((left.canonical_record(),))
    with pytest.raises(TypeError):
        ObservedReadSnapshot(left.source_receipt.canonical_record())


def test_ordinary_container_subclasses_and_oversized_records_fail_closed():
    class PlainDict(dict):
        pass

    class PlainSnapshot(ObservedReadSnapshot):
        pass

    snapshot = _synthetic_snapshot()
    with pytest.raises(TypeError):
        ObservedReadSnapshot.from_record(PlainDict(snapshot.canonical_record()))
    with pytest.raises(TypeError):
        SnapshotReadAdapter((PlainSnapshot(snapshot.source_receipt),))
    record = snapshot.canonical_record()
    record["extra"] = "x" * (MAX_OBSERVED_SNAPSHOT_BYTES + 1)
    with pytest.raises(ValueError):
        ObservedReadSnapshot.from_record(record)


def test_closed_native_probe_proves_captured_content_and_finite_cold_hit_accounting(monkeypatch):
    import socket

    def unavailable(*args, **kwargs):
        raise AssertionError("snapshot consumption cannot contact a live source")

    monkeypatch.setattr(socket, "socket", unavailable)
    monkeypatch.setattr(socket, "create_connection", unavailable)
    monkeypatch.setattr(socket, "getaddrinfo", unavailable)
    snapshots = (_synthetic_snapshot(), _synthetic_snapshot(1))
    report = verify_observed_snapshot_stage(snapshots)
    assert report["equivalent"] is True
    assert report["live_verification"] is False
    assert report["current_remote_state_verified"] is False
    assert report["final_acceptance"] is False
    assert report["transport_calls"] == 0
    assert report["source_snapshot_ids"] == sorted(item.snapshot_id for item in snapshots)
    assert report["fresh_native_runs"] == 2
    assert report["native_proof"]["native_compact_source_bound"] is True
    assert report["native_proof"]["counters"] == {"requests": 4, "executions": 2, "cache_hits": 2, "retries": 0}
    assert report["native_total_counters"] == {"requests": 8, "executions": 4, "cache_hits": 4, "retries": 0}
    assert len(canonical_json(report).encode()) <= MAX_SNAPSHOT_REPORT_BYTES
    assert "source_receipt" not in report["native_proof"]
    identity = report.pop("report_id")
    assert identity == domain_fingerprint("ibae.observed-snapshot-equivalence-report.v1", report)


def test_native_probe_replays_canonically_across_input_order_and_fresh_authority():
    snapshots = (_synthetic_snapshot(), _synthetic_snapshot(1))
    first = verify_observed_snapshot_stage(snapshots)
    assert first == verify_observed_snapshot_stage(tuple(reversed(snapshots)))
    assert first == verify_snapshot_native_equivalence(snapshots)
    changed = verify_observed_snapshot_stage((_synthetic_snapshot(archived=True), snapshots[1]))
    assert first["report_id"] != changed["report_id"]
    assert first["native_proof"]["native_compact_receipt_id"] != changed["native_proof"]["native_compact_receipt_id"]


def test_unavailable_source_receipt_can_be_preserved_without_claiming_source_success():
    snapshot = _synthetic_snapshot(status=404)
    assert snapshot.source_receipt.output is None
    assert snapshot.source_receipt.canonical_record()["status"] == "unavailable"
    report = verify_observed_snapshot_stage((snapshot,))
    assert report["equivalent"] is True
    assert report["live_verification"] is False
    assert report["final_acceptance"] is False


def test_native_probe_requires_nonempty_unique_exact_snapshots():
    snapshot = _synthetic_snapshot()
    for values in ((), (snapshot, snapshot), (snapshot,) * 17):
        with pytest.raises(ValueError):
            verify_observed_snapshot_stage(values)
    for values in ([snapshot], (snapshot.canonical_record(),)):
        with pytest.raises(TypeError):
            verify_observed_snapshot_stage(values)


def test_sixteen_near_limit_snapshots_have_bounded_native_cold_hit_proofs():
    snapshots = tuple(_large_synthetic_snapshot(index) for index in range(MAX_OBSERVED_SNAPSHOTS))
    assert all(55_000 < len(canonical_json(item.canonical_record()).encode()) <= MAX_OBSERVED_SNAPSHOT_BYTES
               for item in snapshots)
    report = verify_observed_snapshot_stage(snapshots)
    assert report["snapshot_count"] == 16
    assert len(report["source_snapshot_ids"]) == 16
    assert report["equivalent"] is True
    assert report["native_proof"]["native_compact_source_bound"] is True
    assert report["native_proof"]["counters"] == {"requests": 32, "executions": 16, "cache_hits": 16, "retries": 0}
    assert report["native_total_counters"] == {"requests": 64, "executions": 32, "cache_hits": 32, "retries": 0}
    assert report["transport_calls"] == 0
    assert report["live_verification"] is False
    assert len(canonical_json(report).encode()) <= MAX_SNAPSHOT_REPORT_BYTES
