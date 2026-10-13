"""Offline conformance never claims provider calls or live recovery."""
import json
from pathlib import Path

from ibae.canonical import canonical_json, domain_fingerprint
from ibae.transport_conformance import verify_readonly_fixture_stage, v0_6c_reference_fixture


def test_real_native_fixture_paths_are_equivalent_without_final_acceptance():
    record = verify_readonly_fixture_stage()
    assert record["equivalent"] is True
    assert record["live_verification"] is False
    assert record["fake_path"] == record["fixture_path"]
    assert record["fixture_path"]["compact"]["status"] == "complete_no_failures"
    assert len(record["fixture_path"]["runtime_receipts"]) == 2
    assert all(item["status"] == "accepted" for item in record["fixture_path"]["runtime_receipts"])
    assert "final_acceptance" not in record
    identity = record.pop("report_id")
    assert identity == domain_fingerprint("ibae.readonly-fixture-equivalence.v1", record)


def test_golden_transport_conformance_replays_without_network(monkeypatch):
    import socket
    def unavailable(*args, **kwargs):
        raise AssertionError("offline conformance attempted network")
    monkeypatch.setattr(socket, "socket", unavailable)
    monkeypatch.setattr(socket, "create_connection", unavailable)
    monkeypatch.setattr(socket, "getaddrinfo", unavailable)
    record = v0_6c_reference_fixture()
    assert record["offline_only"] is True
    assert record["live_verification"] is False
    assert record["external_effects_executed"] == 0
    assert len(record["equivalent_streams"]) == 8
    assert all(item["equivalent"] for item in record["equivalent_streams"].values())
    expected = Path("fixtures/v0.6C/openai-readonly-reference.json").read_bytes()
    assert expected == (canonical_json(record) + "\n").encode()
    assert json.loads(expected)["live_gate_status"].startswith("blocked_")


def test_optional_provider_import_has_no_sdk_or_environment_dependency():
    # A subprocess gives a fresh module cache; no credential is copied into it.
    import os
    import subprocess
    import sys
    environment = {key: os.environ[key] for key in
                   ("PATH", "HOME", "LANG", "LC_ALL", "PYTHONPATH", "LD_LIBRARY_PATH") if key in os.environ}
    result = subprocess.run([sys.executable, "-c", "import sys, ibae; assert 'openai' not in sys.modules"],
                            env=environment, check=True, capture_output=True, timeout=30)
    assert result.stdout == result.stderr == b""


def test_selected_capture_admission_parity_covers_every_read_kind():
    from ibae.readonly_adapters import GITHUB_READ_TOOLS
    from ibae.transport_conformance import selected_capture_admission_conformance
    record = selected_capture_admission_conformance()
    assert record["live_verification"] is False
    assert record["http_dispatches"] == record["native_requests"] == 0
    assert {case["tool_name"] for case in record["cases"]} == set(GITHUB_READ_TOOLS)
    assert all(case["equivalent"] and case["authority_class"] == "volatile_read"
               and case["cache_reuse"] is False for case in record["cases"])


def test_frozen_observation_native_proof_does_not_claim_live_capture():
    from ibae.transport_conformance import synthetic_snapshot_conformance
    record = synthetic_snapshot_conformance()
    assert record["transport_calls"] == 0
    assert record["live_capture_verified"] is False
    proof = record["native_consumption_equivalence"]
    assert proof["live_verification"] is False
    assert proof["equivalent"] is True
    assert proof["transport_calls"] == 0
    assert record["snapshot_id"] in proof["source_snapshot_ids"]


def test_isolated_stage_ladder_never_dispatches_credentials_or_network(monkeypatch):
    import socket
    from ibae.openai_transport import OpenAICredentialBroker
    from ibae import readonly_adapters
    from ibae.transport_conformance import simulation_activation_conformance
    def forbidden(*args, **kwargs):
        raise AssertionError("isolated simulation attempted production dispatch")
    monkeypatch.setattr(OpenAICredentialBroker, "_request", forbidden)
    monkeypatch.setattr(readonly_adapters.http.client, "HTTPSConnection", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    record = simulation_activation_conformance()
    assert record["simulation_only"] is True
    assert record["live_verification"] is record["production_gate_authority"] is False
    assert record["network_dispatches"] == record["credential_resolutions"] == 0
    assert [item["stage"] for item in record["stage_observations"]] == [0, 1, 2, 3]
    assert all(item["simulation_only"] and not item["live_transport_observed"]
               for item in record["stage_observations"])
    before, after = record["before_rollback"], record["after_rollback"]
    assert before["active_stage_verification"] == "simulation_passed"
    assert before["consumed_transport_calls"] == after["consumed_transport_calls"] == 8
    assert before["network_dispatch_allowed"] is after["network_dispatch_allowed"] is False
