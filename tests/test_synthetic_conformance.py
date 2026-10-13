"""Golden-input replay, bounded transport and no-live-connection contract."""
import ast
import json
from pathlib import Path
import socket
import urllib.request

import pytest

from ibae.canonical import canonical_json
from ibae.synthetic_conformance import (
    MAX_SYNTHETIC_INPUT_BYTES, MAX_SYNTHETIC_OUTPUT_BYTES,
    replay_synthetic_fixture, synthetic_input_fixture, v0_6b_reference_fixture,
)

ROOT = Path(__file__).parents[1]


def test_golden_input_and_replay_are_byte_identical_to_checked_in_evidence():
    path = ROOT / "fixtures/v0.6B"
    source = json.loads((path / "supervisor-transcripts.json").read_text())
    assert canonical_json(synthetic_input_fixture()) + "\n" == (path / "supervisor-transcripts.json").read_text()
    evidence = replay_synthetic_fixture(source)
    assert canonical_json(evidence) + "\n" == (path / "synthetic-recovery-reference.json").read_text()
    assert evidence["live_recovery_verified"] is False
    assert evidence["external_effects_executed"] == 0
    assert evidence["restores_native_authority"] is False
    telemetry = evidence["research_telemetry"]
    assert telemetry["correctness_authority"] is False
    assert telemetry["ratio_threshold"] is None
    assert telemetry["runs"]["happy_path"]["actual_executions"] == 2
    assert telemetry["runs"]["fake_completion_claim"]["unresolved_obligations"] == 1
    assert len(canonical_json(source).encode()) <= MAX_SYNTHETIC_INPUT_BYTES
    assert len(canonical_json(evidence).encode()) <= MAX_SYNTHETIC_OUTPUT_BYTES


def test_full_synthetic_replay_cannot_use_network_or_resolve_dns(monkeypatch):
    def unavailable(*args, **kwargs):
        raise AssertionError("offline synthetic conformance attempted a live connection")
    monkeypatch.setattr(socket, "socket", unavailable)
    monkeypatch.setattr(socket, "create_connection", unavailable)
    monkeypatch.setattr(socket, "getaddrinfo", unavailable)
    monkeypatch.setattr(urllib.request, "urlopen", unavailable)
    assert v0_6b_reference_fixture()["offline_only"] is True


def test_synthetic_modules_have_no_live_provider_network_or_process_dependency():
    forbidden = {"openai", "httpx", "requests", "socket", "urllib", "subprocess", "os"}
    modules = list((ROOT / "src/ibae").glob("synthetic_*.py"))
    assert len(modules) >= 4
    for module in modules:
        tree = ast.parse(module.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not {item.name.split(".")[0] for item in node.names} & forbidden
            if isinstance(node, ast.ImportFrom) and node.level == 0:
                assert (node.module or "").split(".")[0] not in forbidden


@pytest.mark.parametrize("change", ["live", "version", "extra", "no-controls", "no-recovery", "duplicate", "unknown"])
def test_closed_corpus_rejects_drift_before_replay(change):
    source = synthetic_input_fixture()
    if change == "live":
        source["offline_only"] = False
    elif change == "version":
        source["protocol_version"] = "future"
    elif change == "extra":
        source["endpoint"] = "https://invalid.example"
    elif change == "no-controls":
        source["control_transcripts"] = {}
    elif change == "no-recovery":
        source["recovery_scenarios"] = []
    elif change == "duplicate":
        source["recovery_scenarios"].append(source["recovery_scenarios"][0])
    else:
        source["recovery_scenarios"][0]["scenario_id"] = "unknown"
    with pytest.raises((TypeError, ValueError)):
        replay_synthetic_fixture(source)


def test_corpus_rejects_non_inert_transport_and_aggregate_size():
    with pytest.raises((TypeError, ValueError)):
        replay_synthetic_fixture({"value": object()})
    with pytest.raises(ValueError):
        replay_synthetic_fixture({"payload": ["\0" * 4096] * 128})


def test_replay_cli_rejects_changed_expected_evidence(tmp_path):
    import subprocess
    import sys
    changed = tmp_path / "changed.json"
    changed.write_text("{}\n")
    result = subprocess.run([sys.executable, str(ROOT / "tools/render_v0_6b_fixture.py"),
                             "--inputs-only", "--verify", str(changed)],
                            capture_output=True, text=True, check=False)
    assert result.returncode != 0
    assert "did not match bounded expected evidence" in result.stderr
