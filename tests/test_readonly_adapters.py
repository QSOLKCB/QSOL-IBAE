"""Offline read-only shape, selection, observation and bounded transport tests."""

from dataclasses import FrozenInstanceError
import json
from unittest.mock import Mock

import pytest

from ibae.canonical import canonical_fingerprint, canonical_json
from ibae.readonly_adapters import (
    GITHUB_READ_TOOLS, GITHUB_TIMEOUT_MS, MAX_GITHUB_RESPONSE_BYTES,
    ExternalObservationReceipt, FrozenReadAdapter, GitHubReadAdapter, SimulatedGitHubReadAdapter,
    GitHubReadSelection, GitHubRequestPlan, GitHubTransportUnavailable, parse_github_response,
    readonly_interface_manifest, unsupported_session_continuation,
    _read_http_observation, _require_closed_github_transport,
    _require_verified_github_socket, _require_github_response_stream,
)
from ibae.synthetic_protocol import (
    AdapterInterface, AdapterStatus, FakeReadUniverse, NormalizedProposal,
    ProposalKind, SyntheticReadFixture,
)


SHA = "a" * 40
OTHER_SHA = "b" * 40
DEPENDENCY = canonical_fingerprint({"dependency": "selected-head"})


def _selection():
    return GitHubReadSelection("example", "project", "feature/read-only", SHA, 17)


def _proposal(tool="github.repository", arguments=None):
    return NormalizedProposal(ProposalKind.READ, {"proposal_key": "inspect.selected",
        "tool_name": tool, "arguments": _selection().arguments_for(tool) if arguments is None else arguments,
        "target_obligation_keys": ["inspect"]})


def _plan(tool="github.repository"):
    return GitHubRequestPlan.from_proposal(_proposal(tool), _selection(), DEPENDENCY)


def _data(tool):
    return {
        "github.repository": {"full_name": "example/project", "default_branch": "main", "private": False, "archived": False},
        "github.branch": {"name": "feature/read-only", "commit": {"sha": SHA}, "protected": False},
        "github.commit": {"sha": SHA, "commit": {"tree": {"sha": OTHER_SHA}, "message": "Read-only transport\n\nKeep bounded.\n"}},
        "github.pull_request": {"number": 17, "state": "open", "draft": False, "merged": False, "mergeable": None,
            "head": {"sha": SHA}, "base": {"sha": OTHER_SHA, "repo": {"full_name": "example/project"}}},
        "github.check_runs": {"total_count": 1, "check_runs": [{"id": 4, "name": "tests", "head_sha": SHA,
            "status": "completed", "conclusion": "success"}]},
        "github.commit_status": {"sha": SHA, "state": "success", "total_count": 1,
            "statuses": [{"id": 3, "context": "tests", "state": "success"}]},
    }[tool]


def _receipt(tool="github.repository", data=None, metadata=None):
    return parse_github_response(_plan(tool), 200,
        json.dumps(_data(tool) if data is None else data).encode(), metadata)


def test_exact_selection_and_plan_are_round_trippable_detached_records():
    selection, plan = _selection(), _plan()
    assert GitHubReadSelection.from_record(selection.canonical_record()) == selection
    assert GitHubRequestPlan.from_record(plan.canonical_record()) == plan
    record = plan.canonical_record()
    record["headers"]["Accept"] = "text/plain"
    record["proposal"]["payload"]["arguments"]["owner"] = "changed"
    assert plan.canonical_record()["headers"]["Accept"] == "application/vnd.github+json"
    assert plan.canonical_record()["proposal"]["payload"]["arguments"]["owner"] == "example"
    assert selection.selection_id != GitHubReadSelection("example", "other").selection_id
    assert selection.selection_id != GitHubReadSelection("example", "project", "other", SHA, 17).selection_id
    assert selection.selection_id != GitHubReadSelection("example", "project", "feature/read-only", OTHER_SHA, 17).selection_id
    assert selection.selection_id != GitHubReadSelection("example", "project", "feature/read-only", SHA, 18).selection_id
    with pytest.raises(FrozenInstanceError):
        selection._text = "{}"


