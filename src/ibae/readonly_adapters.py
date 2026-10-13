"""Bounded v0.6C observation contracts for selected, read-only sources.

Request plans and observation receipts are inert data, not admissions, native
evidence, source authentication, or proof of live verification. Live GETs are
non-cacheable captures, including mutable repository/branch/PR/CI state. A
selection identity names targets; it is never a content snapshot. Only separately
admitted immutable captured data can enter the legacy native cacheable-read path.
Public GitHub transport is separately activation-gated; authenticated GitHub and
ChatGPT/Work/Codex session continuation are not implemented here.

Routes and JSON fields follow the official GitHub REST documentation:
https://docs.github.com/en/rest/repos/repos#get-a-repository
https://docs.github.com/en/rest/branches/branches#get-a-branch
https://docs.github.com/en/rest/commits/commits#get-a-commit
https://docs.github.com/en/rest/pulls/pulls#get-a-pull-request
https://docs.github.com/en/rest/checks/runs#list-check-runs-for-a-git-reference
https://docs.github.com/en/rest/commits/statuses#get-the-combined-status-for-a-specific-reference
"""

from __future__ import annotations

import json
import http.client
import re
import ssl
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import quote

from ._records import bounded_utf8_length
from .canonical import canonical_json, canonical_tool_key, domain_fingerprint
from .synthetic_protocol import (
    AdapterInterface, AdapterResult, FakeFilesystem, NormalizedProposal,
    ProposalKind, SyntheticReadFixture, _copy_json, _exact, _fields, _fingerprint,
)

GITHUB_SELECTION_VERSION: Final = "IBAE-GITHUB-READ-SELECTION-V1"
GITHUB_REQUEST_VERSION: Final = "IBAE-GITHUB-READ-REQUEST-V1"
EXTERNAL_OBSERVATION_VERSION: Final = "IBAE-EXTERNAL-READ-OBSERVATION-V1"
GITHUB_API_VERSION: Final = "2026-03-10"
MAX_GITHUB_RESPONSE_BYTES: Final = 262_144
MAX_GITHUB_PAGE_ITEMS: Final = 100
GITHUB_TIMEOUT_MS: Final = 10_000
MAX_OBSERVATION_BYTES: Final = 262_144
GITHUB_READ_TOOLS: Final = (
    "github.repository", "github.branch", "github.commit",
    "github.pull_request", "github.check_runs", "github.commit_status",
)


def _source_semantics(tool_name: str) -> dict:
    return {"resource_mutability": "immutable_commit_content" if tool_name == "github.commit" else "mutable_remote_state",
        "selection_is_content_snapshot": False, "network_operation_cacheable": False,
        "current_remote_state_verified": False,
        "freshness_scope": "returned_response_only",
        "native_consumption": "separately_admitted_content_bound_snapshot_only"}


def _text(label: str, value: Any, limit: int = 256) -> str:
    _exact(label, value, str)
    bounded_utf8_length(label, value, limit=limit)
    if not value or value != value.strip() or any(ord(c) < 32 for c in value):
        raise ValueError(f"{label} must be nonempty bounded printable text")
    return value


def _integer(label: str, value: Any, *, minimum: int = 0, maximum: int = (1 << 63) - 1) -> int:
    _exact(label, value, int)
    if not minimum <= value <= maximum:
        raise ValueError(f"{label} is outside the supported bound")
    return value


def _sha(value: Any) -> str:
    _exact("commit SHA", value, str)
    if re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise ValueError("commit SHA requires forty lowercase hexadecimal characters")
    return value


def _message(value: Any) -> str:
    _exact("commit message", value, str)
    bounded_utf8_length("commit message", value, limit=4_096)
    return value


def _branch(value: Any) -> str:
    _text("branch", value)
    if (re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9._/-]*", value) is None
            or ".." in value or "//" in value or value.endswith(("/", "."))
            or any(part.startswith(".") or part.endswith(".lock") for part in value.split("/"))):
        raise ValueError("branch is outside the selected literal branch profile")
    return value


