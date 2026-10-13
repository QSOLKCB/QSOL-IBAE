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