@pytest.mark.parametrize(("tool", "path"), [
    ("github.repository", "/repos/example/project"),
    ("github.branch", "/repos/example/project/branches/feature%2Fread-only"),
    ("github.commit", "/repos/example/project/commits/" + SHA),
    ("github.pull_request", "/repos/example/project/pulls/17"),
    ("github.check_runs", "/repos/example/project/commits/" + SHA + "/check-runs?filter=latest&per_page=100&page=1"),
    ("github.commit_status", "/repos/example/project/commits/" + SHA + "/status?per_page=100&page=1"),
])
def test_only_closed_single_call_get_routes_exist(tool, path):
    record = _plan(tool).canonical_record()
    assert record["url"] == "https://api.github.com" + path
    assert record["method"] == "GET"
    assert record["max_calls"] == 1
    assert record["max_response_bytes"] == MAX_GITHUB_RESPONSE_BYTES
    assert record["timeout_ms"] == GITHUB_TIMEOUT_MS
    assert record["automatic_retries"] == 0
    assert record["automatic_pagination"] is False
    assert record["follow_redirects"] is False
    assert record["authentication"] == "public_unauthenticated_only"
    assert record["control_authority"] is False
    semantics = record["source_semantics"]
    assert semantics["selection_is_content_snapshot"] is False
    assert semantics["network_operation_cacheable"] is False
    assert semantics["current_remote_state_verified"] is False
    expected = "immutable_commit_content" if tool == "github.commit" else "mutable_remote_state"
    assert semantics["resource_mutability"] == expected
    assert semantics["native_consumption"] == "separately_admitted_content_bound_snapshot_only"


@pytest.mark.parametrize("change", [
    {"owner": "other"}, {"repository": "other"}, {"endpoint": "https://example.test"},
    {"headers": {}}, {"credential": "not-a-credential"}, {"page": 2}, {"method": "POST"},
])
def test_normalized_read_rejects_inexact_extra_or_retargeted_arguments(change):
    arguments = {**_selection().arguments_for("github.repository"), **change}
    with pytest.raises(ValueError):
        GitHubRequestPlan(_proposal(arguments=arguments), _selection(), DEPENDENCY)


@pytest.mark.parametrize("number", [True, 17.0, "17", 18])
def test_exact_argument_comparison_does_not_coalesce_json_types(number):
    args = {**_selection().arguments_for("github.pull_request"), "pull_number": number}
    with pytest.raises(ValueError):
        GitHubRequestPlan(_proposal("github.pull_request", args), _selection(), DEPENDENCY)


@pytest.mark.parametrize(("field", "value"), [
    ("owner", "example/other"), ("repository", ".."), ("repository", "project.git"),
    ("branch", "main?other"), ("branch", "feature//branch"), ("branch", "../main"),
    ("branch", "a" * 257), ("commit_sha", "main"), ("commit_sha", "A" * 40),
    ("pull_number", True), ("pull_number", 0), ("pull_number", 1 << 31),
])
def test_selected_target_profile_is_explicit_and_bounded(field, value):
    record = _selection().canonical_record()
    record[field] = value
    with pytest.raises((TypeError, ValueError)):
        GitHubReadSelection.from_record(record)


def test_unselected_target_and_non_read_proposal_are_unavailable():
    selection = GitHubReadSelection("example", "project")
    for tool in GITHUB_READ_TOOLS[1:]:
        with pytest.raises(ValueError, match="not selected"):
            selection.arguments_for(tool)
    with pytest.raises(ValueError):
        selection.arguments_for("github.merge")
    for kind in (ProposalKind.CONTINUE, ProposalKind.STOP):
        with pytest.raises(ValueError):
            GitHubRequestPlan(NormalizedProposal(kind, {}), _selection(), DEPENDENCY)


@pytest.mark.parametrize(("field", "value"), [
    ("method", "POST"), ("url", "https://example.test/repos/example/project"),
    ("max_calls", True), ("timeout_ms", 10_000.0), ("follow_redirects", True),
    ("automatic_pagination", True), ("authentication", "token"),
    ("headers", {"Accept": "application/vnd.github+json", "Authorization": "not-a-secret"}),
    ("tool_key", "0" * 64), ("control_authority", True),
])
def test_request_record_revalidates_every_canonical_field(field, value):
    record = _plan().canonical_record()
    record[field] = value
    with pytest.raises((TypeError, ValueError)):
        GitHubRequestPlan.from_record(record)


