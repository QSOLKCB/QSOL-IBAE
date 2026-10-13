"""Offline contracts and ordinary SDK test doubles; no live credential/request."""

from dataclasses import replace
import json
import logging
from types import SimpleNamespace

import pytest

import ibae.openai_transport as transport
from ibae.canonical import canonical_json
from ibae.openai_transport import (
    CredentialReference, MAX_RESPONSE_BYTES, OPENAI_SDK_VERSION, OpenAICredentialBroker,
    OpenAIResponsesSupervisor, OpenAITransportError, OpenAITransportPolicy,
    decode_openai_response, decode_proposal_envelope, encode_proposal_envelope,
    openai_interface_manifest, structured_proposal_format,
)
from ibae.supervisor import FreshContextHandoff, SupervisorProjection
from ibae.synthetic_protocol import NormalizedProposal, ProposalKind
from ibae.transport_activation import (
    ActivationController, ActivationStage, OperatorStageAuthorization, ToolProfile,
)
from test_supervisor import _context


_PLACEHOLDER = "fixture-only-not-a-real-credential"
_ENVIRONMENT = "IBAE_TEST_OPENAI_CREDENTIAL"


def _policy(**changes):
    return OpenAITransportPolicy("gpt-5.4", ("gpt-5.4",), **changes)


def _proposal():
    return NormalizedProposal(ProposalKind.READ, {
        "proposal_key": "read.first", "tool_name": "read", "arguments": {"path": "example.txt"},
        "target_obligation_keys": ["first"],
    })


def _response(proposal=None, **changes):
    result = {"id": "resp_fixture001", "object": "response", "status": "completed", "error": None,
              "incomplete_details": None, "model": "gpt-5.4", "output": [{
                  "type": "message", "status": "completed", "role": "assistant", "content": [{
                      "type": "output_text", "text": encode_proposal_envelope(proposal or _proposal()),
                  }],
              }]}
    result.update(changes)
    return result


def _body(proposal=None, **changes):
    return canonical_json(_response(proposal, **changes)).encode()


def _setup(*, enabled=True, store=False, max_calls=16):
    context, _, _ = _context()
    projection = SupervisorProjection(context)
    record = projection.canonical_record()
    handoff = FreshContextHandoff(projection).canonical_record()
    broker = OpenAICredentialBroker(context.governance_policy, context.task, context.governance,
                                  handle="cred:openai.test", environment_name=_ENVIRONMENT)
    policy = _policy(live_enabled=enabled, store_responses=store, max_calls=max_calls)
    supervisor = OpenAIResponsesSupervisor(policy, broker, broker.reference,
                                          stage=ActivationStage.OPENAI_FAKE_TOOLS, tool_profile=ToolProfile.FAKE)
    activation = ActivationController(record["sources"]["task_id"], record["sources"]["governance_id"],
                                      max_transport_calls=max_calls, transport_policy_id=policy.policy_id,
                                      credential_reference_id=broker.reference.reference_id)
    activation.verify_synthetic_stage()
    activation.authorize(OperatorStageAuthorization(ActivationStage.OPENAI_FAKE_TOOLS,
                         activation.task_id, activation.governance_id, activation.epoch,
                         "test.operator", ToolProfile.FAKE, transport_policy_id=policy.policy_id,
                         credential_reference_id=broker.reference.reference_id))
    return supervisor, activation, record, handoff, broker


