"""Narrow Python facade for the opaque v0.3 Rust execution runtime."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from ._records import CanonicalRuntimeRecord, CanonicalValue, require_fingerprint
from .canonical import canonical_json, domain_fingerprint

RUNTIME_PROTOCOL_VERSION = "IBAE-RUNTIME-PROTOCOL-V1"
RUNTIME_ADMISSION_DOMAIN = "ibae.runtime-admission-id.v1"
RUNTIME_RECEIPT_DOMAIN = "ibae.runtime-receipt-id.v1"

MAX_RUNTIME_REQUESTS = 1_000_000
MAX_RUNTIME_EXECUTIONS = 4_096
MAX_RUNTIME_RETRIES = 1_000_000
MAX_RUNTIME_HISTORY = 4_096

_RECEIPT_FIELDS = {
    "admission_id",
    "arguments_id",
    "authority_layer",
    "budget_delta",
    "cache_status",
    "command_id",
    "command_type",
    "dependency_fingerprint",
    "logical_tick",
    "logical_tick_delta",
    "observation_id",
    "prior_state_id",
    "protocol_version",
    "receipt_id",
    "rejection",
    "resulting_state_id",
    "session_id",
    "status",
    "tool_key",
    "tool_name",
    "transition_id",
}


def _require_exact_positive_int(name: str, value: int, hard_limit: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be an exact positive integer")
    if value > hard_limit:
        raise ValueError(f"{name} exceeds the runtime hard limit of {hard_limit}")
    return value


@dataclass(frozen=True, slots=True)
class RuntimeLimits:
    max_requests: int = 32
    max_executions: int = 16
    max_retries: int = 4
    max_history: int = 32

    def __post_init__(self) -> None:
        for name, value, hard_limit in (
            ("max_requests", self.max_requests, MAX_RUNTIME_REQUESTS),
            ("max_executions", self.max_executions, MAX_RUNTIME_EXECUTIONS),
            ("max_retries", self.max_retries, MAX_RUNTIME_RETRIES),
            ("max_history", self.max_history, MAX_RUNTIME_HISTORY),
        ):
            _require_exact_positive_int(name, value, hard_limit)

    def canonical_record(self) -> dict[str, int]:
        return {
            "max_executions": self.max_executions,
            "max_history": self.max_history,
            "max_requests": self.max_requests,
            "max_retries": self.max_retries,
        }


@dataclass(frozen=True, slots=True, init=False)
class RuntimeReceipt:
    """Mutation-isolated canonical runtime receipt returned by Rust."""

    _record: CanonicalValue

    def __init__(self, record: Mapping[str, Any]) -> None:
        if not isinstance(record, Mapping) or set(record) != _RECEIPT_FIELDS:
            raise ValueError("runtime receipt does not match the v1 schema")
        copied = dict(record)
        receipt_id = copied.pop("receipt_id", None)
        require_fingerprint("runtime receipt id", receipt_id)
        expected = domain_fingerprint(RUNTIME_RECEIPT_DOMAIN, copied)
        if receipt_id != expected:
            raise ValueError("runtime receipt identity does not match its record")
        if copied["protocol_version"] != RUNTIME_PROTOCOL_VERSION:
            raise ValueError("runtime receipt protocol version mismatch")
        if copied["authority_layer"] != "execution":
            raise ValueError("runtime receipt must remain execution-layer authority")
        if copied["status"] not in {"accepted", "rejected"}:
            raise ValueError("runtime receipt has an unsupported status")
        for name in ("logical_tick", "logical_tick_delta"):
            value = copied[name]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"runtime receipt {name} must be an exact integer")
        budget_delta = copied["budget_delta"]
        if not isinstance(budget_delta, Mapping) or set(budget_delta) != {
            "cache_hits",
            "executions",
            "requests",
            "retries",
        }:
            raise ValueError("runtime receipt has an invalid budget delta")
        for value in budget_delta.values():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("runtime budget deltas must be exact integers")
        for name in ("prior_state_id", "resulting_state_id", "session_id"):
            require_fingerprint(name.replace("_", " "), copied[name])
        if copied["status"] == "accepted" and copied["rejection"] is not None:
            raise ValueError("accepted runtime receipts cannot carry rejection state")
        if copied["status"] == "rejected" and not isinstance(
            copied["rejection"], Mapping
        ):
            raise ValueError("rejected runtime receipts require structured rejection")
        copied["receipt_id"] = receipt_id
        object.__setattr__(self, "_record", CanonicalValue.from_value(copied))

    @property
    def receipt_id(self) -> str:
        return self._record.to_value()["receipt_id"]

    @property
    def status(self) -> str:
        return self._record.to_value()["status"]

    @property
    def rejection_reason(self) -> str | None:
        rejection = self._record.to_value()["rejection"]
        return None if rejection is None else rejection["reason_code"]

    @property
    def transition_id(self) -> str | None:
        return self._record.to_value()["transition_id"]

    @property
    def cache_status(self) -> str | None:
        return self._record.to_value()["cache_status"]

    def canonical_record(self) -> dict[str, Any]:
        return self._record.to_value()


@dataclass(frozen=True, slots=True)
class RuntimeTransition:
    observation: Any
    receipt: RuntimeReceipt


@dataclass(frozen=True, slots=True)
class RuntimeSnapshot:
    session_id: str
    state_id: str
    logical_tick: int
    requests: int
    executions: int
    cache_hits: int
    retries: int
    history: tuple[str, ...]
    cache: tuple[tuple[str, str], ...]
    limits: RuntimeLimits

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> RuntimeSnapshot:
        if not isinstance(record, Mapping) or set(record) != {
            "cache",
            "counters",
            "history",
            "limits",
            "logical_tick",
            "protocol_version",
            "session_id",
            "state_id",
        }:
            raise ValueError("runtime snapshot does not match the v1 schema")
        if record["protocol_version"] != RUNTIME_PROTOCOL_VERSION:
            raise ValueError("runtime snapshot protocol version mismatch")
        counters = record["counters"]
        limits_record = record["limits"]
        limits = RuntimeLimits(
            max_requests=limits_record["max_requests"],
            max_executions=limits_record["max_executions"],
            max_retries=limits_record["max_retries"],
            max_history=limits_record["max_history"],
        )
        for name in ("session_id", "state_id"):
            require_fingerprint(name.replace("_", " "), record[name])
        numeric = {
            **counters,
            "logical_tick": record["logical_tick"],
        }
        for name, value in numeric.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"runtime snapshot {name} must be an exact integer")
        history = tuple(record["history"])
        if len(history) > limits.max_history:
            raise ValueError("runtime snapshot history exceeds its declared bound")
        for transition_id in history:
            require_fingerprint("runtime history transition id", transition_id)
        cache = tuple(
            (entry["tool_key"], entry["observation_id"])
            for entry in record["cache"]
        )
        if len(cache) > limits.max_executions:
            raise ValueError("runtime snapshot cache exceeds its declared bound")
        for tool_key, observation_id in cache:
            require_fingerprint("runtime cache tool key", tool_key)
            require_fingerprint("runtime cache observation id", observation_id)
        return cls(
            session_id=record["session_id"],
            state_id=record["state_id"],
            logical_tick=record["logical_tick"],
            requests=counters["requests"],
            executions=counters["executions"],
            cache_hits=counters["cache_hits"],
            retries=counters["retries"],
            history=history,
            cache=cache,
            limits=limits,
        )

    def canonical_record(self) -> dict[str, Any]:
        return {
            "cache": [
                {"observation_id": observation_id, "tool_key": tool_key}
                for tool_key, observation_id in self.cache
            ],
            "counters": {
                "cache_hits": self.cache_hits,
                "executions": self.executions,
                "requests": self.requests,
                "retries": self.retries,
            },
            "history": list(self.history),
            "limits": self.limits.canonical_record(),
            "logical_tick": self.logical_tick,
            "protocol_version": RUNTIME_PROTOCOL_VERSION,
            "session_id": self.session_id,
            "state_id": self.state_id,
        }


class RuntimeRejected(RuntimeError):
    """A stable, structured rejection returned by execution authority."""

    def __init__(self, receipt: RuntimeReceipt) -> None:
        self.receipt = receipt
        super().__init__(receipt.rejection_reason or "runtime command rejected")


class RustRuntimeSession:
    """Controlled facade over a private, non-subclassable native session."""

    __slots__ = ("__native",)

    def __init__(
        self,
        session_key: str,
        limits: RuntimeLimits | None = None,
    ) -> None:
        if not isinstance(session_key, str) or not session_key:
            raise ValueError("session_key must be a non-empty string")
        active_limits = limits or RuntimeLimits()
        if not isinstance(active_limits, RuntimeLimits):
            raise TypeError("limits must be RuntimeLimits")
        from ._runtime import NativeRuntimeSession

        self.__native = NativeRuntimeSession(
            session_key,
            active_limits.max_requests,
            active_limits.max_executions,
            active_limits.max_retries,
            active_limits.max_history,
        )

    @property
    def snapshot(self) -> RuntimeSnapshot:
        canonical = CanonicalRuntimeRecord(self.__native.snapshot())
        return RuntimeSnapshot.from_record(canonical.to_value())

    def terminal_cycle_period(self) -> int | None:
        return self.__native.terminal_cycle_period()

    @staticmethod
    def _invocation(operation: Callable[[], Any]) -> Callable[[], str]:
        def require_exact_json_form(value: Any) -> None:
            """Reject values whose Python semantics a JSON cache cannot preserve."""

            if value is None or type(value) in {bool, int, float, str}:
                return
            if type(value) is list:
                for nested in value:
                    require_exact_json_form(nested)
                return
            if type(value) is dict:
                keys = list(value)
                if any(type(key) is not str for key in keys):
                    raise TypeError("runtime observation keys must be exact strings")
                if keys != sorted(keys):
                    raise ValueError(
                        "runtime observation mappings must use canonical key order"
                    )
                for nested in value.values():
                    require_exact_json_form(nested)
                return
            raise TypeError(
                "runtime observations support only exact JSON Python forms"
            )

        def invoke() -> str:
            try:
                value = operation()
            except Exception:
                return canonical_json(
                    {"reason_code": "operation_failed", "status": "rejected"}
                )
            try:
                require_exact_json_form(value)
                observation = CanonicalValue.from_value(value)
            except (TypeError, ValueError, OverflowError, RecursionError):
                return canonical_json(
                    {
                        "reason_code": "invalid_observation",
                        "status": "rejected",
                    }
                )
            return f'{{"observation":{observation.text},"status":"ok"}}'

        return invoke

    def dispatch_canonical(
        self,
        command_json: str,
        operation: Callable[[], Any] | None = None,
    ) -> RuntimeTransition:
        if not isinstance(command_json, str):
            raise TypeError("command_json must be canonical text")
        callback = None if operation is None else self._invocation(operation)
        outcome_text = self.__native.dispatch(command_json, callback)
        outcome = CanonicalRuntimeRecord(outcome_text).to_value()
        receipt = RuntimeReceipt(outcome["receipt"])
        return RuntimeTransition(outcome["observation"], receipt)

    def dispatch_protocol(
        self,
        command: Mapping[str, Any],
        operation: Callable[[], Any] | None = None,
    ) -> RuntimeTransition:
        envelope = CanonicalRuntimeRecord.from_value(command)
        return self.dispatch_canonical(envelope.text, operation)

    def execute_read_transition(
        self,
        tool_name: str,
        arguments: Any,
        dependency_fingerprint: str,
        operation: Callable[[], Any],
        *,
        admission_id: str | None = None,
    ) -> RuntimeTransition:
        if not isinstance(tool_name, str) or not tool_name:
            raise ValueError("tool_name must be a non-empty string")
        if not isinstance(dependency_fingerprint, str) or not dependency_fingerprint:
            raise ValueError("dependency_fingerprint must be a non-empty string")
        if not callable(operation):
            raise TypeError("operation must be callable")
        canonical_arguments = CanonicalValue.from_value(arguments).to_value()
        if admission_id is None:
            admission_id = domain_fingerprint(
                RUNTIME_ADMISSION_DOMAIN,
                {
                    "arguments": canonical_arguments,
                    "dependency_fingerprint": dependency_fingerprint,
                    "tool_name": tool_name,
                },
            )
        require_fingerprint("runtime admission id", admission_id)
        command = {
            "admission_id": admission_id,
            "arguments": canonical_arguments,
            "command_type": "execute_read",
            "dependency_fingerprint": dependency_fingerprint,
            "protocol_version": RUNTIME_PROTOCOL_VERSION,
            "tool_name": tool_name,
        }
        return self.dispatch_protocol(command, operation)

    def execute_read(
        self,
        tool_name: str,
        arguments: Any,
        dependency_fingerprint: str,
        operation: Callable[[], Any],
        *,
        admission_id: str | None = None,
    ) -> Any:
        transition = self.execute_read_transition(
            tool_name,
            arguments,
            dependency_fingerprint,
            operation,
            admission_id=admission_id,
        )
        if transition.receipt.status == "rejected":
            raise RuntimeRejected(transition.receipt)
        return transition.observation

    def execute_admitted_read(
        self,
        decision: Any,
        proposal: Any,
        capability: Any,
        dependency_fingerprint: str,
        operation: Callable[[], Any],
    ) -> RuntimeTransition:
        """Execute one v0.2-admitted cacheable read without reclassifying it."""

        from .orchestration import (
            ActionProposal,
            AdmissionDecision,
            Capability,
            DecisionStatus,
            ReplaySafety,
        )

        if not isinstance(decision, AdmissionDecision):
            raise TypeError("decision must be an AdmissionDecision")
        if not isinstance(proposal, ActionProposal):
            raise TypeError("proposal must be an ActionProposal")
        if not isinstance(capability, Capability):
            raise TypeError("capability must be a Capability")
        if decision.status is not DecisionStatus.ADMITTED:
            raise ValueError("only an admitted action may cross into execution")
        if decision.proposal_id != proposal.proposal_id:
            raise ValueError("decision and proposal identities do not match")
        if proposal.capability != capability.name:
            raise ValueError("proposal and capability identities do not match")
        if capability.replay_safety is not ReplaySafety.CACHEABLE_READ:
            raise ValueError("only cacheable reads enter the v0.3 runtime cache path")
        assert decision.action_id is not None
        semantic_arguments = capability.normalize_arguments(proposal.arguments)
        expected_action_id = domain_fingerprint(
            "ibae.action-id.v1",
            {
                "arguments": semantic_arguments,
                "capability_id": capability.capability_id,
                "dependency_state_id": dependency_fingerprint,
            },
        )
        if decision.action_id != expected_action_id:
            raise ValueError(
                "admitted action identity does not match the supplied capability contract"
            )
        return self.execute_read_transition(
            capability.name,
            semantic_arguments,
            dependency_fingerprint,
            operation,
            admission_id=decision.action_id,
        )

    def record_retry_transition(
        self, *, admission_id: str | None = None
    ) -> RuntimeTransition:
        if admission_id is None:
            admission_id = domain_fingerprint(
                RUNTIME_ADMISSION_DOMAIN,
                {
                    "command_type": "record_retry",
                    "session_id": self.snapshot.session_id,
                },
            )
        require_fingerprint("runtime admission id", admission_id)
        return self.dispatch_protocol(
            {
                "admission_id": admission_id,
                "command_type": "record_retry",
                "protocol_version": RUNTIME_PROTOCOL_VERSION,
            }
        )

    def record_retry(self, *, admission_id: str | None = None) -> None:
        transition = self.record_retry_transition(admission_id=admission_id)
        if transition.receipt.status == "rejected":
            raise RuntimeRejected(transition.receipt)


def rust_canonical_json(canonical_text: str) -> str:
    """Validate and reproduce Python canonical JSON in the admitted Rust domain."""

    from ._runtime import canonicalize_json

    return canonicalize_json(canonical_text)