@pytest.mark.parametrize("tool", GITHUB_READ_TOOLS)
def test_supported_response_projections_round_trip_without_native_authority(tool):
    receipt = _receipt(tool)
    record = receipt.canonical_record()
    assert record["control_authority"] is False
    assert record["native_evidence"] is False
    assert record["source_authentication"] == "not_established"
    assert record["status"] == "observed"
    assert record["source_semantics"] == record["request"]["source_semantics"]
    assert record["request"]["tool_key"] == _plan(tool).canonical_record()["tool_key"]
    assert ExternalObservationReceipt.from_record(record) == receipt
    output = receipt.output
    output["unrequested"] = True
    assert "unrequested" not in receipt.output
    assert receipt.receipt_id != receipt.observation_id


def test_source_metadata_is_bounded_and_excluded_from_semantic_observation_identity():
    left = _receipt(metadata={"request_id": "AA:01", "etag": '"abc123"', "has_next_page": False})
    right = _receipt(metadata={"request_id": "BB:02", "etag": 'W/"def456"', "has_next_page": False})
    assert left.observation_id == right.observation_id
    assert left.receipt_id != right.receipt_id
    for metadata in ({"request_id": "a" * 129, "etag": None, "has_next_page": False},
                     {"request_id": None, "etag": "arbitrary text", "has_next_page": False},
                     {"request_id": None, "etag": None, "has_next_page": 0},
                     {"request_id": None, "etag": None, "has_next_page": False, "credential": None}):
        with pytest.raises((TypeError, ValueError)):
            _receipt(metadata=metadata)


@pytest.mark.parametrize("code", [301, 302, 304, 401, 403, 404, 429, 500, 503])
def test_unavailable_http_responses_do_not_return_source_output_or_retry(code):
    receipt = parse_github_response(_plan(), code, b"untrusted error body")
    assert receipt.output is None
    assert receipt.canonical_record()["status"] == "unavailable"
    expected = "redirect_rejected" if code < 400 else "http_unavailable"
    assert receipt.canonical_record()["reason"] == expected


def test_ci_is_exact_commit_bounded_page_data_not_required_check_acceptance():
    output = _receipt("github.check_runs").output
    assert output["complete_page_set"] is True
    assert output["required_checks_verified"] is False
    data = _data("github.check_runs")
    data["total_count"] = 101
    assert _receipt("github.check_runs", data).output["complete_page_set"] is False
    result = _receipt("github.check_runs", metadata={"request_id": None, "etag": None, "has_next_page": True})
    assert result.output["complete_page_set"] is False
    assert _receipt("github.check_runs").observation_id != result.observation_id
    data = _data("github.check_runs")
    data["check_runs"][0]["head_sha"] = OTHER_SHA
    with pytest.raises(ValueError):
        _receipt("github.check_runs", data)


def test_ci_items_are_canonically_ordered_but_coverage_is_never_inferred():
    data = _data("github.check_runs")
    data["check_runs"].append({**data["check_runs"][0], "id": 1, "name": "lint"})
    data["total_count"] = 2
    first = _receipt("github.check_runs", data)
    data["check_runs"].reverse()
    assert _receipt("github.check_runs", data).observation_id == first.observation_id
    assert [item["id"] for item in first.output["items"]] == [1, 4]
    empty = {"check_runs": [], "total_count": 0}
    assert _receipt("github.check_runs", empty).output["required_checks_verified"] is False
    assert _receipt("github.check_runs", empty).output["returned_count"] == 0


@pytest.mark.parametrize(("tool", "change"), [
    ("github.repository", {"full_name": "other/project"}),
    ("github.branch", {"name": "main"}),
    ("github.commit", {"sha": OTHER_SHA}),
    ("github.pull_request", {"number": 18}),
    ("github.commit_status", {"sha": OTHER_SHA}),
    ("github.check_runs", {"total_count": False}),
])
def test_response_target_mismatch_or_wrong_field_type_rejects(tool, change):
    with pytest.raises((TypeError, ValueError)):
        _receipt(tool, {**_data(tool), **change})