def _install_sdk_double(monkeypatch, *, body=None, failure=False, version=OPENAI_SDK_VERSION, chunks=None):
    """Offline-only SDK-shaped response data; never a production adapter input."""
    calls = {"http": [], "clients": [], "requests": [], "closed": 0, "chunks": 0}
    actual_import = transport.importlib.import_module
    monkeypatch.setenv(_ENVIRONMENT, _PLACEHOLDER)
    for name in ("OPENAI_CUSTOM_HEADERS", "OPENAI_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    for name in ("openai", "openai._base_client", "httpx", "httpcore", "httpx2", "httpcore2"):
        monkeypatch.setattr(logging.getLogger(name), "level", logging.WARNING)

    class RawResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            calls["closed"] += 1

        def iter_bytes(self, *, chunk_size):
            assert chunk_size == 4_096
            for chunk in (chunks if chunks is not None else [body if body is not None else _body()]):
                calls["chunks"] += 1
                yield chunk

    class HTTPClient:
        def __init__(self, **kwargs):
            calls["http"].append(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            calls["closed"] += 1

    class Client:
        def __init__(self, **kwargs):
            assert kwargs.pop("api_key") == _PLACEHOLDER
            calls["clients"].append(kwargs)
            self.responses = SimpleNamespace(with_streaming_response=SimpleNamespace(create=self.create))

        def create(self, **kwargs):
            calls["requests"].append(kwargs)
            if failure:
                raise RuntimeError("Provider diagnostics including " + _PLACEHOLDER)
            return RawResponse()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            calls["closed"] += 1

    sdk = SimpleNamespace(__version__=version, OpenAI=Client, DefaultHttpx2Client=HTTPClient, omit=object())
    monkeypatch.setattr(transport.importlib, "import_module",
                        lambda name: sdk if name == "openai" else actual_import(name))
    return calls


def test_strict_envelope_is_detached_and_preserves_exact_normalized_identity():
    proposal = _proposal()
    encoded = encode_proposal_envelope(proposal)
    assert decode_proposal_envelope(encoded).proposal_id == proposal.proposal_id
    decoded, response_id = decode_openai_response(_body(proposal), policy=_policy())
    assert decoded.canonical_record() == proposal.canonical_record()
    assert response_id == "resp_fixture001"
    schema = structured_proposal_format()
    assert schema["strict"] is True
    assert schema["schema"]["additionalProperties"] is False
    assert set(schema["schema"]["properties"]) == set(schema["schema"]["required"])
    schema["schema"]["required"].clear()
    assert structured_proposal_format()["schema"]["required"]
    assert openai_interface_manifest()["live_recovery_verified"] is False


@pytest.mark.parametrize("changes", [
    {"status": "incomplete"}, {"status": "failed"}, {"error": {"message": "failed"}},
    {"incomplete_details": {"reason": "max_output_tokens"}}, {"model": "unapproved-model"},
    {"id": "a-chatgpt-or-codex-thread"}, {"output": []},
    {"output": [{"type": "function_call", "name": "execute"}]},
])
def test_incomplete_error_unknown_model_and_tool_output_fail_closed(changes):
    with pytest.raises(ValueError):
        decode_openai_response(_body(**changes), policy=_policy())


def test_refusal_multiple_messages_and_authority_claim_are_rejected():
    record = _response()
    record["output"][0]["content"] = [{"type": "refusal", "refusal": "No"}]
    with pytest.raises(ValueError, match="refusal"):
        decode_openai_response(canonical_json(record).encode(), policy=_policy())
    record = _response()
    record["output"] *= 2
    with pytest.raises(ValueError, match="exactly one"):
        decode_openai_response(canonical_json(record).encode(), policy=_policy())
    proposal = _proposal().canonical_record()
    proposal["control_authority"] = True
    with pytest.raises(ValueError):
        decode_proposal_envelope(canonical_json({"protocol_version": transport.OPENAI_WIRE_VERSION,
                                                 "proposal_json": canonical_json(proposal)}))


def test_reasoning_is_bounded_discarded_data_not_a_tool_or_proposal():
    record = _response()
    record["output"].insert(0, {"type": "reasoning", "summary": []})
    decoded, _ = decode_openai_response(canonical_json(record).encode(), policy=_policy())
    assert decoded == _proposal()


@pytest.mark.parametrize("text", [
    '{"protocol_version":"x","protocol_version":"y","proposal_json":"{}"}',
    "[" * 25 + "]" * 25, '{"x":NaN}', "\ud800",
])
def test_ambiguous_nonfinite_deep_or_invalid_unicode_json_is_rejected(text):
    with pytest.raises((ValueError, UnicodeError)):
        decode_proposal_envelope(text)


def test_exact_types_and_hard_limits_are_enforced():
    with pytest.raises(TypeError):
        _policy(max_calls=True)
    with pytest.raises(ValueError):
        _policy(max_response_bytes=MAX_RESPONSE_BYTES + 1)
    with pytest.raises(ValueError):
        OpenAITransportPolicy("unapproved", ("gpt-5.4",))
    with pytest.raises(ValueError):
        decode_openai_response(b" " * (MAX_RESPONSE_BYTES + 1), policy=_policy())
    with pytest.raises(TypeError):
        decode_openai_response(bytearray(_body()), policy=_policy())


def test_credential_reference_is_inert_opaque_and_governance_bound():
    _, _, projection, _, broker = _setup(enabled=False)
    reference = broker.reference
    assert reference.canonical_record()["control_authority"] is False
    assert _PLACEHOLDER not in repr(broker) + canonical_json(reference.canonical_record())
    with pytest.raises(ValueError, match="opaque"):
        CredentialReference("sk-not-a-handle", reference.task_id, reference.governance_id, reference.source_binding_id)
    mismatch = replace(reference, handle="cred:openai.other")
    with pytest.raises(OpenAITransportError, match="binding"):
        broker._check(mismatch, projection)


def test_disabled_transport_makes_no_sdk_import_or_credential_lookup(monkeypatch):
    supervisor, activation, projection, handoff, _ = _setup(enabled=False)
    calls = _install_sdk_double(monkeypatch)
    with pytest.raises(OpenAITransportError, match="disabled"):
        supervisor.propose(projection, index=0, activation=activation, fresh_handoff=handoff)
    assert not calls["clients"] and not calls["requests"]


def test_mocked_sdk_request_is_narrow_bounded_and_uses_same_normalized_contract(monkeypatch):
    supervisor, activation, projection, handoff, _ = _setup()
    calls = _install_sdk_double(monkeypatch)
    result = supervisor.propose(projection, index=0, activation=activation, fresh_handoff=handoff)
    assert result == _proposal()
    request, = calls["requests"]
    assert request["tools"] == [] and request["tool_choice"] == "none"
    assert request["stream"] is False and request["background"] is False and request["store"] is False
    assert json.loads(request["input"]) == handoff
    assert _PLACEHOLDER not in canonical_json(request)
    client, = calls["clients"]
    assert client["max_retries"] == 0 and client["base_url"] == "https://api.openai.com/v1"
    assert client["organization"] == client["project"] == client["admin_api_key"] == client["webhook_secret"] == ""
    http, = calls["http"]
    assert http["trust_env"] is False and http["follow_redirects"] is False
    assert http["headers"] == {"Accept-Encoding": "identity"}
    assert calls["closed"] == 3
    assert supervisor.previous_response_id is None
    assert activation.epoch == 1  # A proposal never advances an activation gate.
    observed = supervisor.last_observation.canonical_record()
    assert observed["status"] == "received" and observed["dispatch_attempted"] is True
    assert observed["response_id"] == "resp_fixture001" and observed["proposal_id"] == result.proposal_id
    assert observed["task_id"] == projection["sources"]["task_id"]
    assert observed["governance_id"] == projection["sources"]["governance_id"]
    assert observed["transport_policy_id"] == supervisor.policy_id
    assert observed["credential_reference_id"] == supervisor.deployment_binding[1]
    assert observed["epoch"] == activation.epoch and observed["stage"] == 1 and observed["call_index"] == 0
    assert observed["transport_only"] is True and observed["live_verification"] is False
    assert observed["control_authority"] is False and _PLACEHOLDER not in canonical_json(observed)
    observed["status"] = "changed"
    assert supervisor.last_observation.canonical_record()["status"] == "received"


def test_continuation_requires_owned_successful_stored_response_and_same_epoch(monkeypatch):
    supervisor, activation, projection, handoff, _ = _setup(store=True)
    calls = _install_sdk_double(monkeypatch)
    with pytest.raises(OpenAITransportError, match="unverified"):
        supervisor.propose(projection, index=0, activation=activation, previous_response_id="resp_unknown")
    supervisor.propose(projection, index=0, activation=activation, fresh_handoff=handoff)
    previous = supervisor.previous_response_id
    supervisor.propose(projection, index=1, activation=activation, previous_response_id=previous)
    assert calls["requests"][1]["previous_response_id"] == previous
    assert calls["requests"][1]["instructions"] == calls["requests"][0]["instructions"]
    other = ActivationController(activation.task_id, activation.governance_id, max_transport_calls=4)
    with pytest.raises(OpenAITransportError, match="unverified"):
        supervisor.propose(projection, index=2, activation=other, previous_response_id=previous)


def test_failure_consumes_attempt_clears_continuation_and_does_not_expose_exception(monkeypatch):
    supervisor, activation, projection, handoff, _ = _setup(store=True, max_calls=1)
    calls = _install_sdk_double(monkeypatch, failure=True)
    with pytest.raises(OpenAITransportError, match="transport_failed") as caught:
        supervisor.propose(projection, index=0, activation=activation, fresh_handoff=handoff)
    assert caught.value.__context__ is None
    assert _PLACEHOLDER not in str(caught.value)
    assert supervisor.previous_response_id is None
    observed = supervisor.last_observation.canonical_record()
    assert observed["status"] == "failed" and observed["reason"] == "transport_failed"
    assert observed["dispatch_attempted"] is True
    assert observed["response_id"] is None and observed["proposal_id"] is None
    assert _PLACEHOLDER not in canonical_json(observed)
    with pytest.raises(OpenAITransportError, match="budget"):
        supervisor.propose(projection, index=1, activation=activation, fresh_handoff=handoff)
    assert len(calls["requests"]) == 1


@pytest.mark.parametrize("name", ["OPENAI_BASE_URL", "OPENAI_CUSTOM_HEADERS"])
def test_ambient_routing_or_header_configuration_fails_before_credentials(monkeypatch, name):
    supervisor, activation, projection, handoff, _ = _setup()
    calls = _install_sdk_double(monkeypatch)
    monkeypatch.setenv(name, "offline-rejected-configuration")
    with pytest.raises(OpenAITransportError, match="ambient"):
        supervisor.propose(projection, index=0, activation=activation, fresh_handoff=handoff)
    assert not calls["clients"]


def test_debug_logging_or_sdk_version_drift_fail_closed(monkeypatch):
    supervisor, activation, projection, handoff, _ = _setup()
    calls = _install_sdk_double(monkeypatch, version="0.0.0")
    with pytest.raises(OpenAITransportError, match="version"):
        supervisor.propose(projection, index=0, activation=activation, fresh_handoff=handoff)
    assert not calls["clients"]
    calls = _install_sdk_double(monkeypatch)
    monkeypatch.setattr(logging.getLogger("openai"), "level", logging.DEBUG)
    with pytest.raises(OpenAITransportError, match="logging"):
        supervisor.propose(projection, index=1, activation=activation, fresh_handoff=handoff)
    assert not calls["clients"]


def test_policy_or_credential_binding_cannot_change_inside_authorized_stage(monkeypatch):
    supervisor, activation, projection, handoff, broker = _setup()
    calls = _install_sdk_double(monkeypatch)
    changed_policy = _policy(live_enabled=True, timeout_seconds=30)
    other = OpenAIResponsesSupervisor(changed_policy, broker, broker.reference,
                                     stage=ActivationStage.OPENAI_FAKE_TOOLS, tool_profile=ToolProfile.FAKE)
    with pytest.raises((ValueError, RuntimeError)):
        other.propose(projection, index=0, activation=activation, fresh_handoff=handoff)
    context, _, _ = _context()
    changed_broker = OpenAICredentialBroker(context.governance_policy, context.task, context.governance,
                                          handle="cred:openai.other", environment_name=_ENVIRONMENT)
    other = OpenAIResponsesSupervisor(_policy(live_enabled=True), changed_broker, changed_broker.reference,
                                     stage=ActivationStage.OPENAI_FAKE_TOOLS, tool_profile=ToolProfile.FAKE)
    with pytest.raises((ValueError, RuntimeError)):
        other.propose(projection, index=0, activation=activation, fresh_handoff=handoff)
    assert not calls["clients"] and activation.call_count == 0
    changed_source = OpenAICredentialBroker(context.governance_policy, context.task, context.governance,
                                          handle="cred:openai.test", environment_name="IBAE_OTHER_TEST_CREDENTIAL")
    other = OpenAIResponsesSupervisor(_policy(live_enabled=True), changed_source, changed_source.reference,
                                     stage=ActivationStage.OPENAI_FAKE_TOOLS, tool_profile=ToolProfile.FAKE)
    with pytest.raises((ValueError, RuntimeError)):
        other.propose(projection, index=0, activation=activation, fresh_handoff=handoff)
    assert changed_source.reference.handle == broker.reference.handle
    assert changed_source.reference.reference_id != broker.reference.reference_id
    assert not calls["clients"] and activation.call_count == 0
    assert supervisor.deployment_record() == {
        "transport_policy_id": supervisor.policy_id, "credential_reference_id": broker.reference.reference_id,
    }


def test_missing_credential_has_fixed_error_and_no_sdk_client(monkeypatch):
    supervisor, activation, projection, handoff, _ = _setup()
    calls = _install_sdk_double(monkeypatch)
    monkeypatch.delenv(_ENVIRONMENT)
    with pytest.raises(OpenAITransportError, match="credential_unavailable"):
        supervisor.propose(projection, index=0, activation=activation, fresh_handoff=handoff)
    assert not calls["clients"]
    observed = supervisor.last_observation.canonical_record()
    assert observed["status"] == "unavailable" and observed["reason"] == "credential_unavailable"
    assert observed["dispatch_attempted"] is False and observed["response_id"] is None


def test_oversized_body_stops_bounded_stream_without_parsing(monkeypatch):
    supervisor, activation, projection, handoff, _ = _setup()
    calls = _install_sdk_double(monkeypatch, chunks=[b"x" * MAX_RESPONSE_BYTES, b"x", b"never-read"])
    with pytest.raises(OpenAITransportError, match="byte_limit"):
        supervisor.propose(projection, index=0, activation=activation, fresh_handoff=handoff)
    assert calls["chunks"] == 2


def test_known_credential_echo_cannot_become_model_proposal_or_transport_identity(monkeypatch):
    supervisor, activation, projection, handoff, _ = _setup()
    proposal = NormalizedProposal(ProposalKind.COMPLETE, {"claim": _PLACEHOLDER})
    _install_sdk_double(monkeypatch, body=_body(proposal))
    with pytest.raises(OpenAITransportError, match="credential_echo") as caught:
        supervisor.propose(projection, index=0, activation=activation, fresh_handoff=handoff)
    assert _PLACEHOLDER not in str(caught.value)
    assert supervisor.previous_response_id is None
    observed = supervisor.last_observation.canonical_record()
    assert observed["reason"] == "credential_echo_rejected" and observed["response_id"] is None
    assert _PLACEHOLDER not in canonical_json(observed)


def test_http_header_guard_rejects_error_redirect_encoding_and_large_body_without_reading():
    for status, headers in [(429, {}), (302, {}), (200, {"content-encoding": "gzip"}),
                            (200, {"content-type": "text/plain"}),
                            (200, {"content-type": "application/json", "content-length": "99999999"})]:
        response = SimpleNamespace(status_code=status, headers=headers)
        with pytest.raises(OpenAITransportError):
            transport._guard_http_response(response, MAX_RESPONSE_BYTES)


def test_installed_pinned_sdk_serializes_expected_request_without_network(monkeypatch):
    sdk = pytest.importorskip("openai")
    if sdk.__version__ != OPENAI_SDK_VERSION:
        pytest.skip("optional exact SDK is not installed")
    import httpx2

    supervisor, activation, projection, handoff, _ = _setup()
    monkeypatch.setenv(_ENVIRONMENT, _PLACEHOLDER)
    for name in ("OPENAI_CUSTOM_HEADERS", "OPENAI_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    for name in ("openai", "openai._base_client", "httpx2", "httpcore2", "httpx", "httpcore"):
        monkeypatch.setattr(logging.getLogger(name), "level", logging.WARNING)
    requests = []

    def respond(request):
        assert str(request.url) == "https://api.openai.com/v1/responses"
        assert request.headers["authorization"] == "Bearer " + _PLACEHOLDER
        assert request.headers["accept-encoding"] == "identity"
        assert "OpenAI-Organization" not in request.headers and "OpenAI-Project" not in request.headers
        requests.append(json.loads(request.content))
        return httpx2.Response(200, headers={"content-type": "application/json"}, content=_body())

    original = sdk.DefaultHttpx2Client

    def offline_client(**kwargs):
        return original(transport=httpx2.MockTransport(respond), **kwargs)

    monkeypatch.setattr(sdk, "DefaultHttpx2Client", offline_client)
    result = supervisor.propose(projection, index=0, activation=activation, fresh_handoff=handoff)
    assert result == _proposal()
    assert len(requests) == 1 and requests[0]["model"] == "gpt-5.4"
    assert requests[0]["text"]["format"]["strict"] is True


def test_installed_sdk_error_body_is_rejected_before_eager_error_parsing(monkeypatch):
    sdk = pytest.importorskip("openai")
    if sdk.__version__ != OPENAI_SDK_VERSION:
        pytest.skip("optional exact SDK is not installed")
    import httpx2

    supervisor, activation, projection, handoff, _ = _setup()
    monkeypatch.setenv(_ENVIRONMENT, _PLACEHOLDER)
    for name in ("OPENAI_CUSTOM_HEADERS", "OPENAI_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    for name in ("openai", "openai._base_client", "httpx2", "httpcore2", "httpx", "httpcore"):
        monkeypatch.setattr(logging.getLogger(name), "level", logging.WARNING)
    reads = []

    class ErrorBody(httpx2.SyncByteStream):
        def __iter__(self):
            reads.append("read")
            yield b"error body must not be read"

    def respond(request):
        return httpx2.Response(429, headers={"content-type": "application/json"}, stream=ErrorBody())

    original = sdk.DefaultHttpx2Client
    monkeypatch.setattr(sdk, "DefaultHttpx2Client",
                        lambda **kwargs: original(transport=httpx2.MockTransport(respond), **kwargs))
    with pytest.raises(OpenAITransportError, match="transport_failed"):
        supervisor.propose(projection, index=0, activation=activation, fresh_handoff=handoff)
    assert reads == []
