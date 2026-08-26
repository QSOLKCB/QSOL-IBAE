"""Narrow Python facade for the opaque v0.3 Rust execution runtime."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ._records import (
    MAX_CANONICAL_STRING_BYTES,
    MAX_RECORD_TEXT_BYTES,
    CanonicalRuntimeRecord,
    CanonicalValue,
    bounded_utf8_length,
    materialize_bounded_iterable,
    require_fingerprint,
)
from .canonical import canonical_json, domain_fingerprint

RUNTIME_PROTOCOL_VERSION = "IBAE-RUNTIME-PROTOCOL-V1"
RUNTIME_ADMISSION_DOMAIN = "ibae.runtime-admission-id.v1"
RUNTIME_RECEIPT_DOMAIN = "ibae.runtime-receipt-id.v1"

MAX_RUNTIME_REQUESTS = 1_000_000
MAX_RUNTIME_EXECUTIONS = 4_096
MAX_RUNTIME_RETRIES = 1_000_000
MAX_RUNTIME_HISTORY = 4_096
MAX_RUNTIME_LOGICAL_TICK = (
    (2 * MAX_RUNTIME_REQUESTS)
    + (2 * MAX_RUNTIME_EXECUTIONS)
    + MAX_RUNTIME_RETRIES
)

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

_BUDGET_FIELDS = {"cache_hits", "executions", "requests", "retries"}
_LIMIT_FIELDS = {
    "max_executions",
    "max_history",
    "max_requests",
    "max_retries",
}
_REJECTION_FIELDS = {
    "authority_layer",
    "blocking_runtime_state",
    "invariant_ids",
    "reason_code",
}
_BLOCKING_STATE_FIELDS = {
    "counters",
    "limits",
    "logical_tick",
    "state_id",
}
_SNAPSHOT_FIELDS = {
    "cache",
    "counters",
    "history",
    "limits",
    "logical_tick",
    "protocol_version",
    "session_id",
    "state_id",
}
_CACHE_ENTRY_FIELDS = {"observation_id", "tool_key"}
_SUPPORTED_COMMAND_TYPES = {"execute_read", "record_retry"}
_CACHE_STATUSES = {"cache_hit", "cold_execution"}
_REASON_INVARIANTS = {
    "IBAE-RT-REJECT-INVALID-CANONICAL-COMMAND": (
        "IBAE-RT-002",
        "IBAE-RT-005",
    ),
    "IBAE-RT-REJECT-INVALID-COMMAND": ("IBAE-RT-002", "IBAE-RT-005"),
    "IBAE-RT-REJECT-UNSUPPORTED-COMMAND": ("IBAE-RT-002",),
    "IBAE-RT-REJECT-PROTOCOL-VERSION": ("IBAE-RT-002",),
    "IBAE-RT-REJECT-REQUEST-BUDGET": ("IBAE-BND-001", "IBAE-CLK-004"),
    "IBAE-RT-REJECT-EXECUTION-BUDGET": ("IBAE-BND-002", "IBAE-DET-003"),
    "IBAE-RT-REJECT-RETRY-BUDGET": ("IBAE-BND-003",),
    "IBAE-RT-REJECT-ARITHMETIC-OVERFLOW": (
        "IBAE-BND-007",
        "IBAE-CLK-001",
    ),
    "IBAE-RT-REJECT-INVALID-OBSERVATION": (
        "IBAE-REUSE-004",
        "IBAE-RT-005",
    ),
    "IBAE-RT-REJECT-OPERATION-FAILED": ("IBAE-DET-003", "IBAE-RT-001"),
}
_EXECUTION_METADATA_FIELDS = (
    "admission_id",
    "arguments_id",
    "command_id",
    "dependency_fingerprint",
    "tool_key",
    "tool_name",
)
_TOOL_AND_RESULT_FIELDS = (
    "arguments_id",
    "cache_status",
    "dependency_fingerprint",
    "observation_id",
    "tool_key",
    "tool_name",
    "transition_id",
)
_MAX_U64 = (1 << 64) - 1


def _require_exact_dict(
    name: str, value: Any, expected_fields: set[str]
) -> dict[str, Any]:
    if (
        type(value) is not dict
        or len(value) != len(expected_fields)
        or any(
            type(key) is not str or key not in expected_fields for key in value
        )
    ):
        raise ValueError(f"runtime receipt has an invalid {name}")
    return value


def _copy_exact_mapping(
    value: Any,
    expected_fields: set[str],
    *,
    error: str,
) -> dict[str, Any]:
    """Copy one closed record after examining at most N + 1 keys."""

    if not isinstance(value, Mapping):
        raise ValueError(error)
    seen: set[str] = set()
    try:
        iterator = iter(value)
        for _ in range(len(expected_fields) + 1):
            try:
                key = next(iterator)
            except StopIteration:
                break
            if (
                type(key) is not str
                or key not in expected_fields
                or key in seen
            ):
                raise ValueError(error)
            seen.add(key)
        else:
            raise ValueError(error)
        if seen != expected_fields:
            raise ValueError(error)
        return {field: value[field] for field in sorted(expected_fields)}
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(error) from exc


def _require_exact_u64(name: str, value: Any) -> int:
    if type(value) is not int or value < 0 or value > _MAX_U64:
        raise ValueError(f"runtime receipt {name} must be an exact u64 integer")
    return value


def _require_optional_fingerprint(name: str, value: Any) -> None:
    if value is None:
        return
    if type(value) is not str:
        raise ValueError(f"runtime receipt {name} must be a fingerprint or null")
    require_fingerprint(f"runtime receipt {name}", value)


def _require_optional_bounded_text(name: str, value: Any) -> None:
    if value is None:
        return
    if type(value) is not str or not value:
        raise ValueError(f"runtime receipt {name} must be bounded text or null")
    bounded_utf8_length(
        f"runtime receipt {name}", value, limit=MAX_RECORD_TEXT_BYTES
    )


def _require_optional_command_type(value: Any) -> None:
    if value is None:
        return
    if type(value) is not str:
        raise ValueError("runtime receipt command_type must be a string or null")
    bounded_utf8_length(
        "runtime receipt command_type",
        value,
        limit=MAX_CANONICAL_STRING_BYTES,
    )


def _require_none(record: Mapping[str, Any], fields: tuple[str, ...]) -> None:
    if any(record[field] is not None for field in fields):
        raise ValueError("runtime receipt carries fields forbidden for this transition")


def _require_present(record: Mapping[str, Any], fields: tuple[str, ...]) -> None:
    if any(record[field] is None for field in fields):
        raise ValueError("runtime receipt omits fields required for this transition")


def _require_accounting(
    record: Mapping[str, Any],
    *,
    requests: int = 0,
    executions: int = 0,
    cache_hits: int = 0,
    retries: int = 0,
    logical_tick_delta: int,
) -> None:
    expected = {
        "cache_hits": cache_hits,
        "executions": executions,
        "requests": requests,
        "retries": retries,
    }
    if record["budget_delta"] != expected:
        raise ValueError("runtime receipt accounting does not match its transition")
    if record["logical_tick_delta"] != logical_tick_delta:
        raise ValueError(
            "runtime receipt logical tick delta does not match its transition"
        )


def _require_state_change(record: Mapping[str, Any], *, changed: bool) -> None:
    states_differ = record["prior_state_id"] != record["resulting_state_id"]
    if states_differ is not changed:
        raise ValueError("runtime receipt state identity does not match its accounting")


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


def _validate_blocking_state(
    receipt: Mapping[str, Any], rejection: Mapping[str, Any]
) -> None:
    blocking = _require_exact_dict(
        "blocking runtime state",
        rejection["blocking_runtime_state"],
        _BLOCKING_STATE_FIELDS,
    )
    counters = _require_exact_dict(
        "blocking runtime counters", blocking["counters"], _BUDGET_FIELDS
    )
    for name, value in counters.items():
        _require_exact_u64(f"blocking counter {name}", value)

    limits_record = _require_exact_dict(
        "blocking runtime limits", blocking["limits"], _LIMIT_FIELDS
    )
    for name, value in limits_record.items():
        _require_exact_u64(f"blocking limit {name}", value)
    limits = RuntimeLimits(
        max_requests=limits_record["max_requests"],
        max_executions=limits_record["max_executions"],
        max_retries=limits_record["max_retries"],
        max_history=limits_record["max_history"],
    )
    logical_tick = _require_exact_u64(
        "blocking logical_tick", blocking["logical_tick"]
    )
    if logical_tick != receipt["logical_tick"]:
        raise ValueError("runtime rejection blocking tick does not match the receipt")
    if type(blocking["state_id"]) is not str:
        raise ValueError("runtime rejection blocking state id must be a fingerprint")
    require_fingerprint("runtime rejection blocking state id", blocking["state_id"])
    if blocking["state_id"] != receipt["resulting_state_id"]:
        raise ValueError(
            "runtime rejection blocking state id does not match the receipt"
        )

    if counters["requests"] > limits.max_requests:
        raise ValueError("runtime rejection request counter exceeds its limit")
    if counters["executions"] > limits.max_executions:
        raise ValueError("runtime rejection execution counter exceeds its limit")
    if counters["retries"] > limits.max_retries:
        raise ValueError("runtime rejection retry counter exceeds its limit")
    if counters["executions"] + counters["cache_hits"] > counters["requests"]:
        raise ValueError(
            "runtime rejection counters cannot arise from runtime commands"
        )

    authority_events = sum(counters.values())
    maximum_tick = authority_events + counters["executions"]
    if not authority_events <= logical_tick <= maximum_tick:
        raise ValueError(
            "runtime rejection logical tick is inconsistent with its counters"
        )
    for name, delta in receipt["budget_delta"].items():
        if delta > counters[name]:
            raise ValueError("runtime rejection delta exceeds its blocking counter")
    if receipt["logical_tick_delta"] > logical_tick:
        raise ValueError("runtime rejection tick delta exceeds its blocking tick")

    reason = rejection["reason_code"]
    if (
        reason == "IBAE-RT-REJECT-REQUEST-BUDGET"
        and counters["requests"] != limits.max_requests
    ):
        raise ValueError(
            "request-budget rejection does not prove an exhausted boundary"
        )
    if (
        reason == "IBAE-RT-REJECT-EXECUTION-BUDGET"
        and counters["executions"] != limits.max_executions
    ):
        raise ValueError(
            "execution-budget rejection does not prove an exhausted boundary"
        )
    if (
        reason == "IBAE-RT-REJECT-RETRY-BUDGET"
        and counters["retries"] != limits.max_retries
    ):
        raise ValueError("retry-budget rejection does not prove an exhausted boundary")


def _validate_rejection(receipt: Mapping[str, Any]) -> str:
    rejection = _require_exact_dict(
        "structured rejection", receipt["rejection"], _REJECTION_FIELDS
    )
    if (
        type(rejection["authority_layer"]) is not str
        or rejection["authority_layer"] != "execution"
    ):
        raise ValueError("runtime rejection must remain execution-layer authority")
    reason = rejection["reason_code"]
    if type(reason) is not str or reason not in _REASON_INVARIANTS:
        raise ValueError("runtime rejection has an unsupported reason code")
    invariant_ids = rejection["invariant_ids"]
    if type(invariant_ids) is not list or invariant_ids != list(
        _REASON_INVARIANTS[reason]
    ):
        raise ValueError("runtime rejection invariant ids do not match its reason")
    _validate_blocking_state(receipt, rejection)
    return reason


def _require_execute_command(receipt: Mapping[str, Any]) -> None:
    if receipt["command_type"] != "execute_read":
        raise ValueError("runtime receipt is not bound to an execute_read command")
    _require_present(receipt, _EXECUTION_METADATA_FIELDS)


def _require_retry_command(receipt: Mapping[str, Any]) -> None:
    if receipt["command_type"] != "record_retry":
        raise ValueError("runtime receipt is not bound to a record_retry command")
    _require_present(receipt, ("admission_id", "command_id"))
    _require_none(receipt, _TOOL_AND_RESULT_FIELDS)


def _validate_accepted_receipt(receipt: Mapping[str, Any]) -> None:
    if receipt["rejection"] is not None:
        raise ValueError("accepted runtime receipts cannot carry rejection state")
    command_type = receipt["command_type"]
    if command_type not in _SUPPORTED_COMMAND_TYPES:
        raise ValueError("accepted runtime receipt has an unsupported command type")
    if command_type == "record_retry":
        _require_retry_command(receipt)
        _require_accounting(receipt, retries=1, logical_tick_delta=1)
        _require_state_change(receipt, changed=True)
        return

    _require_execute_command(receipt)
    _require_present(receipt, ("cache_status", "observation_id", "transition_id"))
    if receipt["cache_status"] == "cold_execution":
        _require_accounting(
            receipt, requests=1, executions=1, logical_tick_delta=3
        )
    elif receipt["cache_status"] == "cache_hit":
        _require_accounting(
            receipt, requests=1, cache_hits=1, logical_tick_delta=2
        )
    else:  # The field validator rejects other non-null values; null is invalid here.
        raise ValueError("accepted read receipt requires a cache transition status")
    _require_state_change(receipt, changed=True)


def _validate_parsing_rejection(
    receipt: Mapping[str, Any], reason: str
) -> None:
    _require_none(receipt, _TOOL_AND_RESULT_FIELDS)
    if reason == "IBAE-RT-REJECT-INVALID-CANONICAL-COMMAND":
        _require_none(receipt, ("admission_id", "command_id", "command_type"))
    else:
        _require_present(receipt, ("command_id",))
        if (
            reason == "IBAE-RT-REJECT-UNSUPPORTED-COMMAND"
            and (
                receipt["command_type"] is None
                or receipt["command_type"] in _SUPPORTED_COMMAND_TYPES
            )
        ):
            raise ValueError("unsupported-command rejection has no unsupported variant")
    _require_accounting(receipt, logical_tick_delta=0)
    _require_state_change(receipt, changed=False)


def _validate_arithmetic_rejection(receipt: Mapping[str, Any]) -> None:
    _require_none(receipt, ("cache_status", "observation_id", "transition_id"))
    if receipt["command_type"] == "record_retry":
        _require_retry_command(receipt)
        _require_accounting(receipt, logical_tick_delta=0)
        _require_state_change(receipt, changed=False)
        return
    _require_execute_command(receipt)
    admitted_prefixes = (
        ({"cache_hits": 0, "executions": 0, "requests": 0, "retries": 0}, 0),
        ({"cache_hits": 0, "executions": 0, "requests": 1, "retries": 0}, 1),
        ({"cache_hits": 0, "executions": 1, "requests": 1, "retries": 0}, 2),
    )
    accounting = (receipt["budget_delta"], receipt["logical_tick_delta"])
    if accounting not in admitted_prefixes:
        raise ValueError("arithmetic rejection has an impossible admitted prefix")
    _require_state_change(
        receipt, changed=receipt["logical_tick_delta"] != 0
    )


def _validate_rejected_receipt(receipt: Mapping[str, Any]) -> None:
    reason = _validate_rejection(receipt)
    _require_none(receipt, ("cache_status", "observation_id", "transition_id"))
    if reason in {
        "IBAE-RT-REJECT-INVALID-CANONICAL-COMMAND",
        "IBAE-RT-REJECT-INVALID-COMMAND",
        "IBAE-RT-REJECT-UNSUPPORTED-COMMAND",
        "IBAE-RT-REJECT-PROTOCOL-VERSION",
    }:
        _validate_parsing_rejection(receipt, reason)
    elif reason == "IBAE-RT-REJECT-REQUEST-BUDGET":
        _require_execute_command(receipt)
        _require_accounting(receipt, logical_tick_delta=0)
        _require_state_change(receipt, changed=False)
    elif reason == "IBAE-RT-REJECT-EXECUTION-BUDGET":
        _require_execute_command(receipt)
        _require_accounting(receipt, requests=1, logical_tick_delta=1)
        _require_state_change(receipt, changed=True)
    elif reason in {
        "IBAE-RT-REJECT-INVALID-OBSERVATION",
        "IBAE-RT-REJECT-OPERATION-FAILED",
    }:
        _require_execute_command(receipt)
        _require_accounting(
            receipt, requests=1, executions=1, logical_tick_delta=2
        )
        _require_state_change(receipt, changed=True)
    elif reason == "IBAE-RT-REJECT-RETRY-BUDGET":
        _require_retry_command(receipt)
        _require_accounting(receipt, logical_tick_delta=0)
        _require_state_change(receipt, changed=False)
    else:
        _validate_arithmetic_rejection(receipt)


@dataclass(frozen=True, slots=True, init=False)
class RuntimeReceipt:
    """Mutation-isolated canonical runtime receipt returned by Rust."""

    _record: CanonicalValue
    _native_seal: Any | None = field(repr=False, compare=False)

    def __init_subclass__(cls, **kwargs: Any) -> None:
        raise TypeError("RuntimeReceipt cannot be subclassed")

    def __init__(
        self,
        record: Mapping[str, Any],
        *,
        _native_seal: Any | None = None,
    ) -> None:
        copied = _copy_exact_mapping(
            record,
            _RECEIPT_FIELDS,
            error="runtime receipt does not match the v1 schema",
        )
        receipt_id = copied.pop("receipt_id", None)
        if type(receipt_id) is not str:
            raise ValueError("runtime receipt id must be a fingerprint")
        require_fingerprint("runtime receipt id", receipt_id)
        if (
            type(copied["protocol_version"]) is not str
            or copied["protocol_version"] != RUNTIME_PROTOCOL_VERSION
        ):
            raise ValueError("runtime receipt protocol version mismatch")
        if (
            type(copied["authority_layer"]) is not str
            or copied["authority_layer"] != "execution"
        ):
            raise ValueError("runtime receipt must remain execution-layer authority")
        if type(copied["status"]) is not str or copied["status"] not in {
            "accepted",
            "rejected",
        }:
            raise ValueError("runtime receipt has an unsupported status")
        command_type = copied["command_type"]
        _require_optional_command_type(command_type)
        cache_status = copied["cache_status"]
        if cache_status is not None and (
            type(cache_status) is not str or cache_status not in _CACHE_STATUSES
        ):
            raise ValueError("runtime receipt has an unsupported cache status")

        for name in (
            "admission_id",
            "arguments_id",
            "command_id",
            "observation_id",
            "tool_key",
            "transition_id",
        ):
            _require_optional_fingerprint(name, copied[name])
        for name in ("prior_state_id", "resulting_state_id", "session_id"):
            if type(copied[name]) is not str:
                raise ValueError(f"runtime receipt {name} must be a fingerprint")
            require_fingerprint(f"runtime receipt {name}", copied[name])
        for name in ("dependency_fingerprint", "tool_name"):
            _require_optional_bounded_text(name, copied[name])

        for name in ("logical_tick", "logical_tick_delta"):
            _require_exact_u64(name, copied[name])
        if copied["logical_tick"] > MAX_RUNTIME_LOGICAL_TICK:
            raise ValueError("runtime receipt logical tick exceeds the hard bound")
        if copied["logical_tick_delta"] > copied["logical_tick"]:
            raise ValueError("runtime receipt logical tick delta exceeds logical tick")
        budget_delta = _require_exact_dict(
            "budget delta", copied["budget_delta"], _BUDGET_FIELDS
        )
        for name, value in budget_delta.items():
            _require_exact_u64(f"budget delta {name}", value)
            if value > 1:
                raise ValueError(
                    "one runtime command cannot consume multiple budget units"
                )

        if copied["status"] == "accepted":
            _validate_accepted_receipt(copied)
        else:
            if copied["rejection"] is None:
                raise ValueError(
                    "rejected runtime receipts require structured rejection"
                )
            _validate_rejected_receipt(copied)
        expected = domain_fingerprint(RUNTIME_RECEIPT_DOMAIN, copied)
        if receipt_id != expected:
            raise ValueError("runtime receipt identity does not match its record")
        copied["receipt_id"] = receipt_id
        object.__setattr__(self, "_record", CanonicalValue.from_value(copied))
        if _native_seal is not None:
            from ._runtime import NativeRuntimeReceiptSeal

            if type(_native_seal) is not NativeRuntimeReceiptSeal:
                raise TypeError("runtime receipt requires a native source seal")
            if not bool(_native_seal.validates(self._record.text)):
                raise ValueError("native runtime receipt seal does not match its record")
        object.__setattr__(self, "_native_seal", _native_seal)

    def _validated_value(self) -> dict[str, Any]:
        record = object.__getattribute__(self, "_record")
        seal = object.__getattribute__(self, "_native_seal")
        if type(record) is not CanonicalValue:
            raise ValueError("runtime receipt canonical record is not trusted")
        # Revalidate canonical form in case an unsupported object.__setattr__
        # mutation changed the frozen CanonicalValue itself.
        CanonicalValue(record.text)
        if seal is not None:
            from ._runtime import NativeRuntimeReceiptSeal

            if type(seal) is not NativeRuntimeReceiptSeal:
                raise ValueError("runtime receipt native source seal is not trusted")
            if not bool(seal.validates(record.text)):
                raise ValueError(
                    "native runtime receipt seal no longer matches its record"
                )
        return record.to_value()

    @property
    def receipt_id(self) -> str:
        return self._validated_value()["receipt_id"]

    @property
    def source_bound(self) -> bool:
        try:
            record = object.__getattribute__(self, "_record")
            seal = object.__getattribute__(self, "_native_seal")
            if type(record) is not CanonicalValue or seal is None:
                return False
            CanonicalValue(record.text)
            from ._runtime import NativeRuntimeReceiptSeal

            return type(seal) is NativeRuntimeReceiptSeal and bool(
                seal.validates(record.text)
            )
        except (AttributeError, TypeError, ValueError):
            return False

    def _native_source_seal(self) -> Any:
        if not self.source_bound:
            raise ValueError("runtime receipt has structural validation only")
        return object.__getattribute__(self, "_native_seal")

    @property
    def status(self) -> str:
        return self._validated_value()["status"]

    @property
    def rejection_reason(self) -> str | None:
        rejection = self._validated_value()["rejection"]
        return None if rejection is None else rejection["reason_code"]

    @property
    def transition_id(self) -> str | None:
        return self._validated_value()["transition_id"]

    @property
    def cache_status(self) -> str | None:
        return self._validated_value()["cache_status"]

    def canonical_record(self) -> dict[str, Any]:
        return self._validated_value()


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
        record = _copy_exact_mapping(
            record,
            _SNAPSHOT_FIELDS,
            error="runtime snapshot does not match the v1 schema",
        )
        if record["protocol_version"] != RUNTIME_PROTOCOL_VERSION:
            raise ValueError("runtime snapshot protocol version mismatch")
        counters = _copy_exact_mapping(
            record["counters"],
            _BUDGET_FIELDS,
            error="runtime snapshot counters do not match the v1 schema",
        )
        limits_record = _copy_exact_mapping(
            record["limits"],
            _LIMIT_FIELDS,
            error="runtime snapshot limits do not match the v1 schema",
        )
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
        history = materialize_bounded_iterable(
            "runtime snapshot history",
            record["history"],
            limit=limits.max_history,
        )
        for transition_id in history:
            require_fingerprint("runtime history transition id", transition_id)
        cache_entries = materialize_bounded_iterable(
            "runtime snapshot cache",
            record["cache"],
            limit=limits.max_executions,
        )
        cache = tuple(
            (
                entry["tool_key"],
                entry["observation_id"],
            )
            for entry in (
                _copy_exact_mapping(
                    item,
                    _CACHE_ENTRY_FIELDS,
                    error="runtime snapshot cache entry does not match the v1 schema",
                )
                for item in cache_entries
            )
        )
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
        outcome_text, native_seal = self.__native.dispatch(command_json, callback)
        outcome = CanonicalRuntimeRecord(outcome_text).to_value()
        receipt = RuntimeReceipt(outcome["receipt"], _native_seal=native_seal)
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