def test_moving_branch_or_pull_head_is_an_observation_and_not_selected_commit_proof():
    branch = _data("github.branch")
    branch["commit"]["sha"] = OTHER_SHA
    assert _receipt("github.branch", branch).output["matches_selected_commit"] is False
    pull = _data("github.pull_request")
    pull["head"]["sha"] = OTHER_SHA
    assert _receipt("github.pull_request", pull).output["matches_selected_commit"] is False


@pytest.mark.parametrize("body", [b"[]", b"null", b"{}", b"{", b"\xff", b'{"a":1,"a":2}', b'{"a":NaN}'])
def test_invalid_json_response_is_not_an_observation(body):
    with pytest.raises((TypeError, ValueError)):
        parse_github_response(_plan(), 200, body)


def test_response_and_source_structure_bounds_apply_before_receipt_creation():
    with pytest.raises(ValueError):
        parse_github_response(_plan(), 200, b" " * (MAX_GITHUB_RESPONSE_BYTES + 1))
    with pytest.raises(TypeError):
        parse_github_response(_plan(), True, b"{}")
    with pytest.raises(TypeError):
        parse_github_response(_plan(), 200, "{}")
    data = _data("github.check_runs")
    data["check_runs"] = [{**data["check_runs"][0], "id": index + 1} for index in range(101)]
    data["total_count"] = 101
    with pytest.raises(ValueError):
        _receipt("github.check_runs", data)
    data = _data("github.repository")
    nested = None
    for _ in range(18):
        nested = [nested]
    data["unused"] = nested
    with pytest.raises(ValueError):
        _receipt(data=data)


def test_external_record_schema_cannot_upgrade_or_loosen_observation_claims():
    original = _receipt("github.check_runs").canonical_record()
    for field, value in (("control_authority", True), ("native_evidence", True),
                         ("source_authentication", "verified"), ("status_code", 200.0)):
        with pytest.raises((TypeError, ValueError)):
            ExternalObservationReceipt.from_record({**original, field: value})
    for field, value in (("required_checks_verified", True), ("returned_count", True), ("unrequested", "field")):
        record = json.loads(canonical_json(original))
        record["output"][field] = value
        with pytest.raises((TypeError, ValueError)):
            ExternalObservationReceipt.from_record(record)
    record = json.loads(canonical_json(original))
    record["source_semantics"]["network_operation_cacheable"] = True
    with pytest.raises(ValueError):
        ExternalObservationReceipt.from_record(record)


def test_exact_builtin_contracts_reject_ordinary_subclasses():
    class PlainDict(dict):
        pass

    class PlainBytes(bytes):
        pass

    class PlainSelection(GitHubReadSelection):
        pass

    with pytest.raises(TypeError):
        GitHubReadSelection.from_record(PlainDict(_selection().canonical_record()))
    with pytest.raises(TypeError):
        parse_github_response(_plan(), 200, PlainBytes(b"{}"))
    with pytest.raises(TypeError):
        GitHubRequestPlan(_proposal(), PlainSelection("example", "project"), DEPENDENCY)


def test_frozen_local_reader_matches_accepted_fixture_semantics_exactly():
    fixture = SyntheticReadFixture("local.read", {"path": "frozen.txt", "flag": True}, DEPENDENCY,
        {"text": "frozen local observation"}, interface=AdapterInterface.FILESYSTEM)
    adapter = FrozenReadAdapter((fixture,))
    universe = FakeReadUniverse((fixture,))
    proposal = _proposal("local.read", fixture.arguments)
    left = adapter.read(proposal, DEPENDENCY)
    right = universe.read("local.read", fixture.arguments, DEPENDENCY, interface=AdapterInterface.FILESYSTEM)
    assert left == right
    assert adapter.lookup("local.read", fixture.arguments, DEPENDENCY) == fixture.output
    changed = {"path": "frozen.txt", "flag": 1}
    assert adapter.read(_proposal("local.read", changed), DEPENDENCY).status is AdapterStatus.UNAVAILABLE
    with pytest.raises(LookupError):
        adapter.lookup("local.read", changed, DEPENDENCY)
    with pytest.raises(ValueError):
        FrozenReadAdapter((SyntheticReadFixture("local.read", {}, DEPENDENCY, {}),))


