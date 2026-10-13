"""Offline v0.6B normalized proposals and closed, frozen data adapters.

These are data contracts, never authority tokens. The intended future OpenAI
transport must enter ``NormalizedProposal`` too; no live transport is present.
All reads select an exact preconfigured fixture. No endpoint, SDK, credential
resolver, callable backend, worker execution, or effect implementation exists.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final

from ._records import bounded_utf8_length, require_fingerprint, require_symbol
from .canonical import canonical_json, canonical_tool_key, domain_fingerprint
from .supervisor import SupervisorProjection

NORMALIZED_PROPOSAL_VERSION: Final = "IBAE-NORMALIZED-SUPERVISOR-PROPOSAL-V1"
SYNTHETIC_FIXTURE_VERSION: Final = "IBAE-SYNTHETIC-READ-FIXTURE-V1"
SYNTHETIC_UNIVERSE_VERSION: Final = "IBAE-SYNTHETIC-READ-UNIVERSE-V1"
SYNTHETIC_RESULT_VERSION: Final = "IBAE-SYNTHETIC-ADAPTER-RESULT-V1"
SYNTHETIC_SUPERVISOR_VERSION: Final = "IBAE-SYNTHETIC-SUPERVISOR-V1"
MAX_PROPOSAL_BYTES: Final = 65_536
MAX_FIXTURE_BYTES: Final = 65_536
MAX_STREAM_BYTES: Final = 1_048_576
MAX_PROPOSALS: Final = 128
MAX_READ_FIXTURES: Final = 128
MAX_TEXT_BYTES: Final = 4_096
MAX_BATCH_ACTIONS: Final = 64
MAX_JSON_NODES: Final = 4_096
MAX_JSON_DEPTH: Final = 16


def _exact(label: str, value: Any, kind: type) -> None:
    if type(value) is not kind:
        raise TypeError(f"{label} must have exact type {kind.__name__}")


def _copy_json(value: Any, *, limit: int = MAX_PROPOSAL_BYTES,
               node_limit: int = MAX_JSON_NODES) -> Any:
    """Reject non-inert values before canonicalization, with bounded traversal."""
    nodes, size = 0, 0

    def charge(amount: int) -> None:
        nonlocal size
        size += amount
        if size > limit:
            raise ValueError("synthetic record exceeds serialized byte bound")

    def copy(item: Any, depth: int) -> Any:
        nonlocal nodes
        nodes += 1
        if nodes > node_limit or depth > MAX_JSON_DEPTH:
            raise ValueError("synthetic record exceeds structural bounds")
        kind = type(item)
        if kind is str:
            bounded_utf8_length("synthetic text", item, limit=MAX_TEXT_BYTES)
            charge(2)
            for character in item:
                point = ord(character)
                if character in {'"', "\\", "\b", "\f", "\n", "\r", "\t"}:
                    charge(2)
                elif point <= 0x1F:
                    charge(6)
                else:
                    charge(1 if point <= 0x7F else 2 if point <= 0x7FF else 3 if point <= 0xFFFF else 4)
            return item
        if item is None or kind is bool:
            charge(4 if item is None or item is True else 5)
            return item
        if kind is int:
            if item.bit_length() > 256:
                raise ValueError("synthetic integer exceeds 256 bits")
            charge(len(str(item)))
            return item
        if kind is float:
            if not math.isfinite(item):
                raise ValueError("synthetic numbers must be finite")
            charge(len(str(item)))
            return item
        if kind is list:
            if len(item) > 128:
                raise ValueError("synthetic array exceeds bound")
            charge(2 + max(0, len(item) - 1))
            return [copy(child, depth + 1) for child in item]
        if kind is dict:
            if len(item) > 128:
                raise ValueError("synthetic object exceeds bound")
            charge(2 + len(item) + max(0, len(item) - 1))
            result = {}
            for key, child in item.items():
                _exact("synthetic object key", key, str)
                result[copy(key, depth + 1)] = copy(child, depth + 1)
            return result
        raise TypeError("synthetic records require inert exact JSON types")

    result = copy(value, 0)
    # The incremental counter is conservative for strings and exact containers;
    # the final check also covers JSON's finite-float spelling.
    bounded_utf8_length("synthetic record", canonical_json(result), limit=limit)
    return result


def bounded_synthetic_data(value: Any, *, max_bytes: int = 262_144) -> Any:
    """Copy an inert fixture envelope under the shared hard transport ceiling.

    This is structural validation only, not evidence admission or authority.
    Per-message constructors impose their own narrower schema and byte caps.
    """
    _exact("synthetic byte limit", max_bytes, int)
    if not 1 <= max_bytes <= MAX_STREAM_BYTES:
        raise ValueError("synthetic byte limit exceeds the hard transport ceiling")
    return _copy_json(value, limit=max_bytes, node_limit=65_536)


def _fields(value: Any, fields: set[str], label: str) -> dict:
    _exact(label, value, dict)
    if len(value) != len(fields) or any(type(key) is not str for key in value) or set(value) != fields:
        raise ValueError(f"{label} does not match the versioned schema")
    return value


def _symbol(label: str, value: Any) -> str:
    _exact(label, value, str)
    return require_symbol(label, value)


def _fingerprint(label: str, value: Any) -> str:
    _exact(label, value, str)
    return require_fingerprint(label, value)


def _text(label: str, value: Any) -> None:
    _exact(label, value, str)
    bounded_utf8_length(label, value, limit=MAX_TEXT_BYTES)


def _ordered_strings(label: str, value: Any, *, fingerprints: bool = False,
                     nonempty: bool = False, ordered: bool = True) -> None:
    _exact(label, value, list)
    if len(value) > 128 or (nonempty and not value):
        raise ValueError(f"{label} has invalid length")
    for item in value:
        (_fingerprint if fingerprints else _symbol)(label, item)
    if len(set(value)) != len(value) or (ordered and value != sorted(value)):
        raise ValueError(f"{label} must be unique and canonically ordered")


class ProposalKind(str, Enum):
    READ = "read"
    READ_BATCH = "read_batch"
    CONTINUE = "continue"
    STRATEGY = "strategy"
    STRATEGY_CHANGE = "strategy_change"
    OBSERVE = "observe"
    INSPECT_RECOVERY = "inspect_recovery"
    COMPLETE = "complete"
    PROGRESS_CLAIM = "progress_claim"
    EFFECT_ATTEMPT = "effect_attempt"
    STOP = "stop"


def _strategy(value: Any) -> None:
    _fields(value, {"key", "schema_id", "parameters"}, "strategy descriptor")
    _symbol("strategy key", value["key"])
    _fingerprint("strategy schema id", value["schema_id"])
    _exact("strategy parameters", value["parameters"], dict)
    if len(value["parameters"]) > 32:
        raise ValueError("too many strategy parameters")
    for key, parameter in value["parameters"].items():
        _symbol("strategy parameter key", key)
        if type(parameter) is list:
            if len(parameter) > 64:
                raise ValueError("strategy symbol list exceeds 64 items")
            for symbol in parameter:
                _symbol("strategy parameter symbol", symbol)
        elif type(parameter) is str:
            _symbol("strategy parameter symbol", parameter)
        elif type(parameter) not in (bool, int):
            raise TypeError("strategy parameters require boolean, integer, symbol or symbol-list values")


def _validate_payload(kind: ProposalKind, payload: dict) -> None:
    if kind in {ProposalKind.CONTINUE, ProposalKind.OBSERVE, ProposalKind.INSPECT_RECOVERY, ProposalKind.STOP}:
        _fields(payload, set(), "empty proposal payload")
    elif kind is ProposalKind.READ:
        _fields(payload, {"proposal_key", "tool_name", "arguments", "target_obligation_keys"}, "read proposal")
        _symbol("proposal key", payload["proposal_key"])
        _symbol("tool name", payload["tool_name"])
        _exact("read arguments", payload["arguments"], dict)
        _ordered_strings("target obligation keys", payload["target_obligation_keys"], nonempty=True)
    elif kind is ProposalKind.READ_BATCH:
        _fields(payload, {"batch_key", "strategy", "proposals"}, "read batch proposal")
        _symbol("batch key", payload["batch_key"])
        _strategy(payload["strategy"])
        _exact("batch proposals", payload["proposals"], list)
        if not 1 <= len(payload["proposals"]) <= MAX_BATCH_ACTIONS:
            raise ValueError("read batch requires 1 to 64 proposals")
        keys = []
        for action in payload["proposals"]:
            _fields(action, {"proposal_key", "capability", "arguments", "target_obligation_ids", "required_state_keys"}, "batch action")
            keys.append(_symbol("proposal key", action["proposal_key"]))
            _symbol("capability", action["capability"])
            _exact("action arguments", action["arguments"], dict)
            _ordered_strings("target obligations", action["target_obligation_ids"], fingerprints=True, nonempty=True)
            _ordered_strings("required state keys", action["required_state_keys"])
        if len(set(keys)) != len(keys):
            raise ValueError("batch proposal keys must be unique")
    elif kind in {ProposalKind.COMPLETE, ProposalKind.PROGRESS_CLAIM}:
        _fields(payload, {"claim"}, "model claim")
        _text("model claim", payload["claim"])
    elif kind is ProposalKind.STRATEGY:
        _fields(payload, {"mode", "description"}, "strategy proposal")
        _exact("strategy mode", payload["mode"], str)
        if payload["mode"] not in {"primary", "alternate"}:
            raise ValueError("unsupported synthetic strategy mode")
        _text("strategy description", payload["description"])
    elif kind is ProposalKind.STRATEGY_CHANGE:
        _fields(payload, {"strategy", "capability_names", "target_obligation_ids", "dependency_path", "recovery_mode", "initial_transition_pattern"}, "strategy change proposal")
        _strategy(payload["strategy"])
        _ordered_strings("capability names", payload["capability_names"])
        _ordered_strings("target obligations", payload["target_obligation_ids"], fingerprints=True, nonempty=True)
        _ordered_strings("dependency path", payload["dependency_path"], ordered=False)
        _symbol("recovery mode", payload["recovery_mode"])
        _exact("initial transition pattern", payload["initial_transition_pattern"], list)
        if len(payload["initial_transition_pattern"]) > 6:
            raise ValueError("transition pattern exceeds six entries")
        for identity in payload["initial_transition_pattern"]:
            _fingerprint("transition identity", identity)
    elif kind is ProposalKind.EFFECT_ATTEMPT:
        _fields(payload, {"capability", "arguments"}, "effect proposal")
        _symbol("effect capability", payload["capability"])
        _exact("effect arguments", payload["arguments"], dict)
    else:
        raise ValueError("unsupported normalized proposal kind")


def _proposal_record(record: Any) -> dict:
    value = _copy_json(record)
    _fields(value, {"protocol_version", "provider", "kind", "payload", "epistemic_class", "control_authority"}, "normalized proposal")
    if (value["protocol_version"] != NORMALIZED_PROPOSAL_VERSION or value["provider"] != "openai"
            or value["epistemic_class"] != "model_proposed" or value["control_authority"] is not False):
        raise ValueError("invalid proposal version, OpenAI provider or authority declaration")
    _exact("proposal kind", value["kind"], str)
    _validate_payload(ProposalKind(value["kind"]), value["payload"])
    return value


@dataclass(frozen=True, slots=True, init=False)
class NormalizedProposal:
    """A versioned proposal only; parsing never admits an action or a claim."""

    _text: str

    def __init__(self, kind: ProposalKind, payload: dict, *, provider: str = "openai") -> None:
        _exact("proposal kind", kind, ProposalKind)
        _exact("provider", provider, str)
        record = _proposal_record({"protocol_version": NORMALIZED_PROPOSAL_VERSION,
            "provider": provider, "kind": kind.value, "payload": payload,
            "epistemic_class": "model_proposed", "control_authority": False})
        object.__setattr__(self, "_text", canonical_json(record))

    @classmethod
    def from_record(cls, record: dict) -> NormalizedProposal:
        value = _proposal_record(record)
        return cls(ProposalKind(value["kind"]), value["payload"], provider=value["provider"])

    def canonical_record(self) -> dict:
        _exact("proposal text", self._text, str)
        bounded_utf8_length("proposal", self._text, limit=MAX_PROPOSAL_BYTES)
        return _proposal_record(json.loads(self._text))

    @property
    def kind(self) -> ProposalKind:
        return ProposalKind(self.canonical_record()["kind"])

    @property
    def payload(self) -> dict:
        return self.canonical_record()["payload"]

    @property
    def proposal_id(self) -> str:
        return domain_fingerprint("ibae.normalized-supervisor-proposal-id.v1", self.canonical_record())


class AdapterInterface(str, Enum):
    CHATGPT = "chatgpt"
    WORK = "work"
    CODEX = "codex"
    GITHUB = "github"
    FILESYSTEM = "filesystem"
    WEB = "web"
    READ = "read"
    WORKER = "worker"
    EFFECT = "effect"


class AdapterStatus(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"


_READ_INTERFACES = frozenset({AdapterInterface.GITHUB, AdapterInterface.FILESYSTEM,
                            AdapterInterface.WEB, AdapterInterface.READ, AdapterInterface.WORKER})


def synthetic_interface_manifest() -> dict:
    """Closed status declarations describe only this offline implementation."""
    return {"protocol_version": "IBAE-SYNTHETIC-INTERFACES-V1", "provider": "openai",
        "transport": "fixture_only", "network_enabled": False, "control_authority": False,
        "interfaces": [{"interface": interface.value,
            "synthetic_status": (AdapterStatus.AVAILABLE.value if interface in _READ_INTERFACES
                                 else AdapterStatus.UNSUPPORTED.value if interface is AdapterInterface.EFFECT
                                 else AdapterStatus.UNAVAILABLE.value),
            "live_status": AdapterStatus.UNSUPPORTED.value if interface is AdapterInterface.EFFECT else AdapterStatus.UNAVAILABLE.value,
            "implementation": "frozen_data_only" if interface in _READ_INTERFACES else "proposed_interface_only"}
            for interface in AdapterInterface]}


def _fixture_record(record: Any) -> dict:
    value = _copy_json(record, limit=MAX_FIXTURE_BYTES)
    _fields(value, {"protocol_version", "interface", "tool_name", "arguments", "dependency_fingerprint", "output", "control_authority"}, "read fixture")
    if value["protocol_version"] != SYNTHETIC_FIXTURE_VERSION or value["control_authority"] is not False:
        raise ValueError("invalid synthetic fixture version or authority")
    _exact("fixture interface", value["interface"], str)
    if AdapterInterface(value["interface"]) not in _READ_INTERFACES:
        raise ValueError("interface has no synthetic read implementation")
    _symbol("fixture tool name", value["tool_name"])
    _exact("fixture arguments", value["arguments"], dict)
    _fingerprint("fixture dependency", value["dependency_fingerprint"])
    return value


@dataclass(frozen=True, slots=True, init=False)
class SyntheticReadFixture:
    _text: str

    def __init__(self, tool_name: str, arguments: dict, dependency_fingerprint: str,
                 output: Any, *, interface: AdapterInterface = AdapterInterface.READ) -> None:
        _exact("fixture interface", interface, AdapterInterface)
        record = _fixture_record({"protocol_version": SYNTHETIC_FIXTURE_VERSION,
            "interface": interface.value, "tool_name": tool_name, "arguments": arguments,
            "dependency_fingerprint": dependency_fingerprint, "output": output, "control_authority": False})
        object.__setattr__(self, "_text", canonical_json(record))

    @classmethod
    def from_record(cls, record: dict) -> SyntheticReadFixture:
        value = _fixture_record(record)
        return cls(value["tool_name"], value["arguments"], value["dependency_fingerprint"],
                   value["output"], interface=AdapterInterface(value["interface"]))

    def canonical_record(self) -> dict:
        _exact("fixture text", self._text, str)
        bounded_utf8_length("fixture", self._text, limit=MAX_FIXTURE_BYTES)
        return _fixture_record(json.loads(self._text))

    @property
    def tool_name(self) -> str:
        return self.canonical_record()["tool_name"]

    @property
    def arguments(self) -> dict:
        return self.canonical_record()["arguments"]

    @property
    def dependency_fingerprint(self) -> str:
        return self.canonical_record()["dependency_fingerprint"]

    @property
    def output(self) -> Any:
        return self.canonical_record()["output"]

    @property
    def interface(self) -> AdapterInterface:
        return AdapterInterface(self.canonical_record()["interface"])

    @property
    def tool_key(self) -> str:
        value = self.canonical_record()
        return canonical_tool_key(value["tool_name"], value["arguments"], value["dependency_fingerprint"])

    @property
    def fixture_id(self) -> str:
        return domain_fingerprint("ibae.synthetic-read-fixture-id.v1", self.canonical_record())


def _result_record(record: Any) -> dict:
    value = _copy_json(record, limit=MAX_FIXTURE_BYTES)
    _fields(value, {"protocol_version", "interface", "status", "tool_key", "output", "reason", "control_authority"}, "adapter result")
    if value["protocol_version"] != SYNTHETIC_RESULT_VERSION or value["control_authority"] is not False:
        raise ValueError("invalid result version or authority")
    _exact("result interface", value["interface"], str)
    _exact("result status", value["status"], str)
    interface, status = AdapterInterface(value["interface"]), AdapterStatus(value["status"])
    _fingerprint("result tool key", value["tool_key"])
    expected_reason = {AdapterStatus.AVAILABLE: "exact_frozen_fixture", AdapterStatus.UNAVAILABLE: "no_exact_frozen_fixture",
                       AdapterStatus.UNSUPPORTED: "effects_unsupported_pending_v0.6d"}[status]
    if type(value["reason"]) is not str or value["reason"] != expected_reason:
        raise ValueError("result reason does not match status")
    if status is not AdapterStatus.AVAILABLE and value["output"] is not None:
        raise ValueError("unavailable or unsupported results cannot carry output")
    if ((status is AdapterStatus.AVAILABLE and interface not in _READ_INTERFACES)
            or (status is AdapterStatus.UNSUPPORTED and interface is not AdapterInterface.EFFECT)
            or (interface is AdapterInterface.EFFECT and status is not AdapterStatus.UNSUPPORTED)):
        raise ValueError("result status does not match supported interface")
    return value


@dataclass(frozen=True, slots=True, init=False)
class AdapterResult:
    _text: str

    def __init__(self, interface: AdapterInterface, status: AdapterStatus, tool_key: str, output: Any = None) -> None:
        _exact("result interface", interface, AdapterInterface)
        _exact("result status", status, AdapterStatus)
        reason = {AdapterStatus.AVAILABLE: "exact_frozen_fixture", AdapterStatus.UNAVAILABLE: "no_exact_frozen_fixture",
                  AdapterStatus.UNSUPPORTED: "effects_unsupported_pending_v0.6d"}[status]
        record = _result_record({"protocol_version": SYNTHETIC_RESULT_VERSION,
            "interface": interface.value, "status": status.value, "tool_key": tool_key,
            "output": output, "reason": reason, "control_authority": False})
        object.__setattr__(self, "_text", canonical_json(record))

    @classmethod
    def from_record(cls, record: dict) -> AdapterResult:
        value = _result_record(record)
        return cls(AdapterInterface(value["interface"]), AdapterStatus(value["status"]), value["tool_key"], value["output"])

    def canonical_record(self) -> dict:
        _exact("result text", self._text, str)
        bounded_utf8_length("result", self._text, limit=MAX_FIXTURE_BYTES)
        return _result_record(json.loads(self._text))

    @property
    def status(self) -> AdapterStatus:
        return AdapterStatus(self.canonical_record()["status"])

    @property
    def output(self) -> Any:
        return self.canonical_record()["output"]

    @property
    def result_id(self) -> str:
        return domain_fingerprint("ibae.synthetic-adapter-result-id.v1", self.canonical_record())


@dataclass(frozen=True, slots=True, init=False)
class FakeReadUniverse:
    """A bounded, closed universe; no arbitrary operations or fallback reads."""

    _fixtures: tuple[SyntheticReadFixture, ...]

    def __init__(self, fixtures: tuple[SyntheticReadFixture, ...]) -> None:
        _exact("read fixtures", fixtures, tuple)
        if len(fixtures) > MAX_READ_FIXTURES:
            raise ValueError("too many read fixtures")
        frozen = []
        for fixture in fixtures:
            _exact("read fixture", fixture, SyntheticReadFixture)
            frozen.append(SyntheticReadFixture.from_record(fixture.canonical_record()))
        frozen.sort(key=lambda fixture: (fixture.interface.value, fixture.tool_key))
        keys = [(fixture.interface, fixture.tool_key) for fixture in frozen]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate synthetic read key")
        object.__setattr__(self, "_fixtures", tuple(frozen))
        self.canonical_record()

    @classmethod
    def from_record(cls, record: dict) -> FakeReadUniverse:
        value = _copy_json(record, limit=MAX_STREAM_BYTES, node_limit=65_536)
        _fields(value, {"protocol_version", "fixtures", "control_authority", "network_enabled"}, "read universe")
        if (value["protocol_version"] != SYNTHETIC_UNIVERSE_VERSION or value["control_authority"] is not False
                or value["network_enabled"] is not False):
            raise ValueError("invalid synthetic universe version or authority")
        _exact("fixture array", value["fixtures"], list)
        result = cls(tuple(SyntheticReadFixture.from_record(item) for item in value["fixtures"]))
        if result.canonical_record() != value:
            raise ValueError("fixtures must be canonically ordered")
        return result

    def canonical_record(self) -> dict:
        _exact("read fixtures", self._fixtures, tuple)
        if len(self._fixtures) > MAX_READ_FIXTURES:
            raise ValueError("too many read fixtures")
        records, keys = [], []
        for fixture in self._fixtures:
            _exact("read fixture", fixture, SyntheticReadFixture)
            records.append(fixture.canonical_record())
            keys.append((fixture.interface.value, fixture.tool_key))
        if keys != sorted(set(keys)):
            raise ValueError("fixtures must have unique canonically ordered keys")
        return _copy_json({"protocol_version": SYNTHETIC_UNIVERSE_VERSION, "fixtures": records,
            "control_authority": False, "network_enabled": False}, limit=MAX_STREAM_BYTES, node_limit=65_536)

    @property
    def universe_id(self) -> str:
        return domain_fingerprint("ibae.synthetic-read-universe-id.v1", self.canonical_record())

    def read(self, tool_name: str, arguments: dict, dependency_fingerprint: str,
             *, interface: AdapterInterface = AdapterInterface.READ) -> AdapterResult:
        _exact("read interface", interface, AdapterInterface)
        _symbol("read tool name", tool_name)
        _fingerprint("read dependency", dependency_fingerprint)
        _exact("read arguments", arguments, dict)
        arguments = _copy_json(arguments)
        key = canonical_tool_key(tool_name, arguments, dependency_fingerprint)
        # Revalidate the complete frozen configuration before selecting a value.
        record = self.canonical_record()
        if interface is AdapterInterface.EFFECT:
            return AdapterResult(interface, AdapterStatus.UNSUPPORTED, key)
        for fixture in record["fixtures"]:
            if (fixture["interface"] == interface.value and fixture["tool_name"] == tool_name
                    and canonical_tool_key(fixture["tool_name"], fixture["arguments"], fixture["dependency_fingerprint"]) == key):
                return AdapterResult(interface, AdapterStatus.AVAILABLE, key, fixture["output"])
        return AdapterResult(interface, AdapterStatus.UNAVAILABLE, key)

    def lookup(self, tool_name: str, arguments: dict, dependency_fingerprint: str,
               *, interface: AdapterInterface = AdapterInterface.READ) -> Any:
        result = self.read(tool_name, arguments, dependency_fingerprint, interface=interface)
        if result.status is not AdapterStatus.AVAILABLE:
            raise LookupError("no supported exact frozen read fixture")
        return result.output


@dataclass(frozen=True, slots=True, init=False)
class _FakeAdapter:
    _universe: FakeReadUniverse
    _interface: AdapterInterface

    def __init__(self, fixtures: tuple[SyntheticReadFixture, ...], interface: AdapterInterface) -> None:
        universe = FakeReadUniverse(fixtures)
        if any(item["interface"] != interface.value for item in universe.canonical_record()["fixtures"]):
            raise ValueError("fixture belongs to a different adapter interface")
        object.__setattr__(self, "_universe", universe)
        object.__setattr__(self, "_interface", interface)

    def read(self, tool_name: str, arguments: dict, dependency_fingerprint: str) -> AdapterResult:
        _exact("adapter universe", self._universe, FakeReadUniverse)
        return self._universe.read(tool_name, arguments, dependency_fingerprint, interface=self._interface)

    def lookup(self, tool_name: str, arguments: dict, dependency_fingerprint: str) -> Any:
        _exact("adapter universe", self._universe, FakeReadUniverse)
        return self._universe.lookup(tool_name, arguments, dependency_fingerprint, interface=self._interface)


class FakeGitHub(_FakeAdapter):
    __slots__ = ()

    def __init__(self, fixtures: tuple[SyntheticReadFixture, ...]) -> None:
        super().__init__(fixtures, AdapterInterface.GITHUB)


class FakeFilesystem(_FakeAdapter):
    __slots__ = ()

    def __init__(self, fixtures: tuple[SyntheticReadFixture, ...]) -> None:
        super().__init__(fixtures, AdapterInterface.FILESYSTEM)


class FakeWeb(_FakeAdapter):
    __slots__ = ()

    def __init__(self, fixtures: tuple[SyntheticReadFixture, ...]) -> None:
        super().__init__(fixtures, AdapterInterface.WEB)


class FakeReadTool(_FakeAdapter):
    __slots__ = ()

    def __init__(self, fixtures: tuple[SyntheticReadFixture, ...]) -> None:
        super().__init__(fixtures, AdapterInterface.READ)


class FakeWorker(_FakeAdapter):
    """Frozen candidate text only; no worker process or supervisor authority."""

    __slots__ = ()

    def __init__(self, fixtures: tuple[SyntheticReadFixture, ...]) -> None:
        super().__init__(fixtures, AdapterInterface.WORKER)


class FakeEffectTool:
    """An explicit unsupported result, even when a proposal requests effects."""

    __slots__ = ()

    def attempt(self, proposal: NormalizedProposal) -> AdapterResult:
        _exact("effect proposal", proposal, NormalizedProposal)
        if proposal.kind is not ProposalKind.EFFECT_ATTEMPT:
            raise ValueError("effect adapter requires an effect-attempt proposal")
        return AdapterResult(AdapterInterface.EFFECT, AdapterStatus.UNSUPPORTED, proposal.proposal_id)


class FakeCredentialBroker:
    """Accept one public opaque test handle; never accept or resolve secrets."""

    __slots__ = ()

    def accept(self, handle: str, *, provider: str = "openai") -> dict:
        _exact("credential handle", handle, str)
        _exact("credential provider", provider, str)
        bounded_utf8_length("credential handle", handle, limit=64)
        if provider != "openai" or handle != "cred:openai.test":
            raise ValueError("only the opaque OpenAI synthetic test handle is supported")
        # No input text is forwarded or committed into any identity/receipt.
        return {"protocol_version": "IBAE-SYNTHETIC-CREDENTIAL-STATUS-V1", "provider": "openai",
                "status": "accepted_test_handle", "secret_resolved": False, "control_authority": False}


@dataclass(frozen=True, slots=True, init=False)
class FakeSupervisor:
    """A frozen, index-addressed stream receiving the actual compact surface."""

    _proposals: tuple[NormalizedProposal, ...]

    def __init__(self, proposals: tuple[NormalizedProposal, ...]) -> None:
        _exact("proposal stream", proposals, tuple)
        if len(proposals) > MAX_PROPOSALS:
            raise ValueError("proposal stream exceeds bound")
        frozen = []
        for proposal in proposals:
            _exact("stream proposal", proposal, NormalizedProposal)
            frozen.append(NormalizedProposal.from_record(proposal.canonical_record()))
        object.__setattr__(self, "_proposals", tuple(frozen))
        self.canonical_record()

    @classmethod
    def from_record(cls, record: dict) -> FakeSupervisor:
        value = _copy_json(record, limit=MAX_STREAM_BYTES, node_limit=65_536)
        _fields(value, {"protocol_version", "provider", "proposals", "control_authority", "network_enabled"}, "fake supervisor")
        if (value["protocol_version"] != SYNTHETIC_SUPERVISOR_VERSION or value["provider"] != "openai"
                or value["control_authority"] is not False or value["network_enabled"] is not False):
            raise ValueError("invalid synthetic supervisor version, provider or authority")
        _exact("proposal array", value["proposals"], list)
        return cls(tuple(NormalizedProposal.from_record(item) for item in value["proposals"]))

    def canonical_record(self) -> dict:
        _exact("proposal stream", self._proposals, tuple)
        if len(self._proposals) > MAX_PROPOSALS:
            raise ValueError("proposal stream exceeds bound")
        records = []
        for proposal in self._proposals:
            _exact("stream proposal", proposal, NormalizedProposal)
            records.append(proposal.canonical_record())
        return _copy_json({"protocol_version": SYNTHETIC_SUPERVISOR_VERSION, "provider": "openai",
            "proposals": records, "control_authority": False, "network_enabled": False},
            limit=MAX_STREAM_BYTES, node_limit=65_536)

    @property
    def stream_id(self) -> str:
        return domain_fingerprint("ibae.synthetic-supervisor-stream-id.v1", self.canonical_record())

    def propose(self, projection: SupervisorProjection, *, index: int) -> NormalizedProposal | None:
        _exact("supervisor projection", projection, SupervisorProjection)
        # Canonical validation consumes the same compact state as future live
        # transport. Projection contents are observations, not authorization.
        projection.canonical_record()
        _exact("proposal stream index", index, int)
        if not 0 <= index <= MAX_PROPOSALS:
            raise ValueError("proposal index is outside the bounded stream")
        record = self.canonical_record()
        if index >= len(record["proposals"]):
            return None
        return NormalizedProposal.from_record(record["proposals"][index])