def _selection(record: Any) -> dict:
    value = _copy_json(record)
    _fields(value, {"protocol_version", "owner", "repository", "branch", "commit_sha",
                    "pull_number", "control_authority"}, "GitHub selection")
    if value["protocol_version"] != GITHUB_SELECTION_VERSION or value["control_authority"] is not False:
        raise ValueError("invalid GitHub selection version or authority")
    owner = _text("owner", value["owner"], 39)
    repository = _text("repository", value["repository"], 100)
    if re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", owner) is None:
        raise ValueError("owner is outside the GitHub account-name profile")
    if (re.fullmatch(r"[A-Za-z0-9_.-]+", repository) is None or repository in {".", ".."}
            or repository.endswith(".git")):
        raise ValueError("repository must be a literal repository name without a .git suffix")
    if value["branch"] is not None:
        _branch(value["branch"])
    if value["commit_sha"] is not None:
        _sha(value["commit_sha"])
    if value["pull_number"] is not None:
        _integer("pull number", value["pull_number"], minimum=1, maximum=(1 << 31) - 1)
    return value


@dataclass(frozen=True, slots=True, init=False)
class GitHubReadSelection:
    """Literal selected targets. Selection is configuration, never permission."""

    _text: str

    def __init__(self, owner: str, repository: str, branch: str | None = None,
                 commit_sha: str | None = None, pull_number: int | None = None) -> None:
        value = _selection({"protocol_version": GITHUB_SELECTION_VERSION, "owner": owner,
            "repository": repository, "branch": branch, "commit_sha": commit_sha,
            "pull_number": pull_number, "control_authority": False})
        object.__setattr__(self, "_text", canonical_json(value))

    @classmethod
    def from_record(cls, record: dict) -> GitHubReadSelection:
        value = _selection(record)
        return cls(value["owner"], value["repository"], value["branch"],
                   value["commit_sha"], value["pull_number"])

    def canonical_record(self) -> dict:
        _exact("selection text", self._text, str)
        bounded_utf8_length("selection text", self._text, limit=4_096)
        return _selection(json.loads(self._text))

    @property
    def selection_id(self) -> str:
        return domain_fingerprint("ibae.github-read-selection-id.v1", self.canonical_record())

    def arguments_for(self, tool_name: str) -> dict:
        _exact("GitHub tool name", tool_name, str)
        if tool_name not in GITHUB_READ_TOOLS:
            raise ValueError("unsupported GitHub read tool")
        value = self.canonical_record()
        result = {"owner": value["owner"], "repository": value["repository"]}
        key = {"github.branch": "branch", "github.commit": "commit_sha",
               "github.pull_request": "pull_number", "github.check_runs": "commit_sha",
               "github.commit_status": "commit_sha"}.get(tool_name)
        if key is not None:
            if value[key] is None:
                raise ValueError("read target was not selected")
            result[key] = value[key]
        return result