@pytest.mark.parametrize("interface", [AdapterInterface.CHATGPT, AdapterInterface.WORK, AdapterInterface.CODEX])
def test_conversation_products_explicitly_lack_session_continuation(interface):
    status = unsupported_session_continuation(interface)
    assert status["status"] == "unsupported"
    assert status["network_attempted"] is False
    assert status["native_resume_supported"] is False
    assert status["control_authority"] is False
    with pytest.raises(ValueError):
        unsupported_session_continuation(AdapterInterface.GITHUB)


def test_manifest_distinguishes_bounded_backend_from_live_verification():
    manifest = readonly_interface_manifest()
    assert manifest["live_verification"] == "not_established"
    assert manifest["github_authenticated"] == "unavailable_no_credential_broker"
    assert manifest["effects"] == "unsupported_pending_v0.6d"


def _http_response(body=None, *, status=200, headers=None):
    response = Mock()
    response.status = status
    response.read.return_value = json.dumps(_data("github.repository")).encode() if body is None else body
    response.getheader.side_effect = ({} if headers is None else headers).get
    return response


def test_http_reader_uses_a_single_bounded_read_and_closed_metadata():
    response = _http_response(headers={"X-GitHub-Request-Id": "AB:12", "ETag": '"123abc"'})
    result = _read_http_observation(_plan(), response)
    assert result.output == _data("github.repository")
    response.read.assert_called_once_with(MAX_GITHUB_RESPONSE_BYTES + 1)
    assert result.canonical_record()["source_metadata"] == {
        "request_id": "AB:12", "etag": '"123abc"', "has_next_page": False}
    assert result.canonical_record()["native_evidence"] is False


@pytest.mark.parametrize("headers", [
    {"Content-Length": str(MAX_GITHUB_RESPONSE_BYTES + 1)},
    {"Content-Length": "9" * 11}, {"Content-Length": "-1"},
    {"Content-Length": "1.0"}, {"Content-Encoding": "gzip"},
])
def test_http_reader_rejects_unbounded_or_compressed_body_before_reading(headers):
    response = _http_response(headers=headers)
    with pytest.raises(ValueError):
        _read_http_observation(_plan(), response)
    response.read.assert_not_called()


def test_http_reader_rejects_actual_body_overrun_and_excessive_metadata():
    with pytest.raises(ValueError):
        _read_http_observation(_plan(), _http_response(b"x" * (MAX_GITHUB_RESPONSE_BYTES + 1)))
    with pytest.raises(ValueError):
        _read_http_observation(_plan(), _http_response(headers={"Link": "x" * 4_097}))
    response = _http_response(status=302, headers={"Location": "https://example.test/other"})
    assert _read_http_observation(_plan(), response).canonical_record()["reason"] == "redirect_rejected"
    assert all(call.args != ("Location",) for call in response.getheader.call_args_list)


def test_http_reader_rejects_incomplete_content_length_even_for_valid_json():
    body = json.dumps(_data("github.repository")).encode()
    with pytest.raises(ValueError, match="content length"):
        _read_http_observation(_plan(), _http_response(body, headers={"Content-Length": str(len(body) + 1)}))
    result = _read_http_observation(_plan(), _http_response(body, headers={"Content-Length": str(len(body))}))
    assert result.output == _data("github.repository")


@pytest.mark.parametrize("live_stage_one", [False, True])
def test_full_public_adapter_denies_before_network_without_stage_three(monkeypatch, live_stage_one):
    from ibae.transport_activation import (
        ActivationController, ActivationError, ActivationStage, OperatorStageAuthorization, ToolProfile,
    )

    task_id = canonical_fingerprint({"task": "test"})
    governance_id = canonical_fingerprint({"governance": "test"})
    activation = ActivationController(task_id, governance_id,
        transport_policy_id="3" * 64, credential_reference_id="4" * 64)
    if live_stage_one:
        activation.verify_synthetic_stage()
        activation.authorize(OperatorStageAuthorization(ActivationStage.OPENAI_FAKE_TOOLS,
            task_id, governance_id, activation.epoch, "operator.test", ToolProfile.FAKE,
            transport_policy_id="3" * 64, credential_reference_id="4" * 64))
    connection = Mock(side_effect=AssertionError("offline test must not connect"))
    monkeypatch.setattr("ibae.readonly_adapters.http.client.HTTPSConnection", connection)
    adapter = GitHubReadAdapter(_selection(), activation, task_id=task_id, governance_id=governance_id)
    with pytest.raises(ActivationError, match="stage 3"):
        adapter.observe(_proposal(), DEPENDENCY)
    connection.assert_not_called()
    assert activation.call_count == 0
    assert activation.canonical_record()["outstanding_call"] is False


