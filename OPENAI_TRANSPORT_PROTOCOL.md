# v0.6C official OpenAI and read-only transport

Status: implementation candidate. The accepted predecessor is v0.6B PR #9,
merge `4a6e75d703e85e21a549c39c4509d15ac564d1e3`, reviewed source
`1962b6afe525b1d50d921158d474b95d8c791800`.

## Authority and deployment boundary

Transport translates external observations into existing bounded inert data.
It neither grants a tool permission nor issues a continuation lease. The Python
supervisor still proposes through `IBAE-NORMALIZED-SUPERVISOR-PROPOSAL-V1`;
the accepted governance, orchestration and native runtime remain authoritative.
A successful HTTP response, API response ID or transport receipt never restores
native execution authority, proves task completion or authenticates arbitrary
serialized IBAE evidence.

Live activation is disabled by default. Deployment configuration belongs to a
trusted operator, not model output, retrieved repository text or tool results.
The Python transport controls are process-local safety controls, not new Rust
seals or protection against arbitrary code execution in the trusted host.
Serialized records are observations and cannot restore an activated controller.

## Official provider and wire boundary

The only proprietary model transport is the official OpenAI Python SDK using
the Responses API. No generic provider registry, arbitrary endpoint, internal
ChatGPT session API, Azure compatibility layer or alternate provider exists.
The client disables implicit retries, redirects and environment-selected proxy
or endpoint behavior. A declared finite call budget is consumed before dispatch;
network failure or missing acknowledgement cannot refund a sent attempt.

Supervisor input is a mutation-isolated canonical projection. Native runtime,
lineage seals and supervisor capabilities are never passed to the transport.
The transport returns only bounded normalized proposals, initially classified
`model_proposed`. Refusals, incomplete output, unexpected tool calls, malformed
JSON and unsupported wire versions fail closed with bounded structured status.
Raw response bytes are bounded before parsing. Latency, usage and remote request
IDs are transport observations, excluded from deterministic admission authority.

## Credentials

The model and orchestration see only opaque `cred:openai.<name>` references.
Trusted deployment configuration binds a reference to a task/governance policy
and an approved secret source. Resolution occurs only after activation and call
reservation, immediately before SDK initialization. Secrets are not accepted as
normalized proposal arguments and are not emitted in receipts, fixture files,
object representations, raw error messages or logs. The broker does not save
new credentials or expand account permissions.

This contract cannot erase copies retained by Python, the official SDK or the
operating system. Its guarantee is narrow lifetime and no intentional export
through the IBAE model/evidence interfaces, not secure memory erasure.

## Conversation context and recovery

An OpenAI Responses continuation ID is provider context only. It must belong to
the same controller-owned successful history and deployment binding. Instructions
are supplied again for every request. Missing or stale history requires a fresh
session with the verified inert handoff; it never reconstructs lost native
runtime state or increases the original task's budgets.

Direct ChatGPT conversation, Work task and Codex-thread reconnection are
explicitly unsupported by this package unless an official separately reviewed
integration supplies them. Their availability in this engineering environment
does not imply availability to a deployed QSOL-IBAE process.

## Activation and rollback

The activation ladder is sequential:

0. Synthetic supervisor and synthetic tools.
1. Official OpenAI supervisor and synthetic tools.
2. Official OpenAI supervisor and deterministic read-only fixtures.
3. Official OpenAI supervisor and explicitly selected real read-only tools.

Each transition requires explicit operator configuration, the preceding stage's
own verified evidence, unchanged task/policy binding and a rollback check.
Synthetic/mock SDK responses cannot be reported as live-stage verification.
Unsupported verification remains unavailable; caller assertions, hashes or
JSON receipts cannot silently substitute for a verifier.

Rollback and revocation invalidate pending transport context and cannot refund
used call capacity. They do not create native continuation authority. Stage 4,
external mutations and effect execution are outside this protocol.

## Read-only external observations

