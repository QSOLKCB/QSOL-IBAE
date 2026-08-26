"""Bounded compact evidence facade over the opaque Rust reducer.

The v1 profile proves only exact reported counts and ordered aggregate
identities for records admitted through the reducer.  It does not establish
external truth, producer authentication, benchmark superiority, or semantics
beyond the declared verifier.  Compact transport identity is distinct from
the separately bound execution-correctness identity.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from ._records import CanonicalValue, bounded_utf8_length, require_fingerprint
from .canonical import domain_fingerprint

EVIDENCE_PROTOCOL_VERSION: Final = "IBAE-COMPACT-EVIDENCE-V1"
EVIDENCE_PROFILE: Final = "IBAE-COMPACT-EVIDENCE-COUNTS-AND-IDENTITIES-V1"
EVIDENCE_RECEIPT_DOMAIN: Final = "ibae.compact-evidence-receipt.v1"
EVIDENCE_SUMMARY_DOMAIN: Final = "ibae.evidence-aggregate-summary.v1"
EVIDENCE_EXPANSION_DOMAIN: Final = "ibae.evidence-expansion.v1"
EVIDENCE_ADMISSION_DOMAIN: Final = "ibae.evidence-admission-aggregate.v1"
EVIDENCE_AUTHORIZATION_DOMAIN: Final = "ibae.evidence-authorization-manifest.v1"
FAST_FOLD_ALGORITHM: Final = "fnv1a64-non-cryptographic-v1"

MAX_EVIDENCE_CASES: Final = 1_000_000
MAX_EVIDENCE_FAILURE_DETAILS: Final = 32
MAX_EVIDENCE_FAILURE_DETAIL_BYTES: Final = 4_096
MAX_COMPACT_EVIDENCE_BYTES: Final = 2_048
MAX_EVIDENCE_EXPANSION_BYTES: Final = 262_144
MAX_EVIDENCE_AUTHORIZATIONS: Final = 256
MAX_U64: Final = (1 << 64) - 1

EVIDENCE_PROFILE_CLAIMS: Final = frozenset(
    {
        "authorization_manifest_binding",
        "bound_execution_identity",
        "bound_governance_identity",
        "bound_orchestration_identity",
        "bound_task_identity",
        "declared_case_count",
        "execution_manifest_root_boundary_count_correspondence",
        "exact_reported_counters",
        "governed_authorization_manifest_coverage",
        "ordered_admission_aggregate",
        "ordered_input_aggregate",
        "ordered_runtime_admission_aggregate",
        "ordered_result_aggregate",
        "ordered_case_receipt_aggregate",
        "reported_failure_summary",
        "runtime_session_state_boundary_continuity",
    }
)

_RECEIPT_FIELDS = {
    "aggregate_identities",
    "authorization_manifest",
    "bound_identities",
    "case_counts",
    "counter_totals",
    "evidence_profile",
    "failure_summary",
    "item_counts",
    "limits",
    "protocol_version",
    "receipt_id",
    "runtime_boundary",
    "status",
}
_SUMMARY_FIELDS = {
    "aggregate_identities",
    "authorization_manifest",
    "bound_identities",
    "case_counts",
    "counter_totals",
    "evidence_profile",
    "item_counts",
    "protocol_version",
    "runtime_boundary",
    "summary_id",
}
_COUNTER_FIELDS = {
    "actual_executions",
    "cache_hits",
    "canonical_mismatches",
    "invariant_violations",
    "mutations",
    "receipt_mismatches",
    "requests",
    "retries",
}
_HEX16 = re.compile(r"^[0-9a-f]{16}$")
_BOUNDARY_FIELDS = {
    "final_state_id",
    "first_runtime_receipt_id",
    "initial_state_id",
    "last_runtime_receipt_id",
    "session_id",
}
_AUTHORIZATION_FIELDS = {
    "action_id",
    "arguments_id",
    "authority_class",
    "cache_reuse_permitted",
    "dependency_fingerprint",
    "tool_admission_receipt_id",
    "tool_name",
}


def _exact_mapping(name: str, value: Any, fields: set[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} does not match the v1 schema")
    keys: list[Any] = []
    for key in value:
        if len(keys) == len(fields):
            raise ValueError(f"{name} does not match the v1 schema")
        keys.append(key)
    if set(keys) != fields:
        raise ValueError(f"{name} does not match the v1 schema")
    return {key: value[key] for key in sorted(fields)}


def _u64(name: str, value: Any) -> int:
    if type(value) is not int or value < 0 or value > MAX_U64:
        raise ValueError(f"{name} must be an exact unsigned 64-bit integer")
    return value


def _bounded_positive(name: str, value: Any, maximum: int) -> int:
    _u64(name, value)
    if value == 0 or value > maximum:
        raise ValueError(f"{name} must be in the range 1..{maximum}")
    return value


def _normalize_authorization_manifest(
    entries: Any,
) -> tuple[dict[str, Any], ...]:
    if isinstance(entries, (str, bytes, bytearray)):
        raise TypeError("authorization manifest must be an iterable of entries")
    try:
        iterator = iter(entries)
    except TypeError as exc:
        raise TypeError("authorization manifest must be iterable") from exc
    normalized: list[dict[str, Any]] = []
    for entry in iterator:
        if len(normalized) == MAX_EVIDENCE_AUTHORIZATIONS:
            raise ValueError("authorization manifest exceeds its hard bound")
        record = _exact_mapping(
            "evidence authorization entry", entry, _AUTHORIZATION_FIELDS
        )
        for name in (
            "action_id",
            "arguments_id",
            "dependency_fingerprint",
            "tool_admission_receipt_id",
        ):
            require_fingerprint(f"authorization {name}", record[name])
        if record["authority_class"] not in {"PURE_READ", "SNAPSHOT_READ"}:
            raise ValueError("authorization class is not runtime-finalizable")
        if type(record["cache_reuse_permitted"]) is not bool:
            raise ValueError("authorization cache reuse flag must be an exact boolean")
        if (
            not isinstance(record["tool_name"], str)
            or not record["tool_name"]
        ):
            raise ValueError("authorization tool name is invalid")
        bounded_utf8_length(
            "authorization tool name", record["tool_name"], limit=4_096
        )
        normalized.append(record)
    normalized.sort(key=lambda entry: entry["action_id"])
    action_ids = [entry["action_id"] for entry in normalized]
    if len(action_ids) != len(set(action_ids)):
        raise ValueError("authorization action IDs must be unique")
    return tuple(normalized)


def authorization_manifest_identity(entries: Any) -> str:
    normalized = _normalize_authorization_manifest(entries)
    record = CanonicalValue.from_value({"entries": list(normalized)}).to_value()
    return domain_fingerprint(
        EVIDENCE_AUTHORIZATION_DOMAIN,
        record,
    )


def aggregate_admission_stream(admission_ids: Any) -> str:
    """Compute the ordered v1 admission root without retaining the stream."""

    if isinstance(admission_ids, (str, bytes, bytearray)):
        raise TypeError("admission IDs must be an iterable of fingerprints")
    try:
        iterator = iter(admission_ids)
    except TypeError as exc:
        raise TypeError("admission IDs must be iterable") from exc
    prior = domain_fingerprint(EVIDENCE_ADMISSION_DOMAIN, {"profile": EVIDENCE_PROFILE})
    for ordinal, identity in enumerate(iterator):
        if ordinal == MAX_EVIDENCE_CASES:
            raise ValueError("admission stream exceeds its hard bound")
        require_fingerprint("evidence admission identity", identity)
        prior = domain_fingerprint(
            EVIDENCE_ADMISSION_DOMAIN,
            {
                "identity": identity,
                "item_type": "case",
                "ordinal": ordinal,
                "prior": prior,
            },
        )
    return prior


@dataclass(frozen=True, slots=True)
class EvidenceLimits:
    max_cases: int = 100_000
    max_failure_details: int = 8

    def __post_init__(self) -> None:
        _bounded_positive("max_cases", self.max_cases, MAX_EVIDENCE_CASES)
        _bounded_positive(
            "max_failure_details",
            self.max_failure_details,
            MAX_EVIDENCE_FAILURE_DETAILS,
        )

    def canonical_record(self) -> dict[str, int]:
        return {
            "max_cases": self.max_cases,
            "max_failure_details": self.max_failure_details,
        }


@dataclass(frozen=True, slots=True)
class EvidenceCaseCounts:
    failed: int
    passed: int
    rejected: int
    total: int

    @classmethod
    def from_record(cls, value: Any, *, allow_zero: bool = False) -> EvidenceCaseCounts:
        record = _exact_mapping(
            "evidence case counts",
            value,
            {"failed", "passed", "rejected", "total"},
        )
        for name, count in record.items():
            _u64(f"evidence case count {name}", count)
        if record["total"] != (
            record["failed"] + record["passed"] + record["rejected"]
        ):
            raise ValueError("evidence case counts are inconsistent")
        if not allow_zero and record["total"] == 0:
            raise ValueError("compact evidence requires at least one case")
        return cls(**record)

    @property
    def failure_count(self) -> int:
        return self.failed + self.rejected

    def canonical_record(self) -> dict[str, int]:
        return {
            "failed": self.failed,
            "passed": self.passed,
            "rejected": self.rejected,
            "total": self.total,
        }


@dataclass(frozen=True, slots=True)
class EvidenceCounters:
    actual_executions: int = 0
    cache_hits: int = 0
    canonical_mismatches: int = 0
    invariant_violations: int = 0
    mutations: int = 0
    receipt_mismatches: int = 0
    requests: int = 0
    retries: int = 0

    def __post_init__(self) -> None:
        for name, value in self.canonical_record().items():
            _u64(f"evidence counter {name}", value)

    @classmethod
    def from_record(cls, value: Any) -> EvidenceCounters:
        return cls(**_exact_mapping("evidence counters", value, _COUNTER_FIELDS))

    @property
    def has_correctness_mismatch(self) -> bool:
        return any(
            (
                self.canonical_mismatches,
                self.invariant_violations,
                self.receipt_mismatches,
            )
        )

    def canonical_record(self) -> dict[str, int]:
        return {
            "actual_executions": self.actual_executions,
            "cache_hits": self.cache_hits,
            "canonical_mismatches": self.canonical_mismatches,
            "invariant_violations": self.invariant_violations,
            "mutations": self.mutations,
            "receipt_mismatches": self.receipt_mismatches,
            "requests": self.requests,
            "retries": self.retries,
        }


def _validate_aggregate_identities(value: Any) -> dict[str, str]:
    record = _exact_mapping(
        "evidence aggregate identities",
        value,
        {"admissions", "inputs", "receipts", "results"},
    )
    for name, identity in record.items():
        require_fingerprint(f"evidence aggregate {name}", identity)
    return record


def _validate_authorization_manifest_record(value: Any) -> tuple[int, str]:
    record = _exact_mapping(
        "evidence authorization manifest", value, {"count", "manifest_id"}
    )
    count = _u64("evidence authorization manifest count", record["count"])
    if count > MAX_EVIDENCE_AUTHORIZATIONS:
        raise ValueError("evidence authorization manifest exceeds its hard bound")
    identity = require_fingerprint(
        "evidence authorization manifest identity", record["manifest_id"]
    )
    return count, identity


def _validate_item_counts(value: Any, cases: EvidenceCaseCounts) -> tuple[int, int]:
    record = _exact_mapping(
        "evidence item counts", value, {"case_records", "child_receipts"}
    )
    case_records = _u64("case record count", record["case_records"])
    child_receipts = _u64("child receipt count", record["child_receipts"])
    if case_records + child_receipts == 0:
        raise ValueError("compact evidence must contain at least one item")
    if case_records + child_receipts > cases.total:
        raise ValueError("evidence item counts exceed represented case count")
    return case_records, child_receipts


def _validate_runtime_boundary(value: Any) -> dict[str, str] | None:
    if value is None:
        return None
    record = _exact_mapping("evidence runtime boundary", value, _BOUNDARY_FIELDS)
    for name, identity in record.items():
        require_fingerprint(f"evidence runtime boundary {name}", identity)
    return record


class EvidenceAggregateSummary:
    """A live-reducer-bound, sealed aggregate used to construct execution identity."""

    __slots__ = (
        "_aggregates",
        "_authorization_manifest_count",
        "_authorization_manifest_identity",
        "_bound",
        "_case_counts",
        "_case_record_count",
        "_child_receipt_count",
        "_counters",
        "_first_runtime_receipt",
        "_last_runtime_receipt",
        "_native_seal",
        "_record",
        "_runtime_boundary",
    )

    def __init_subclass__(cls, **kwargs: Any) -> None:
        raise TypeError("EvidenceAggregateSummary cannot be subclassed")

    def __setattr__(self, name: str, value: Any) -> None:
        if hasattr(self, name):
            raise AttributeError("EvidenceAggregateSummary is immutable")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        raise AttributeError("EvidenceAggregateSummary is immutable")

    def __init__(
        self,
        canonical_text: str,
        *,
        _native_seal: Any,
        _first_runtime_receipt: Any | None,
        _last_runtime_receipt: Any | None,
    ) -> None:
        from ._runtime import NativeEvidenceSummarySeal

        if type(_native_seal) is not NativeEvidenceSummarySeal:
            raise TypeError("evidence aggregate summaries require a native source seal")
        canonical = CanonicalValue(canonical_text)
        if not bool(_native_seal.validates(canonical.text)):
            raise ValueError("native evidence summary seal does not match its record")
        if len(canonical.text.encode("utf-8")) > MAX_COMPACT_EVIDENCE_BYTES:
            raise ValueError("evidence summary exceeds its fixed byte ceiling")
        record = _exact_mapping("evidence aggregate summary", canonical.to_value(), _SUMMARY_FIELDS)
        if record["protocol_version"] != EVIDENCE_PROTOCOL_VERSION:
            raise ValueError("evidence summary protocol version mismatch")
        if record["evidence_profile"] != EVIDENCE_PROFILE:
            raise ValueError("evidence summary sufficiency profile mismatch")
        summary_id = record.pop("summary_id")
        require_fingerprint("evidence summary id", summary_id)
        if domain_fingerprint(EVIDENCE_SUMMARY_DOMAIN, record) != summary_id:
            raise ValueError("evidence summary identity does not match its record")
        record["summary_id"] = summary_id
        aggregates = _validate_aggregate_identities(record["aggregate_identities"])
        bound = _exact_mapping(
            "evidence summary bound identities",
            record["bound_identities"],
            {"governance", "orchestration", "task"},
        )
        for name, identity in bound.items():
            require_fingerprint(f"evidence summary {name} identity", identity)
        authorization_count, authorization_identity = (
            _validate_authorization_manifest_record(record["authorization_manifest"])
        )
        cases = EvidenceCaseCounts.from_record(record["case_counts"])
        counters = EvidenceCounters.from_record(record["counter_totals"])
        case_records, child_receipts = _validate_item_counts(record["item_counts"], cases)
        runtime_boundary = _validate_runtime_boundary(record["runtime_boundary"])
        if runtime_boundary is not None and (
            child_receipts != 0 or case_records != cases.total
        ):
            raise ValueError("runtime boundary requires a direct-case-only evidence stream")
        if runtime_boundary is not None:
            from .runtime import RuntimeReceipt

            if type(_first_runtime_receipt) is not RuntimeReceipt or type(
                _last_runtime_receipt
            ) is not RuntimeReceipt:
                raise ValueError("runtime-bound evidence summary requires typed endpoints")
            if not _first_runtime_receipt.source_bound or not _last_runtime_receipt.source_bound:
                raise ValueError("runtime-bound evidence endpoints require native source seals")
            first_record = _first_runtime_receipt.canonical_record()
            last_record = _last_runtime_receipt.canonical_record()
            if (
                _first_runtime_receipt.receipt_id
                != runtime_boundary["first_runtime_receipt_id"]
                or _last_runtime_receipt.receipt_id
                != runtime_boundary["last_runtime_receipt_id"]
                or first_record["session_id"] != runtime_boundary["session_id"]
                or last_record["session_id"] != runtime_boundary["session_id"]
                or first_record["prior_state_id"]
                != runtime_boundary["initial_state_id"]
                or last_record["resulting_state_id"]
                != runtime_boundary["final_state_id"]
            ):
                raise ValueError("runtime endpoint receipts do not match summary boundary")
        elif _first_runtime_receipt is not None or _last_runtime_receipt is not None:
            raise ValueError("evidence summary cannot expose unbound runtime endpoints")
        self._record = CanonicalValue.from_value(record)
        self._aggregates = aggregates
        self._authorization_manifest_count = authorization_count
        self._authorization_manifest_identity = authorization_identity
        self._bound = bound
        self._case_counts = cases
        self._counters = counters
        self._case_record_count = case_records
        self._child_receipt_count = child_receipts
        self._native_seal = _native_seal
        self._runtime_boundary = runtime_boundary
        self._first_runtime_receipt = _first_runtime_receipt
        self._last_runtime_receipt = _last_runtime_receipt

    def _validated_value(self) -> dict[str, Any]:
        record = object.__getattribute__(self, "_record")
        seal = object.__getattribute__(self, "_native_seal")
        if type(record) is not CanonicalValue:
            raise ValueError("evidence summary canonical record is not trusted")
        CanonicalValue(record.text)
        from ._runtime import NativeEvidenceSummarySeal

        if type(seal) is not NativeEvidenceSummarySeal:
            raise ValueError("evidence summary native source seal is not trusted")
        if not bool(seal.validates(record.text)):
            raise ValueError("native evidence summary seal no longer matches its record")
        return record.to_value()

    def _runtime_endpoint(self, *, first: bool) -> Any | None:
        boundary = self._validated_value()["runtime_boundary"]
        endpoint = (
            self._first_runtime_receipt if first else self._last_runtime_receipt
        )
        if boundary is None:
            if endpoint is not None:
                raise ValueError("evidence summary has an unbound runtime endpoint")
            return None
        from .runtime import RuntimeReceipt

        if type(endpoint) is not RuntimeReceipt or not endpoint.source_bound:
            raise ValueError("evidence summary runtime endpoint is not source-bound")
        runtime_record = endpoint.canonical_record()
        expected_receipt = (
            boundary["first_runtime_receipt_id"]
            if first
            else boundary["last_runtime_receipt_id"]
        )
        expected_state = (
            boundary["initial_state_id"]
            if first
            else boundary["final_state_id"]
        )
        actual_state = (
            runtime_record["prior_state_id"]
            if first
            else runtime_record["resulting_state_id"]
        )
        if (
            endpoint.receipt_id != expected_receipt
            or runtime_record["session_id"] != boundary["session_id"]
            or actual_state != expected_state
        ):
            raise ValueError("evidence summary runtime endpoint no longer matches")
        return endpoint

    @property
    def source_bound(self) -> bool:
        try:
            record = object.__getattribute__(self, "_record")
            seal = object.__getattribute__(self, "_native_seal")
            if type(record) is not CanonicalValue:
                return False
            CanonicalValue(record.text)
            from ._runtime import NativeEvidenceSummarySeal

            if type(seal) is not NativeEvidenceSummarySeal or not bool(
                seal.source_bound() and seal.validates(record.text)
            ):
                return False
            boundary = record.to_value()["runtime_boundary"]
            if boundary is not None:
                self._runtime_endpoint(first=True)
                self._runtime_endpoint(first=False)
        except (AttributeError, TypeError, ValueError):
            return False
        return True

    @property
    def verification_scope(self) -> str:
        return (
            "live_rust_reducer_ingestion_path"
            if self.source_bound
            else "structural_schema_and_identity_only"
        )

    @property
    def summary_id(self) -> str:
        return self._validated_value()["summary_id"]

    @property
    def aggregate_input_identity(self) -> str:
        return self._validated_value()["aggregate_identities"]["inputs"]

    @property
    def aggregate_admission_identity(self) -> str:
        return self._validated_value()["aggregate_identities"]["admissions"]

    @property
    def aggregate_result_identity(self) -> str:
        return self._validated_value()["aggregate_identities"]["results"]

    @property
    def aggregate_receipt_identity(self) -> str:
        return self._validated_value()["aggregate_identities"]["receipts"]

    @property
    def case_counts(self) -> EvidenceCaseCounts:
        return EvidenceCaseCounts.from_record(self._validated_value()["case_counts"])

    @property
    def counter_totals(self) -> EvidenceCounters:
        return EvidenceCounters.from_record(self._validated_value()["counter_totals"])

    @property
    def case_record_count(self) -> int:
        return self._validated_value()["item_counts"]["case_records"]

    @property
    def child_receipt_count(self) -> int:
        return self._validated_value()["item_counts"]["child_receipts"]

    @property
    def authorization_manifest_identity(self) -> str:
        return self._validated_value()["authorization_manifest"]["manifest_id"]

    @property
    def authorization_manifest_count(self) -> int:
        return self._validated_value()["authorization_manifest"]["count"]

    @property
    def first_runtime_receipt(self) -> Any | None:
        return self._runtime_endpoint(first=True)

    @property
    def last_runtime_receipt(self) -> Any | None:
        return self._runtime_endpoint(first=False)

    @property
    def first_runtime_receipt_id(self) -> str | None:
        boundary = self._validated_value()["runtime_boundary"]
        return None if boundary is None else boundary[
            "first_runtime_receipt_id"
        ]

    @property
    def last_runtime_receipt_id(self) -> str | None:
        boundary = self._validated_value()["runtime_boundary"]
        return None if boundary is None else boundary[
            "last_runtime_receipt_id"
        ]

    @property
    def runtime_session_id(self) -> str | None:
        boundary = self._validated_value()["runtime_boundary"]
        return None if boundary is None else boundary["session_id"]

    @property
    def initial_runtime_state_id(self) -> str | None:
        boundary = self._validated_value()["runtime_boundary"]
        return None if boundary is None else boundary[
            "initial_state_id"
        ]

    @property
    def final_runtime_state_id(self) -> str | None:
        boundary = self._validated_value()["runtime_boundary"]
        return None if boundary is None else boundary["final_state_id"]

    @property
    def task_identity(self) -> str:
        return self._validated_value()["bound_identities"]["task"]

    @property
    def governance_identity(self) -> str:
        return self._validated_value()["bound_identities"]["governance"]

    @property
    def orchestration_identity(self) -> str:
        return self._validated_value()["bound_identities"]["orchestration"]

    def canonical_record(self) -> dict[str, Any]:
        return self._validated_value()

    @property
    def canonical_text(self) -> str:
        self._validated_value()
        return self._record.text


class CompactEvidenceReceipt:
    """Structurally verified compact receipt with explicit source provenance.

    Parsing a self-consistent record proves schema and SHA-256 consistency only.
    ``source_bound`` is true solely for receipts returned by a live opaque Rust
    accumulator.  This is deterministic path binding, not producer
    authentication or proof of external truth.
    """

    __slots__ = (
        "_aggregates",
        "_authorization_manifest_count",
        "_authorization_manifest_identity",
        "_bound",
        "_case_counts",
        "_case_record_count",
        "_child_receipt_count",
        "_counters",
        "_native_seal",
        "_record",
        "_runtime_boundary",
    )

    def __init_subclass__(cls, **kwargs: Any) -> None:
        raise TypeError("CompactEvidenceReceipt cannot be subclassed")

    def __setattr__(self, name: str, value: Any) -> None:
        if hasattr(self, name):
            raise AttributeError("CompactEvidenceReceipt is immutable")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        raise AttributeError("CompactEvidenceReceipt is immutable")

    def __init__(
        self,
        canonical_text: str,
        *,
        required_profile: str = EVIDENCE_PROFILE,
        _native_seal: Any | None = None,
    ) -> None:
        canonical = CanonicalValue(canonical_text)
        if _native_seal is not None:
            from ._runtime import NativeEvidenceReceiptSeal

            if type(_native_seal) is not NativeEvidenceReceiptSeal:
                raise TypeError("compact evidence requires a native receipt seal")
            if not bool(_native_seal.validates(canonical.text)):
                raise ValueError("native evidence receipt seal does not match its record")
        if len(canonical.text.encode("utf-8")) > MAX_COMPACT_EVIDENCE_BYTES:
            raise ValueError("compact evidence exceeds its fixed byte ceiling")
        record = _exact_mapping("compact evidence receipt", canonical.to_value(), _RECEIPT_FIELDS)
        if required_profile != EVIDENCE_PROFILE:
            raise ValueError("unsupported required evidence sufficiency profile")
        if record["protocol_version"] != EVIDENCE_PROTOCOL_VERSION:
            raise ValueError("compact evidence protocol version mismatch")
        if record["evidence_profile"] != required_profile:
            raise ValueError("compact evidence sufficiency profile mismatch")
        receipt_id = record.pop("receipt_id")
        require_fingerprint("compact evidence receipt id", receipt_id)
        if domain_fingerprint(EVIDENCE_RECEIPT_DOMAIN, record) != receipt_id:
            raise ValueError("compact evidence receipt identity does not match its record")
        record["receipt_id"] = receipt_id

        aggregates = _validate_aggregate_identities(record["aggregate_identities"])
        bound = _exact_mapping(
            "compact evidence bound identities",
            record["bound_identities"],
            {"execution", "governance", "orchestration", "task"},
        )
        for name, identity in bound.items():
            require_fingerprint(f"compact evidence {name} identity", identity)
        authorization_count, authorization_identity = (
            _validate_authorization_manifest_record(record["authorization_manifest"])
        )
        cases = EvidenceCaseCounts.from_record(record["case_counts"])
        counters = EvidenceCounters.from_record(record["counter_totals"])
        case_records, child_receipts = _validate_item_counts(record["item_counts"], cases)
        runtime_boundary = _validate_runtime_boundary(record["runtime_boundary"])
        if runtime_boundary is not None and (
            child_receipts != 0 or case_records != cases.total
        ):
            raise ValueError("runtime boundary requires a direct-case-only evidence stream")
        limits = _exact_mapping(
            "compact evidence limits", record["limits"], {"max_cases", "max_failure_details"}
        )
        max_cases = _bounded_positive("max_cases", limits["max_cases"], MAX_EVIDENCE_CASES)
        max_details = _bounded_positive(
            "max_failure_details",
            limits["max_failure_details"],
            MAX_EVIDENCE_FAILURE_DETAILS,
        )
        if cases.total > max_cases:
            raise ValueError("compact evidence case count exceeds its declared bound")
        failure = _exact_mapping(
            "compact evidence failure summary",
            record["failure_summary"],
            {"count", "details_available", "details_truncated", "first_index"},
        )
        count = _u64("failure count", failure["count"])
        available = _u64("available failure detail count", failure["details_available"])
        if type(failure["details_truncated"]) is not bool:
            raise ValueError("failure detail truncation flag must be an exact boolean")
        if count != cases.failure_count or available != min(count, max_details):
            raise ValueError("compact evidence failure summary is inconsistent")
        if failure["details_truncated"] != (available < count):
            raise ValueError("compact evidence failure truncation flag is inconsistent")
        if count == 0:
            if failure["first_index"] is not None:
                raise ValueError("failure-free evidence cannot have a first failure")
        else:
            first = _u64("first failure index", failure["first_index"])
            if first >= cases.total:
                raise ValueError("first failure index is outside the represented cases")
        expected_status = (
            "complete_no_failures" if count == 0 else "complete_with_failures"
        )
        if record["status"] != expected_status:
            raise ValueError("compact evidence status is inconsistent")
        if count == 0 and counters.has_correctness_mismatch:
            raise ValueError("failure-free evidence cannot report a correctness mismatch")

        self._record = CanonicalValue.from_value(record)
        self._aggregates = aggregates
        self._authorization_manifest_count = authorization_count
        self._authorization_manifest_identity = authorization_identity
        self._bound = bound
        self._case_counts = cases
        self._counters = counters
        self._case_record_count = case_records
        self._child_receipt_count = child_receipts
        self._runtime_boundary = runtime_boundary
        self._native_seal = _native_seal

    def _validated_value(self) -> dict[str, Any]:
        record = object.__getattribute__(self, "_record")
        seal = object.__getattribute__(self, "_native_seal")
        if type(record) is not CanonicalValue:
            raise ValueError("compact evidence canonical record is not trusted")
        CanonicalValue(record.text)
        if seal is not None:
            from ._runtime import NativeEvidenceReceiptSeal

            if type(seal) is not NativeEvidenceReceiptSeal:
                raise ValueError("compact evidence native source seal is not trusted")
            if not bool(seal.validates(record.text)):
                raise ValueError(
                    "native evidence receipt seal no longer matches its record"
                )
        return record.to_value()

    @classmethod
    def from_json(
        cls,
        canonical_text: str,
        *,
        required_profile: str = EVIDENCE_PROFILE,
    ) -> CompactEvidenceReceipt:
        return cls(canonical_text, required_profile=required_profile)

    @classmethod
    def from_record(
        cls,
        record: Mapping[str, Any],
        *,
        required_profile: str = EVIDENCE_PROFILE,
    ) -> CompactEvidenceReceipt:
        return cls(
            CanonicalValue.from_value(record).text,
            required_profile=required_profile,
        )

    @property
    def receipt_id(self) -> str:
        return self._validated_value()["receipt_id"]

    @property
    def status(self) -> str:
        return self._validated_value()["status"]

    @property
    def evidence_profile(self) -> str:
        return EVIDENCE_PROFILE

    @property
    def verification_scope(self) -> str:
        return (
            "live_rust_reducer_ingestion_path"
            if self.source_bound
            else "structural_schema_and_identity_only"
        )

    @property
    def source_bound(self) -> bool:
        try:
            record = object.__getattribute__(self, "_record")
            seal = object.__getattribute__(self, "_native_seal")
            if type(record) is not CanonicalValue or seal is None:
                return False
            CanonicalValue(record.text)
            from ._runtime import NativeEvidenceReceiptSeal

            return type(seal) is NativeEvidenceReceiptSeal and bool(
                seal.source_bound() and seal.validates(record.text)
            )
        except (AttributeError, TypeError, ValueError):
            return False

    def _native_source_seal(self) -> Any:
        if not self.source_bound:
            raise ValueError("compact evidence has structural validation only")
        return self._native_seal

    @property
    def aggregate_input_identity(self) -> str:
        return self._validated_value()["aggregate_identities"]["inputs"]

    @property
    def aggregate_admission_identity(self) -> str:
        return self._validated_value()["aggregate_identities"]["admissions"]

    @property
    def aggregate_result_identity(self) -> str:
        return self._validated_value()["aggregate_identities"]["results"]

    @property
    def aggregate_receipt_identity(self) -> str:
        return self._validated_value()["aggregate_identities"]["receipts"]

    @property
    def task_identity(self) -> str:
        return self._validated_value()["bound_identities"]["task"]

    @property
    def governance_identity(self) -> str:
        return self._validated_value()["bound_identities"]["governance"]

    @property
    def orchestration_identity(self) -> str:
        return self._validated_value()["bound_identities"]["orchestration"]

    @property
    def execution_identity(self) -> str:
        return self._validated_value()["bound_identities"]["execution"]

    @property
    def case_counts(self) -> EvidenceCaseCounts:
        return EvidenceCaseCounts.from_record(self._validated_value()["case_counts"])

    @property
    def counter_totals(self) -> EvidenceCounters:
        return EvidenceCounters.from_record(self._validated_value()["counter_totals"])

    @property
    def failure_count(self) -> int:
        return self.case_counts.failure_count

    @property
    def case_record_count(self) -> int:
        return self._validated_value()["item_counts"]["case_records"]

    @property
    def child_receipt_count(self) -> int:
        return self._validated_value()["item_counts"]["child_receipts"]

    @property
    def authorization_manifest_identity(self) -> str:
        return self._validated_value()["authorization_manifest"]["manifest_id"]

    @property
    def authorization_manifest_count(self) -> int:
        return self._validated_value()["authorization_manifest"]["count"]

    @property
    def first_runtime_receipt_id(self) -> str | None:
        boundary = self._validated_value()["runtime_boundary"]
        return None if boundary is None else boundary[
            "first_runtime_receipt_id"
        ]

    @property
    def last_runtime_receipt_id(self) -> str | None:
        boundary = self._validated_value()["runtime_boundary"]
        return None if boundary is None else boundary[
            "last_runtime_receipt_id"
        ]

    @property
    def runtime_session_id(self) -> str | None:
        boundary = self._validated_value()["runtime_boundary"]
        return None if boundary is None else boundary["session_id"]

    @property
    def initial_runtime_state_id(self) -> str | None:
        boundary = self._validated_value()["runtime_boundary"]
        return None if boundary is None else boundary[
            "initial_state_id"
        ]

    @property
    def final_runtime_state_id(self) -> str | None:
        boundary = self._validated_value()["runtime_boundary"]
        return None if boundary is None else boundary["final_state_id"]

    @property
    def canonical_text(self) -> str:
        self._validated_value()
        return self._record.text

    def require_sufficient_for(self, claims: set[str] | frozenset[str]) -> None:
        if not isinstance(claims, (set, frozenset)) or not all(
            isinstance(claim, str) for claim in claims
        ):
            raise TypeError("evidence claims must be a set of strings")
        unsupported = claims - EVIDENCE_PROFILE_CLAIMS
        if unsupported:
            raise ValueError(
                "compact evidence profile is insufficient for: "
                + ", ".join(sorted(unsupported))
            )

    def canonical_record(self) -> dict[str, Any]:
        return self._validated_value()


class FailureExpansion:
    """Bounded failure-only detail bound to one compact parent receipt."""

    __slots__ = ("_record",)

    def __init__(self, canonical_text: str, *, expected_parent_id: str) -> None:
        require_fingerprint("expected compact evidence parent", expected_parent_id)
        canonical = CanonicalValue(canonical_text)
        if len(canonical.text.encode("utf-8")) > MAX_EVIDENCE_EXPANSION_BYTES:
            raise ValueError("evidence expansion exceeds its hard byte limit")
        record = _exact_mapping(
            "evidence expansion",
            canonical.to_value(),
            {
                "details",
                "evidence_receipt_id",
                "expansion_id",
                "protocol_version",
                "start_case_index",
            },
        )
        if record["protocol_version"] != EVIDENCE_PROTOCOL_VERSION:
            raise ValueError("evidence expansion protocol version mismatch")
        if record["evidence_receipt_id"] != expected_parent_id:
            raise ValueError("evidence expansion is not bound to its expected parent")
        expansion_id = record.pop("expansion_id")
        require_fingerprint("evidence expansion id", expansion_id)
        if domain_fingerprint(EVIDENCE_EXPANSION_DOMAIN, record) != expansion_id:
            raise ValueError("evidence expansion identity does not match its record")
        record["expansion_id"] = expansion_id
        _u64("evidence expansion start index", record["start_case_index"])
        if type(record["details"]) is not list:
            raise ValueError("evidence expansion details must be a list")
        if len(record["details"]) > MAX_EVIDENCE_FAILURE_DETAILS:
            raise ValueError("evidence expansion detail count exceeds its hard bound")
        prior_index: int | None = None
        for detail in record["details"]:
            item = _exact_mapping(
                "evidence failure detail",
                detail,
                {"case_id", "case_index", "detail", "reason_code", "receipt_id", "status"},
            )
            require_fingerprint("failure detail case id", item["case_id"])
            require_fingerprint("failure detail receipt id", item["receipt_id"])
            case_index = _u64("failure detail case index", item["case_index"])
            if case_index < record["start_case_index"] or (
                prior_index is not None and case_index <= prior_index
            ):
                raise ValueError("failure expansion indexes are not a valid ordered selection")
            prior_index = case_index
            if item["status"] not in {"failed", "rejected"}:
                raise ValueError("success traces cannot enter failure expansion")
            if (
                not isinstance(item["reason_code"], str)
                or not item["reason_code"]
            ):
                raise ValueError("failure detail reason code is invalid")
            bounded_utf8_length(
                "failure detail reason code", item["reason_code"], limit=256
            )
            if (
                len(CanonicalValue.from_value(item["detail"]).text.encode("utf-8"))
                > MAX_EVIDENCE_FAILURE_DETAIL_BYTES
            ):
                raise ValueError("failure detail exceeds its hard byte limit")
        self._record = CanonicalValue.from_value(record)

    @property
    def details(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._record.to_value()["details"])

    @property
    def evidence_receipt_id(self) -> str:
        return self._record.to_value()["evidence_receipt_id"]

    def canonical_record(self) -> dict[str, Any]:
        return self._record.to_value()


@dataclass(frozen=True, slots=True)
class FastRegressionObservation:
    """Optional non-cryptographic comparison hint with no correctness authority."""

    algorithm: str
    correctness_authority: bool
    protocol_version: str
    value: str

    @classmethod
    def from_json(cls, canonical_text: str) -> FastRegressionObservation:
        record = _exact_mapping(
            "fast regression observation",
            CanonicalValue(canonical_text).to_value(),
            {"algorithm", "correctness_authority", "protocol_version", "value"},
        )
        if record["algorithm"] != FAST_FOLD_ALGORITHM:
            raise ValueError("fast regression algorithm is unsupported")
        if record["correctness_authority"] is not False:
            raise ValueError("fast regression fold cannot have correctness authority")
        if record["protocol_version"] != EVIDENCE_PROTOCOL_VERSION:
            raise ValueError("fast regression protocol version mismatch")
        if not isinstance(record["value"], str) or not _HEX16.fullmatch(record["value"]):
            raise ValueError("fast regression fold must be 16 lowercase hex characters")
        return cls(**record)


class EvidenceAccumulator:
    """Controlled Python facade over Rust-owned streaming evidence state."""

    __slots__ = (
        "__final",
        "__first_runtime_receipt",
        "__last_runtime_receipt",
        "__last_runtime_state_id",
        "__native",
        "__governance_identity",
        "__orchestration_identity",
        "__runtime_session_id",
        "__summary",
        "__task_identity",
        "_limits",
    )

    def __init__(
        self,
        task_identity: str,
        governance_identity: str,
        orchestration_identity: str,
        *,
        authorization_manifest: Any = (),
        limits: EvidenceLimits | None = None,
        max_cases: int | None = None,
        max_failure_details: int | None = None,
        enable_fast_fold: bool = False,
    ) -> None:
        for name, identity in (
            ("task", task_identity),
            ("governance", governance_identity),
            ("orchestration", orchestration_identity),
        ):
            require_fingerprint(f"evidence {name} identity", identity)
        if type(enable_fast_fold) is not bool:
            raise ValueError("enable_fast_fold must be an exact boolean")
        if limits is not None and not isinstance(limits, EvidenceLimits):
            raise TypeError("limits must be EvidenceLimits")
        if limits is not None and (
            max_cases is not None or max_failure_details is not None
        ):
            raise ValueError("limits cannot be combined with direct limit arguments")
        if limits is None:
            active_limits = EvidenceLimits(
                100_000 if max_cases is None else max_cases,
                8 if max_failure_details is None else max_failure_details,
            )
        else:
            active_limits = limits
        normalized_manifest = _normalize_authorization_manifest(
            authorization_manifest
        )
        canonical_manifest = CanonicalValue.from_value(
            list(normalized_manifest)
        )
        from ._runtime import NativeEvidenceAccumulator

        self.__native = NativeEvidenceAccumulator(
            task_identity,
            governance_identity,
            orchestration_identity,
            canonical_manifest.text,
            active_limits.max_cases,
            active_limits.max_failure_details,
            enable_fast_fold,
        )
        self.__summary: EvidenceAggregateSummary | None = None
        self.__final: CompactEvidenceReceipt | None = None
        self.__first_runtime_receipt: Any | None = None
        self.__last_runtime_receipt: Any | None = None
        self.__last_runtime_state_id: str | None = None
        self.__runtime_session_id: str | None = None
        self.__task_identity = task_identity
        self.__governance_identity = governance_identity
        self.__orchestration_identity = orchestration_identity
        self._limits = active_limits

    def record_case(
        self,
        *,
        case_id: str,
        admission_identity: str | None = None,
        input_identity: str,
        result_identity: str,
        receipt_identity: str,
        status: str,
        counters: EvidenceCounters | None = None,
        failure_reason: str | None = None,
        failure_detail: Any = None,
    ) -> None:
        active_admission_identity = (
            case_id if admission_identity is None else admission_identity
        )
        for name, identity in (
            ("admission", active_admission_identity),
            ("case", case_id),
            ("input", input_identity),
            ("result", result_identity),
            ("case receipt", receipt_identity),
        ):
            require_fingerprint(f"evidence {name} identity", identity)
        if status not in {"passed", "failed", "rejected"}:
            raise ValueError("evidence case status is unsupported")
        active_counters = EvidenceCounters() if counters is None else counters
        if not isinstance(active_counters, EvidenceCounters):
            raise TypeError("counters must be EvidenceCounters")
        if status == "passed":
            if failure_reason is not None or failure_detail is not None:
                raise ValueError("passing evidence cannot carry failure detail")
            if active_counters.has_correctness_mismatch:
                raise ValueError("passing evidence cannot report a correctness mismatch")
            failure = None
        else:
            if (
                not isinstance(failure_reason, str)
                or not failure_reason
            ):
                raise ValueError("failed evidence requires a bounded reason code")
            bounded_utf8_length(
                "evidence failure reason", failure_reason, limit=256
            )
            failure = {"detail": failure_detail, "reason_code": failure_reason}
        item = CanonicalValue.from_value(
            {
                "admission_id": active_admission_identity,
                "case_id": case_id,
                "counters": active_counters.canonical_record(),
                "failure": failure,
                "input_id": input_identity,
                "item_type": "case",
                "protocol_version": EVIDENCE_PROTOCOL_VERSION,
                "receipt_id": receipt_identity,
                "result_id": result_identity,
                "runtime_source": None,
                "status": status,
            }
        )
        self.__native.ingest_structural(item.text)

    def record_runtime_case(self, runtime_receipt: Any) -> None:
        """Admit exact deltas from a sealed v0.3 runtime receipt.

        ``record_retry`` carries only its governed admission identity in the
        v0.3 protocol.  It may extend a source-bound stream but cannot, by
        itself, satisfy authorization-manifest execution coverage.
        """

        from .runtime import RuntimeReceipt

        if type(runtime_receipt) is not RuntimeReceipt:
            raise TypeError("runtime_receipt must be RuntimeReceipt")
        if not runtime_receipt.source_bound:
            raise ValueError("runtime evidence requires a native-bound runtime receipt")
        record = runtime_receipt.canonical_record()
        if record["command_type"] not in {"execute_read", "record_retry"}:
            raise ValueError("runtime evidence command type is unsupported")
        command_id = record["command_id"]
        admission_id = record["admission_id"]
        result_id = record["transition_id"] or record["resulting_state_id"]
        for name, identity in (
            ("runtime admission", admission_id),
            ("runtime command", command_id),
            ("runtime result", result_id),
            ("runtime receipt", runtime_receipt.receipt_id),
            ("runtime prior state", record["prior_state_id"]),
            ("runtime resulting state", record["resulting_state_id"]),
            ("runtime session", record["session_id"]),
        ):
            require_fingerprint(f"evidence {name} identity", identity)
        delta = record["budget_delta"]
        counters = EvidenceCounters(
            actual_executions=delta["executions"],
            cache_hits=delta["cache_hits"],
            requests=delta["requests"],
            retries=delta["retries"],
        )
        rejected = runtime_receipt.status == "rejected"
        rejection = record["rejection"]
        failure_reason = None if not rejected else rejection["reason_code"]
        failure_detail = None if not rejected else {"runtime_rejection": rejection}
        item = CanonicalValue.from_value(
            {
                "admission_id": admission_id,
                "case_id": command_id,
                "counters": counters.canonical_record(),
                "failure": None
                if not rejected
                else {"detail": failure_detail, "reason_code": failure_reason},
                "input_id": command_id,
                "item_type": "case",
                "protocol_version": EVIDENCE_PROTOCOL_VERSION,
                "receipt_id": runtime_receipt.receipt_id,
                "result_id": result_id,
                "runtime_source": {
                    "prior_state_id": record["prior_state_id"],
                    "resulting_state_id": record["resulting_state_id"],
                    "runtime_receipt_id": runtime_receipt.receipt_id,
                    "session_id": record["session_id"],
                },
                "status": "rejected" if rejected else "passed",
            }
        )
        if self.__runtime_session_id is not None:
            if record["session_id"] != self.__runtime_session_id:
                raise ValueError("runtime evidence cannot cross session identity")
            if record["prior_state_id"] != self.__last_runtime_state_id:
                raise ValueError("runtime evidence receipt continuity is invalid")
        self.__native.ingest_runtime(
            item.text, runtime_receipt._native_source_seal()
        )
        if self.__first_runtime_receipt is None:
            self.__first_runtime_receipt = runtime_receipt
            self.__runtime_session_id = record["session_id"]
        self.__last_runtime_receipt = runtime_receipt
        self.__last_runtime_state_id = record["resulting_state_id"]

    def ingest_child(self, receipt: CompactEvidenceReceipt) -> None:
        if type(receipt) is not CompactEvidenceReceipt:
            raise TypeError("child receipt must be CompactEvidenceReceipt")
        if not receipt.source_bound:
            raise ValueError("structural-only child evidence cannot bind a live parent")
        if (
            receipt.task_identity != self.__task_identity
            or receipt.governance_identity != self.__governance_identity
            or receipt.orchestration_identity != self.__orchestration_identity
        ):
            raise ValueError("child evidence authority context does not match its parent")
        item = CanonicalValue.from_value(
            {
                "item_type": "child_receipt",
                "protocol_version": EVIDENCE_PROTOCOL_VERSION,
                "receipt": receipt.canonical_record(),
            }
        )
        self.__native.ingest_child(item.text, receipt._native_source_seal())

    def aggregate_summary(self) -> EvidenceAggregateSummary:
        if self.__summary is None:
            canonical, native_seal = self.__native.aggregate_summary()
            source_bound = bool(native_seal.source_bound())
            self.__summary = EvidenceAggregateSummary(
                canonical,
                _native_seal=native_seal,
                _first_runtime_receipt=(
                    self.__first_runtime_receipt
                    if source_bound
                    else None
                ),
                _last_runtime_receipt=(
                    self.__last_runtime_receipt
                    if source_bound
                    else None
                ),
            )
        return self.__summary

    def finalize(self, execution_identity: str) -> CompactEvidenceReceipt:
        require_fingerprint("evidence execution identity", execution_identity)
        if self.__summary is None:
            raise ValueError(
                "aggregate_summary must seal evidence before execution identity is bound"
            )
        if self.__final is None:
            canonical, native_seal = self.__native.finalize(execution_identity)
            self.__final = CompactEvidenceReceipt(
                canonical,
                _native_seal=native_seal,
            )
        elif self.__final.execution_identity != execution_identity:
            raise ValueError("compact evidence is already bound to another execution identity")
        return self.__final

    def expand(
        self,
        *,
        evidence_receipt_id: str,
        start_case_index: int = 0,
        max_details: int = 1,
    ) -> FailureExpansion:
        require_fingerprint("evidence expansion parent", evidence_receipt_id)
        _u64("evidence expansion start index", start_case_index)
        _bounded_positive(
            "evidence expansion max_details",
            max_details,
            self._limits.max_failure_details,
        )
        request = CanonicalValue.from_value(
            {
                "evidence_receipt_id": evidence_receipt_id,
                "max_details": max_details,
                "protocol_version": EVIDENCE_PROTOCOL_VERSION,
                "start_case_index": start_case_index,
            }
        )
        return FailureExpansion(
            self.__native.expand(request.text),
            expected_parent_id=evidence_receipt_id,
        )

    def fast_regression_observation(self) -> FastRegressionObservation | None:
        observation = self.__native.fast_regression_observation()
        return (
            None
            if observation is None
            else FastRegressionObservation.from_json(observation)
        )


__all__ = [
    "EVIDENCE_PROFILE",
    "EVIDENCE_PROFILE_CLAIMS",
    "EVIDENCE_PROTOCOL_VERSION",
    "MAX_COMPACT_EVIDENCE_BYTES",
    "MAX_EVIDENCE_AUTHORIZATIONS",
    "MAX_EVIDENCE_CASES",
    "MAX_EVIDENCE_FAILURE_DETAILS",
    "CompactEvidenceReceipt",
    "EvidenceAccumulator",
    "EvidenceAggregateSummary",
    "EvidenceCaseCounts",
    "EvidenceCounters",
    "EvidenceLimits",
    "FailureExpansion",
    "FastRegressionObservation",
    "aggregate_admission_stream",
    "authorization_manifest_identity",
]