def test_public_adapter_has_no_arbitrary_endpoint_credential_or_controller_parameter():
    from ibae.transport_activation import ActivationController

    task_id, governance_id = "1" * 64, "2" * 64
    activation = ActivationController(task_id, governance_id)
    with pytest.raises(TypeError):
        GitHubReadAdapter(_selection(), object(), task_id=task_id, governance_id=governance_id)
    for key in ("endpoint", "credential", "headers", "proxy", "transport", "timeout"):
        with pytest.raises(TypeError):
            GitHubReadAdapter(_selection(), activation, task_id=task_id,
                governance_id=governance_id, **{key: "unsupported"})
    adapter = GitHubReadAdapter(_selection(), activation, task_id=task_id, governance_id=governance_id)
    adapter.validate_activation(activation)
    assert adapter.binding_record()["selection_id"] == _selection().selection_id
    with pytest.raises(ValueError):
        adapter.validate_activation(ActivationController(task_id, governance_id))


def test_revoked_adapter_rejects_before_network_and_does_not_spend_capacity(monkeypatch):
    from ibae.transport_activation import ActivationController, ActivationError

    task_id, governance_id = "1" * 64, "2" * 64
    activation = ActivationController(task_id, governance_id)
    adapter = GitHubReadAdapter(_selection(), activation, task_id=task_id, governance_id=governance_id)
    activation.revoke()
    connection = Mock(side_effect=AssertionError("offline test must not connect"))
    monkeypatch.setattr("ibae.readonly_adapters.http.client.HTTPSConnection", connection)
    with pytest.raises(ActivationError, match="revoked"):
        adapter.observe(_proposal(), DEPENDENCY)
    connection.assert_not_called()
    assert activation.call_count == 0


def test_mock_https_factory_cannot_qualify_live_transport_or_fall_back_to_real_network(monkeypatch):
    replacement = Mock(side_effect=AssertionError("a replacement must not be called"))
    monkeypatch.setattr("ibae.readonly_adapters.http.client.HTTPSConnection", replacement)
    with pytest.raises(GitHubTransportUnavailable, match="closed GitHub HTTPS"):
        _require_closed_github_transport()
    replacement.assert_not_called()


def test_mock_response_method_cannot_qualify_the_closed_network_path(monkeypatch):
    replacement = Mock(side_effect=AssertionError("a replacement must not be called"))
    monkeypatch.setattr("ibae.readonly_adapters.http.client.HTTPResponse.read", replacement)
    with pytest.raises(GitHubTransportUnavailable, match="closed GitHub HTTPS"):
        _require_closed_github_transport()
    replacement.assert_not_called()


def test_mock_socket_factory_is_rejected_without_using_a_saved_original(monkeypatch):
    replacement = Mock(side_effect=AssertionError("offline test must not connect"))
    monkeypatch.setattr("ibae.readonly_adapters.socket.create_connection", replacement)
    with pytest.raises(GitHubTransportUnavailable):
        _require_closed_github_transport()
    replacement.assert_not_called()


def test_ordinary_frozen_http_objects_have_no_verified_tls_provenance():
    with pytest.raises(GitHubTransportUnavailable):
        _require_verified_github_socket(Mock(), Mock())
    with pytest.raises(GitHubTransportUnavailable):
        _require_github_response_stream(_http_response(), Mock())
    # The exact same frozen payload remains useful as unverified parser data.
    receipt = _read_http_observation(_plan(), _http_response())
    assert receipt.canonical_record()["source_authentication"] == "not_established"


