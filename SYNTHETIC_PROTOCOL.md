# Offline synthetic supervisor and recovery conformance

Status: v0.6B candidate. Predecessor v0.6A is accepted at PR #8 merge
`735be520825aed8fe383bcf4092a26dd3ee15aa1`. This candidate requires its own
exact-head review and all conformance gates before live integration begins.

## Scope and authority

The external world is frozen fixture data. Governance, orchestration,
continuation, Rust accounting, native seals and compact evidence are real.
No fixture calls a live model, resolves a credential, accesses an external
service, commits a repository change or performs an external mutation.

Normalized supervisor messages are proposals. Successful transport and a
well-formed message confer no admission, execution, lease or finalization
privilege. The synthetic and future live adapters share this bounded normalized
boundary; a later live adapter cannot introduce an alternate authority path.
The only proprietary provider admitted by the boundary is OpenAI.

A deterministic supervisor consumes the same exact-source-validated compact
`SupervisorProjection` that a future live transport will receive. Retrieved
repository, tool, worker, research and conversation text is inert data. Claims
of progress or completion do not satisfy an obligation or produce a lease.

## Control cycle

1. DECLARE an exact governed task, finite obligations, deterministic observation
   acceptance rules, admitted strategy/capability schemas and bounded profile.
2. OBSERVE through normalized frozen proposals, deterministic orchestration
   admission, exact governed tool receipts and Rust admitted-read accounting.
3. CLASSIFY objective progress from admitted observations and bound canonical
   obligations. Activity, transport status, elapsed time and model prose are
   excluded from progress authority.
4. INTERVENE using an admissible bounded proposal, native-sealed continuation
   request, exact governance grant/denial and native application where allowed.
5. RECEIPT the actual source-bound execution with the unchanged compact
   evidence reducer and governance final/partial gates.
6. REPLAY the checked-in normalized input in a fresh independent native session
   and compare canonical evidence byte for byte, including across hash seeds.
7. RECALIBRATE only through a separately versioned admitted profile. Research
   observations cannot modify the running policy.

Legacy evidence is manifest-scoped. A segmented run must identify the exact
scope of each accepted final/partial receipt and preserve explicit native
continuation boundaries. A conformance summary is not a new native seal or a
replacement global finalizer. In particular, lease-application transitions
cannot be omitted to manufacture a continuous legacy read-evidence chain.

## Frozen adapters and credentials

Closed read adapters cover representative GitHub, filesystem, web, read-tool
and worker fixtures. Proposed ChatGPT/Work/Codex interfaces explicitly report
unavailable; the separate recovery corpus models their frozen interruption
observations without claiming a supported live or synthetic continuation API.
Unsupported operations and unavailable state are explicit. A missing response
is not evidence of a failed operation or a lost native task.

Read fixtures are exact-keyed, bounded inert values. No user-supplied callable,
endpoint or arbitrary credential resolver is an adapter configuration input.
Opaque synthetic credential handles carry no secret and never resolve to one.
Raw credential-shaped values are outside the closed handle contract. No
provider SDK is needed for the synthetic phase.

Effect proposals are classified and rejected through the unsupported-effect
boundary. Frozen before/after commit observations represent external history;
they do not execute a commit, overwrite a worktree or hide a mutation inside a
read. Actual effect execution remains the separate v0.6D gate.

## Interruption and recovery

The source of current authority is the retained original native task and live
lineage, not a serialized checkpoint or a fixture label. Existing-task resume
requires that exact source. A fresh task requires independent authorization
that explicitly selects historical evidence; it inherits neither seals nor
remaining resources from a lost task.

The corpus distinguishes:

- interrupted conversations, Work tasks and Codex threads;
- commit already observed before a lost acknowledgement versus interruption
  before a commit, unknown outcome and lost uncommitted state;
- apparent inactivity while the original execution remains active;
- stale checkpoints, duplicate continuation requests and duplicate application;
- partial objectives, finite continuation exhaustion and repeated failures;
- period-one/two/three action loops, strategy churn and material recovery;
- superficial paraphrase, forged receipts and compact evidence;
- fake progress/completion, provider substitution and capability escalation;
- hostile repository, tool and worker text and research/profile drift;
- missing evidence producing indeterminate outcomes;
- interruption during recovery, source-bound checkpoint continuation and
  fresh-session/continued-session equivalence.

Recovery uses the least additional authority needed: inspect existing evidence
or continue the verified live task before considering a separately authorized
fresh task. Unverifiable state stops or requests authorization. No retry is
justified solely by a lost acknowledgement, and no interruption increases the
precommitted budget. Simulated success is never live recovery verification.

## Evidence and research boundary

Canonical fixture inputs and replay outputs have separate domain-separated
identities. Exact source receipts and bounded result classes are retained;
transport labels and model claims cannot substitute for them. A test runner
must fail on malformed input, changed expected evidence, source drift or an
unexpected live adapter configuration.

Exact proposal/admission/execution/rejection counts are sufficient for the
first offline pressure observations. No ratio threshold is operational policy.
Diversification remains a research candidate; it cannot create obligations or
extra resources outside the original governed task, and no benchmark result
in this phase promotes it to authority.

Accepted historical v0.2–v0.6A fixture bytes remain immutable. The new v0.6B
fixtures and protocol names are separate candidate identities. Live OpenAI,
live read adapters, durable cross-process native reconstruction, authenticated
remote producers and actual effect execution remain unverified or unsupported.

## Independent replay interface

- `fixtures/v0.6B/supervisor-transcripts.json`: closed canonical normalized
  control inputs and registered recovery scenario specifications.
- `fixtures/v0.6B/synthetic-recovery-reference.json`: canonical evidence from
  actual fresh in-process native runs of those inputs.
- `python tools/render_v0_6b_fixture.py --input fixtures/v0.6B/supervisor-transcripts.json --verify fixtures/v0.6B/synthetic-recovery-reference.json`

The source file must be exact canonical JSON with one final newline. The
reader caps it before parsing, and the typed parser independently bounds its
shape and content. The conformance envelope allows at most 16 control streams,
64 recovery scenarios, 1 MiB input and 2 MiB output. Every constituent protocol
has tighter local limits. The output binds its full input identity and reports
source-bound control receipts separately from non-authoritative recovery and
research observations. These ceilings bound a test corpus, not a new execution
budget or routine unbounded trace surface.