GitHub inspection is restricted to selected repository, branch, commit, pull
request and CI resources using fixed HTTPS GET routes. No URL or method supplied
by a model becomes an unrestricted request. Redirects, arbitrary headers,
mutating verbs and undeclared targets are rejected. Requests, response bytes and
transport attempts are bounded. Truncated or unavailable data is explicitly
incomplete and is not silently promoted to a complete observation.

A structured external observation receipt binds the selected request, response
and declared dependency. It remains transport evidence. Actual governed reads
must use typed admission, the matching governed tool receipt and
`execute_admitted_read` before runtime/evidence machinery may consume them.
Local frozen read adapters reuse the same declared tool identity and normalized
proposal boundary as the accepted synthetic phase.

## Verification status

Keep these separate in every report:

- implemented and locally tested;
- synthetic/SDK-mock conformance;
- genuine live verification;
- blocked by missing credentials, activation evidence or network permission;
- unsupported by the package or official platform.

The candidate's offline equivalence tests compare actual normalized input
streams through fresh accepted native sessions. They do not establish successful
live OpenAI, GitHub, Work or Codex recovery. Live gates remain closed until their
own execution evidence is obtained. Accepted v0.2–v0.6B fixtures are immutable.

## Supported SDK and official references

The optional dependency is pinned to `openai==3.29.0`, verified against the
[official signed release](https://github.com/openai/openai-python/releases/tag/v3.29.0).
Offline tests exercise this installed SDK's request serialization through an
in-memory HTTP transport. They do not make API requests.

- [Official Python API reference](https://developers.openai.com/api/reference/python)
- [Responses create](https://developers.openai.com/api/reference/python/resources/responses/methods/create)
- [Structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [Conversation state](https://developers.openai.com/api/docs/guides/conversation-state)
- [API overview](https://developers.openai.com/api/reference/overview)

The wire envelope uses strict structured output with a version and an inner
proposal JSON string, then applies the full accepted deterministic proposal
parser. This avoids pretending arbitrary payload maps are enforceable by a
looser provider schema. Fresh requests require exact inert handoff/projection
equality. Optional stored Responses continuation uses only this adapter's own
successful response ID bound to controller, epoch, task, governance and policy.

Separate official products, including Codex App Server, may offer thread resume.
That is not the Responses API and is not implemented by this adapter; reporting
it unavailable here is not a claim that no official platform supports it.

## Exact deployment binding

Activation, reservations and stage observations bind both the complete transport
policy identity and credential-reference identity. The latter includes an opaque
fingerprint of the configured non-secret source locator and explicit source
version. Configuring a different deployment retires prior stage evidence and
context without refunding capacity. Secret values are never fingerprinted;
operators must advance the source version and reconfigure/revoke on rotation.

Stage-3 authorization additionally names exact selected GitHub resource-selection
identities, not only tool names. Verification probes snapshot their stage, epoch,
deployment and observed stream; a concurrent rollback/configuration change
invalidates their result before evidence is committed. In-flight transport is
checked again before an observation can be returned.

Implementation acceptance and live deployment acceptance are distinct. The
user-authorized unavailable-credential path allows review of testable architecture
with live verification explicitly BLOCKED. Subsequent synthetic, default-disabled
effect implementation does not open any live transport or effect gate.

## Current stage-3 verification limit

The selected public GET adapter is implemented, but this candidate has no
trusted native verifier for an entire selected-live-read task. The explicit
`verify_selected_read_stage()` operation therefore reports unavailable and
cannot mint a successful stage observation. This is separate from missing
credentials and from the supported offline/native fixture probe.

Mutable repository, branch, pull-request and CI observations are not cacheable
content snapshots merely because their selection or HTTP receipt has a hash.
The accepted legacy Rust admitted-read path is cacheable-only. Importing a
mutable external observation requires a separately verified source snapshot and
matching governed dependency contract; this transport never invents that
binding or relabels a volatile read. Live selected-read acceptance remains closed
until its own native evidence integration is verified. No effect stage inherits
permission or proof from an unavailable read gate.