def _request(proposal: NormalizedProposal, selection: GitHubReadSelection, dependency: str) -> dict:
    _exact("read proposal", proposal, NormalizedProposal)
    _exact("GitHub selection", selection, GitHubReadSelection)
    _fingerprint("read dependency", dependency)
    record = proposal.canonical_record()
    if record["kind"] != ProposalKind.READ.value:
        raise ValueError("GitHub reads require the normalized read proposal contract")
    tool = record["payload"]["tool_name"]
    arguments = selection.arguments_for(tool)
    # JSON equality distinguishes integer, float and boolean inputs.
    if canonical_json(record["payload"]["arguments"]) != canonical_json(arguments):
        raise ValueError("read arguments do not exactly match the selected target")
    path = "/repos/" + quote(arguments["owner"], safe="") + "/" + quote(arguments["repository"], safe="")
    if tool == "github.branch":
        path += "/branches/" + quote(arguments["branch"], safe="")
    elif tool == "github.pull_request":
        path += "/pulls/" + str(arguments["pull_number"])
    elif tool in {"github.commit", "github.check_runs", "github.commit_status"}:
        path += "/commits/" + arguments["commit_sha"]
        if tool == "github.check_runs":
            path += "/check-runs?filter=latest&per_page=100&page=1"
        elif tool == "github.commit_status":
            path += "/status?per_page=100&page=1"
    return {"protocol_version": GITHUB_REQUEST_VERSION, "selection": selection.canonical_record(),
        "proposal": record, "dependency_fingerprint": dependency,
        "tool_key": canonical_tool_key(tool, arguments, dependency), "method": "GET",
        "url": "https://api.github.com" + path,
        "headers": {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": GITHUB_API_VERSION},
        "max_calls": 1, "max_response_bytes": MAX_GITHUB_RESPONSE_BYTES,
        "timeout_ms": GITHUB_TIMEOUT_MS, "follow_redirects": False,
        "automatic_retries": 0, "automatic_pagination": False,
        "authentication": "public_unauthenticated_only", "source_semantics": _source_semantics(tool),
        "control_authority": False}


def _request_record(record: Any) -> dict:
    value = _copy_json(record)
    _fields(value, {"protocol_version", "selection", "proposal", "dependency_fingerprint", "tool_key",
        "method", "url", "headers", "max_calls", "max_response_bytes", "timeout_ms", "follow_redirects",
        "automatic_retries", "automatic_pagination", "authentication", "source_semantics", "control_authority"}, "GitHub request")
    expected = _request(NormalizedProposal.from_record(value["proposal"]),
                        GitHubReadSelection.from_record(value["selection"]), value["dependency_fingerprint"])
    if canonical_json(value) != canonical_json(expected):
        raise ValueError("GitHub request does not match the complete canonical request plan")
    return expected


@dataclass(frozen=True, slots=True, init=False)
class GitHubRequestPlan:
    """One inert GET plan; creating or parsing it performs no network request."""

    _text: str

    def __init__(self, proposal: NormalizedProposal, selection: GitHubReadSelection,
                 dependency_fingerprint: str) -> None:
        value = _copy_json(_request(proposal, selection, dependency_fingerprint))
        object.__setattr__(self, "_text", canonical_json(value))

    @classmethod
    def from_proposal(cls, proposal: NormalizedProposal, selection: GitHubReadSelection,
                      dependency_fingerprint: str) -> GitHubRequestPlan:
        return cls(proposal, selection, dependency_fingerprint)

    @classmethod
    def from_record(cls, record: dict) -> GitHubRequestPlan:
        value = _request_record(record)
        return cls(NormalizedProposal.from_record(value["proposal"]),
                   GitHubReadSelection.from_record(value["selection"]), value["dependency_fingerprint"])

    def canonical_record(self) -> dict:
        _exact("request text", self._text, str)
        bounded_utf8_length("request text", self._text, limit=65_536)
        return _request_record(json.loads(self._text))

    @property
    def request_id(self) -> str:
        return domain_fingerprint("ibae.github-read-request-id.v1", self.canonical_record())


def _metadata(record: Any) -> dict:
    value = _copy_json(record, limit=2_048)
    _fields(value, {"request_id", "etag", "has_next_page"}, "GitHub source metadata")
    for key, pattern, limit in (("request_id", r"[A-Za-z0-9:-]+", 128),
                                ("etag", r'(?:W/)?"[A-Fa-f0-9]+"', 256)):
        if value[key] is not None:
            text = _text(key, value[key], limit)
            if re.fullmatch(pattern, text) is None:
                raise ValueError("source metadata is outside its closed field profile")
    _exact("pagination observation", value["has_next_page"], bool)
    return value


def _boolean(label: str, value: Any, *, nullable: bool = False) -> bool | None:
    if value is None and nullable:
        return None
    _exact(label, value, bool)
    return value


def _enum(label: str, value: Any, choices: set[str], *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    _exact(label, value, str)
    if value not in choices:
        raise ValueError(f"unsupported {label}")
    return value


def _object(label: str, value: Any) -> dict:
    _exact(label, value, dict)
    return value


def _normalize_response(request: dict, data: dict, metadata: dict) -> dict:
    """Keep a closed selected projection; never copy source text as authority."""
    arguments = request["proposal"]["payload"]["arguments"]
    tool = request["proposal"]["payload"]["tool_name"]
    full_name = arguments["owner"] + "/" + arguments["repository"]
    if tool == "github.repository":
        if _text("repository full name", data.get("full_name")) != full_name:
            raise ValueError("response repository does not match selection")
        return {"full_name": full_name, "default_branch": _branch(data.get("default_branch")),
                "private": _boolean("private", data.get("private")),
                "archived": _boolean("archived", data.get("archived"))}
    if tool == "github.branch":
        if _branch(data.get("name")) != arguments["branch"]:
            raise ValueError("response branch does not match selection")
        sha = _sha(_object("branch commit", data.get("commit")).get("sha"))
        expected = request["selection"]["commit_sha"]
        return {"name": arguments["branch"], "head_sha": sha,
                "matches_selected_commit": None if expected is None else sha == expected,
                "protected": _boolean("protected", data.get("protected"))}
    if tool == "github.commit":
        if _sha(data.get("sha")) != arguments["commit_sha"]:
            raise ValueError("response commit does not match selection")
        commit = _object("commit", data.get("commit"))
        return {"sha": arguments["commit_sha"],
                "tree_sha": _sha(_object("commit tree", commit.get("tree")).get("sha")),
                "message": _message(commit.get("message"))}
    if tool == "github.pull_request":
        number = _integer("pull number", data.get("number"), minimum=1, maximum=(1 << 31) - 1)
        base = _object("pull base", data.get("base"))
        if number != arguments["pull_number"] or _object("base repository", base.get("repo")).get("full_name") != full_name:
            raise ValueError("response pull request does not match selection")
        head = _object("pull head", data.get("head"))
        head_sha = _sha(head.get("sha"))
        selected = request["selection"]["commit_sha"]
        return {"number": number, "state": _enum("pull state", data.get("state"), {"open", "closed"}),
                "head_sha": head_sha, "base_sha": _sha(base.get("sha")),
                "matches_selected_commit": None if selected is None else head_sha == selected,
                "draft": _boolean("draft", data.get("draft")),
                "merged": _boolean("merged", data.get("merged")),
                "mergeable": _boolean("mergeable", data.get("mergeable"), nullable=True)}
    is_checks = tool == "github.check_runs"
    if not is_checks and _sha(data.get("sha")) != arguments["commit_sha"]:
        raise ValueError("response status commit does not match selection")
    items = data.get("check_runs" if is_checks else "statuses")
    _exact("CI records", items, list)
    if len(items) > MAX_GITHUB_PAGE_ITEMS:
        raise ValueError("CI response exceeds the one-page bound")
    total = _integer("CI total count", data.get("total_count"))
    if total < len(items):
        raise ValueError("CI total count is smaller than its returned page")
    output, identities = [], []
    for item in items:
        _object("CI item", item)
        identity = _integer("CI identity", item.get("id"), minimum=1)
        identities.append(identity)
        if is_checks:
            if _sha(item.get("head_sha")) != arguments["commit_sha"]:
                raise ValueError("check run does not match the selected commit")
            output.append({"id": identity, "name": _text("check name", item.get("name")),
                "head_sha": arguments["commit_sha"],
                "status": _enum("check status", item.get("status"), {"queued", "in_progress", "completed", "waiting", "requested", "pending"}),
                "conclusion": _enum("check conclusion", item.get("conclusion"),
                    {"success", "failure", "neutral", "cancelled", "skipped", "timed_out", "action_required", "stale", "startup_failure"}, nullable=True)})
        else:
            output.append({"id": identity, "context": _text("status context", item.get("context")),
                "state": _enum("commit status", item.get("state"), {"error", "failure", "pending", "success"})})
    if len(set(identities)) != len(identities):
        raise ValueError("duplicate CI observation identity")
    result = {"sha": arguments["commit_sha"], "total_count": total,
        "returned_count": len(output), "items": sorted(output, key=lambda item: item["id"]),
        "complete_page_set": total == len(output) and not metadata["has_next_page"],
        "coverage": "latest_check_runs" if is_checks else "combined_commit_statuses",
        "required_checks_verified": False}
    if not is_checks:
        result["reported_state"] = _enum("combined state", data.get("state"), {"failure", "pending", "success"})
    return result


def _json_body(body: bytes) -> dict:
    def pairs(values: list) -> dict:
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("duplicate JSON response field")
            result[key] = value
        return result

    def constant(_: str) -> None:
        raise ValueError("non-finite JSON response number")

    try:
        parsed = json.loads(body.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("invalid bounded GitHub JSON response") from exc
    value = _copy_json(parsed, limit=MAX_GITHUB_RESPONSE_BYTES, node_limit=16_384)
    return _object("GitHub response", value)


def _observation_record(record: Any) -> dict:
    value = _copy_json(record, limit=MAX_OBSERVATION_BYTES, node_limit=16_384)
    _fields(value, {"protocol_version", "request", "status_code", "status", "reason", "output",
        "source_metadata", "source_semantics", "control_authority", "native_evidence", "source_authentication"}, "external observation")
    if (value["protocol_version"] != EXTERNAL_OBSERVATION_VERSION or value["control_authority"] is not False
            or value["native_evidence"] is not False or value["source_authentication"] != "not_established"):
        raise ValueError("invalid external observation version or authority")
    request = _request_record(value["request"])
    if canonical_json(value["source_semantics"]) != canonical_json(request["source_semantics"]):
        raise ValueError("observation source semantics do not match the selected request")
    metadata = _metadata(value["source_metadata"])
    code = _integer("HTTP status", value["status_code"], minimum=100, maximum=599)
    reason = "response_observed" if code == 200 else "redirect_rejected" if 300 <= code < 400 else "http_unavailable"
    if value["status"] != ("observed" if code == 200 else "unavailable") or value["reason"] != reason:
        raise ValueError("observation classification does not match HTTP status")
    if code != 200 and value["output"] is not None:
        raise ValueError("unavailable observations cannot carry output")
    if code == 200:
        # Normalized output is checked independently of any raw response body.
        _validate_output(request, value["output"], metadata)
    return value


def _validate_output(request: dict, output: Any, metadata: dict) -> None:
    _exact("observation output", output, dict)
    tool = request["proposal"]["payload"]["tool_name"]
    args = request["proposal"]["payload"]["arguments"]
    if tool == "github.repository":
        raw = dict(output)
    elif tool == "github.branch":
        raw = {"name": output.get("name"), "commit": {"sha": output.get("head_sha")}, "protected": output.get("protected")}
    elif tool == "github.commit":
        raw = {"sha": output.get("sha"), "commit": {"tree": {"sha": output.get("tree_sha")}, "message": output.get("message")}}
    elif tool == "github.pull_request":
        raw = {"number": output.get("number"), "state": output.get("state"), "draft": output.get("draft"),
               "merged": output.get("merged"), "mergeable": output.get("mergeable"),
               "head": {"sha": output.get("head_sha")},
               "base": {"sha": output.get("base_sha"), "repo": {"full_name": args["owner"] + "/" + args["repository"]}}}
    else:
        raw = {"sha": output.get("sha"), "total_count": output.get("total_count"),
               "check_runs" if tool == "github.check_runs" else "statuses": output.get("items"),
               "state": output.get("reported_state")}
    normalized = _normalize_response(request, raw, metadata)
    if canonical_json(normalized) != canonical_json(output):
        raise ValueError("output does not match its complete normalized schema")


@dataclass(frozen=True, slots=True, init=False)
class ExternalObservationReceipt:
    """Reconstructible observation data. Its hashes do not prove source truth."""

    _text: str

    def __init__(self, record: dict) -> None:
        object.__setattr__(self, "_text", canonical_json(_observation_record(record)))

    @classmethod
    def from_record(cls, record: dict) -> ExternalObservationReceipt:
        return cls(record)

    def canonical_record(self) -> dict:
        _exact("observation text", self._text, str)
        bounded_utf8_length("observation text", self._text, limit=MAX_OBSERVATION_BYTES)
        return _observation_record(json.loads(self._text))

    @property
    def output(self) -> dict | None:
        return self.canonical_record()["output"]

    @property
    def observation_id(self) -> str:
        value = self.canonical_record()
        # Request IDs/ETags describe transport only. Pagination affects the
        # normalized completeness observation, but does not establish authority.
        return domain_fingerprint("ibae.external-read-observation-id.v1", {
            "tool_key": value["request"]["tool_key"], "status": value["status"],
            "reason": value["reason"], "output": value["output"]})

    @property
    def receipt_id(self) -> str:
        return domain_fingerprint("ibae.external-read-observation-receipt-id.v1", self.canonical_record())


def parse_github_response(plan: GitHubRequestPlan, status_code: int, body: bytes,
                          source_metadata: dict | None = None) -> ExternalObservationReceipt:
    """Parse supplied bytes only; this function does not establish live origin."""
    _exact("GitHub request plan", plan, GitHubRequestPlan)
    request = plan.canonical_record()
    _integer("HTTP status", status_code, minimum=100, maximum=599)
    _exact("response body", body, bytes)
    if len(body) > request["max_response_bytes"]:
        raise ValueError("GitHub response body exceeds the declared byte bound")
    metadata = _metadata({"request_id": None, "etag": None, "has_next_page": False}
                         if source_metadata is None else source_metadata)
    output = _normalize_response(request, _json_body(body), metadata) if status_code == 200 else None
    return ExternalObservationReceipt({"protocol_version": EXTERNAL_OBSERVATION_VERSION,
        "request": request, "status_code": status_code,
        "status": "observed" if status_code == 200 else "unavailable",
        "reason": "response_observed" if status_code == 200 else "redirect_rejected" if 300 <= status_code < 400 else "http_unavailable",
        "output": output, "source_metadata": metadata, "source_semantics": request["source_semantics"], "control_authority": False,
        "native_evidence": False, "source_authentication": "not_established"})


@dataclass(frozen=True, slots=True, init=False)
class FrozenReadAdapter:
    """Deterministic local frozen data; no disk paths are opened or followed."""

    _adapter: FakeFilesystem

    def __init__(self, fixtures: tuple[SyntheticReadFixture, ...]) -> None:
        object.__setattr__(self, "_adapter", FakeFilesystem(fixtures))

    def read(self, proposal: NormalizedProposal, dependency_fingerprint: str) -> AdapterResult:
        _exact("local read proposal", proposal, NormalizedProposal)
        _exact("frozen filesystem adapter", self._adapter, FakeFilesystem)
        if proposal.kind is not ProposalKind.READ:
            raise ValueError("frozen reads require the normalized read proposal contract")
        payload = proposal.payload
        return self._adapter.read(payload["tool_name"], payload["arguments"], dependency_fingerprint)

    def lookup(self, tool_name: str, arguments: dict, dependency_fingerprint: str) -> Any:
        """Trusted native-read backend seam; still only exact frozen data."""
        _exact("frozen filesystem adapter", self._adapter, FakeFilesystem)
        return self._adapter.lookup(tool_name, arguments, dependency_fingerprint)


class GitHubTransportUnavailable(RuntimeError):
    """No public response was established; does not infer task or effect state."""


def _read_http_observation(plan: GitHubRequestPlan, response: http.client.HTTPResponse) -> ExternalObservationReceipt:
    """Bounded response-reader seam; never creates or dispatches a connection."""
    _exact("GitHub request plan", plan, GitHubRequestPlan)
    request = plan.canonical_record()
    content_length = response.getheader("Content-Length")
    if content_length is not None:
        if (type(content_length) is not str or len(content_length) > 10
                or re.fullmatch(r"[0-9]+", content_length) is None
                or int(content_length) > request["max_response_bytes"]):
            raise ValueError("GitHub response content length exceeds the supported bound")
    encoding = response.getheader("Content-Encoding")
    if encoding not in (None, "identity"):
        raise ValueError("compressed GitHub response is outside the bounded profile")
    body = response.read(request["max_response_bytes"] + 1)
    _exact("response body", body, bytes)
    if content_length is not None and len(body) != int(content_length):
        raise ValueError("GitHub response body does not match its declared content length")
    link = response.getheader("Link")
    if link is not None:
        _exact("pagination metadata", link, str)
        bounded_utf8_length("pagination metadata", link, limit=4_096)
    metadata = {"request_id": response.getheader("X-GitHub-Request-Id"),
                "etag": response.getheader("ETag"),
                "has_next_page": link is not None and "next" in link.lower()}
    return parse_github_response(plan, response.status, body, metadata)


@dataclass(frozen=True, slots=True, init=False)
class GitHubReadAdapter:
    """Activation-gated, non-cacheable public GET observation capture backend.

    Do not dispatch this GET as a legacy native CACHEABLE_READ. The trusted
    controller may retain an exact immutable observation snapshot, whose later
    separately governed read proves only consumption of that captured content.
    Neither this object nor a response can authorize that native read. A call
    reserves a finite stage-3 transport attempt even if the remote request fails.
    No credentials, proxy, endpoint, callback or redirect override is accepted.
    """

    _selection: GitHubReadSelection
    _activation: Any
    _task_id: str
    _governance_id: str

    def __init__(self, selection: GitHubReadSelection, activation: Any, *,
                 task_id: str, governance_id: str) -> None:
        from .transport_activation import ActivationController

        _exact("GitHub selection", selection, GitHubReadSelection)
        _exact("activation controller", activation, ActivationController)
        _fingerprint("task ID", task_id)
        _fingerprint("governance ID", governance_id)
        object.__setattr__(self, "_selection", GitHubReadSelection.from_record(selection.canonical_record()))
        object.__setattr__(self, "_activation", activation)
        object.__setattr__(self, "_task_id", task_id)
        object.__setattr__(self, "_governance_id", governance_id)

    def validate_activation(self, activation: Any) -> None:
        """Trusted controller binding check; returns no new capability."""
        from .transport_activation import ActivationController

        _exact("activation controller", activation, ActivationController)
        if self._activation is not activation:
            raise ValueError("GitHub adapter belongs to a different activation controller")
        _fingerprint("task ID", self._task_id)
        _fingerprint("governance ID", self._governance_id)
        if self._task_id != activation.task_id or self._governance_id != activation.governance_id:
            raise ValueError("GitHub adapter task/governance bindings differ from activation")
        self._selection.canonical_record()

    def binding_record(self) -> dict:
        """Detached selection observation, not live provenance or authority."""
        self.validate_activation(self._activation)
        return {"task_id": self._task_id, "governance_id": self._governance_id,
            "selection_id": self._selection.selection_id, "selection": self._selection.canonical_record(),
            "network_operation_cacheable": False, "control_authority": False}

    def observe(self, proposal: NormalizedProposal, dependency_fingerprint: str) -> ExternalObservationReceipt:
        from .transport_activation import ActivationController

        _exact("activation controller", self._activation, ActivationController)
        _fingerprint("task ID", self._task_id)
        _fingerprint("governance ID", self._governance_id)
        plan = GitHubRequestPlan(proposal, self._selection, dependency_fingerprint)
        request = plan.canonical_record()
        reservation = self._activation.reserve_read(task_id=self._task_id,
            governance_id=self._governance_id, tool_name=request["proposal"]["payload"]["tool_name"],
            selection_id=self._selection.selection_id, proposal_id=proposal.proposal_id,
            dependency_fingerprint=dependency_fingerprint)
        connection = None
        try:
            # Constructing HTTPSConnection does not connect. Check the exact
            # live reservation again immediately before the network entry.
            connection = http.client.HTTPSConnection("api.github.com", port=443,
                timeout=request["timeout_ms"] / 1_000, context=ssl.create_default_context())
            self._activation.check_read_reservation(reservation)
            connection.request("GET", request["url"][len("https://api.github.com"):],
                headers={**request["headers"], "User-Agent": "QSOL-IBAE-readonly-v1", "Accept-Encoding": "identity"})
            receipt = _read_http_observation(plan, connection.getresponse())
            # A rollback/revocation while the GET was outstanding retires its
            # result as well as future dispatch. The observation grants nothing.
            self._activation.check_read_reservation(reservation)
            return receipt
        except (OSError, http.client.HTTPException):
            raise GitHubTransportUnavailable("public GitHub read unavailable; no result established") from None
        finally:
            try:
                if connection is not None:
                    connection.close()
            finally:
                self._activation.complete_call(reservation)


def readonly_interface_manifest() -> dict:
    """Describe implemented surfaces without asserting activation or live use."""
    return {"protocol_version": "IBAE-READONLY-INTERFACES-V1", "control_authority": False,
        "local_filesystem": "exact_frozen_data_only", "github_public": "stage3_gated_get_backend",
        "github_native_consumption": "separate_observed_snapshot_only", "current_remote_state_verified": False,
        "github_authenticated": "unavailable_no_credential_broker",
        "chatgpt_continuation": "unsupported", "work_continuation": "unsupported",
        "codex_continuation": "unsupported", "effects": "unsupported_pending_v0.6d",
        "live_verification": "not_established"}


def unsupported_session_continuation(interface: AdapterInterface) -> dict:
    """Do not infer a session continuation API from a conversation product."""
    _exact("session interface", interface, AdapterInterface)
    if interface not in {AdapterInterface.CHATGPT, AdapterInterface.WORK, AdapterInterface.CODEX}:
        raise ValueError("expected ChatGPT, Work or Codex session interface")
    return {"protocol_version": "IBAE-SESSION-INTERFACE-STATUS-V1", "interface": interface.value,
        "status": "unsupported", "reason": "no_supported_session_continuation_api",
        "network_attempted": False, "native_resume_supported": False, "control_authority": False}