def test_unconnected_real_https_object_does_not_establish_network_provenance():
    import http.client
    import ssl

    context = ssl.create_default_context()
    connection = http.client.HTTPSConnection("api.github.com", port=443, context=context)
    try:
        assert connection.sock is None
        with pytest.raises(GitHubTransportUnavailable, match="TLS socket"):
            _require_verified_github_socket(connection, context)
        assert connection.sock is None
    finally:
        connection.close()


def test_parsed_or_reconstructed_receipt_cannot_supply_a_live_outcome():
    from ibae.transport_activation import ActivationController

    task_id, governance_id = "1" * 64, "2" * 64
    controller = ActivationController(task_id, governance_id)
    adapter = GitHubReadAdapter(_selection(), controller, task_id=task_id, governance_id=governance_id)
    parsed = _receipt()
    restored = ExternalObservationReceipt.from_record(parsed.canonical_record())
    assert adapter._consume_live_outcome(controller, parsed) is None
    assert adapter._consume_live_outcome(controller, restored) is None
    assert controller.call_count == 0


def test_simulated_github_adapter_has_permanent_cross_mode_type_separation():
    from ibae.transport_activation import ActivationController, SimulationActivationController

    task_id, governance_id = "1" * 64, "2" * 64
    live = ActivationController(task_id, governance_id)
    simulated = SimulationActivationController(task_id, governance_id)
    with pytest.raises(TypeError):
        GitHubReadAdapter(_selection(), simulated, task_id=task_id, governance_id=governance_id)
    with pytest.raises(TypeError):
        SimulatedGitHubReadAdapter(_selection(), live, task_id=task_id, governance_id=governance_id)
    adapter = SimulatedGitHubReadAdapter(_selection(), simulated, task_id=task_id,
        governance_id=governance_id, body=json.dumps(_data("github.repository")).encode())
    assert adapter.binding_record()["simulation_only"] is True
    assert adapter.binding_record()["live_verification"] is False
    assert adapter.call_count == 0
    assert not hasattr(adapter, "_live_outcome")
    assert not hasattr(adapter, "_consume_live_outcome")
    with pytest.raises(TypeError):
        GitHubReadAdapter.validate_activation(adapter, simulated)


@pytest.mark.parametrize("kwargs", [
    {"body": "not bytes"}, {"body": b"x" * (MAX_GITHUB_RESPONSE_BYTES + 1)},
    {"status_code": True}, {"status_code": 600}, {"failure_reason": "arbitrary_failure"},
    {"failure_reason": 1}, {"endpoint": "https://example.test"}, {"transport": None},
])
def test_simulated_response_configuration_is_closed_and_bounded(kwargs):
    from ibae.transport_activation import SimulationActivationController

    task_id, governance_id = "1" * 64, "2" * 64
    controller = SimulationActivationController(task_id, governance_id)
    with pytest.raises((TypeError, ValueError)):
        SimulatedGitHubReadAdapter(_selection(), controller, task_id=task_id,
            governance_id=governance_id, **kwargs)


def test_simulator_unadmitted_reads_preserve_budget_with_network_tripwires(monkeypatch):
    from ibae.transport_activation import ActivationError, SimulationActivationController

    task_id, governance_id = "1" * 64, "2" * 64
    controller = SimulationActivationController(task_id, governance_id)
    adapter = SimulatedGitHubReadAdapter(_selection(), controller, task_id=task_id,
        governance_id=governance_id, body=json.dumps(_data("github.repository")).encode())
    forbidden = Mock(side_effect=AssertionError("simulation must not dispatch a network operation"))
    monkeypatch.setattr("ibae.readonly_adapters.socket.socket", forbidden)
    monkeypatch.setattr("ibae.readonly_adapters.socket.create_connection", forbidden)
    monkeypatch.setattr("ibae.readonly_adapters.socket.getaddrinfo", forbidden)
    monkeypatch.setattr("ibae.readonly_adapters.http.client.HTTPSConnection", forbidden)
    with pytest.raises(ActivationError, match="stage 3"):
        adapter.observe(_proposal(), DEPENDENCY)
    assert controller.call_count == adapter.call_count == 0
    forbidden.assert_not_called()
