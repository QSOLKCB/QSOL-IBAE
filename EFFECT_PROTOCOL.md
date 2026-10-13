# Governed synthetic effects and recovery

Status: v0.6D implementation candidate, not yet accepted. Accepted predecessor:
v0.6C implementation PR #10, merge `88e3de74a7c8ee10be81c669aaaa8b6bebd933ff`.
C live provider/GitHub/recovery verification remains BLOCKED. This phase supplies
only a default-disabled, closed in-memory synthetic effect executor.

## Version and authority boundaries

`IBAE-EFFECT-PROFILE-V1`, `IBAE-EFFECT-RUNTIME-V1`,
`IBAE-EFFECT-SNAPSHOT-V1`, `IBAE-EFFECT-OBSERVATION-V1` and
`IBAE-EFFECT-RECEIPT-V1` form a separate command/evidence family. No v0.3 read
command, v0.4 read finalizer, v0.5 resource vector or lease schema is extended.
v0.5 mutation resources remain zero. D records cannot establish legacy final
task acceptance, continuation progress or current external state.

Python constructs bounded inert declarations and projects observations. Rust
owns exact effect state, finite accounting, approval issuance, dispatch,
occurrence journal, ordering and source seals. The native executor accepts no
Python backend callback, arbitrary operation, filesystem path, network endpoint
or credentials. Model text cannot authorize or report an effect as executed.

## Original-task commitment

The original TaskReceipt acceptance contract must contain `effect_profile_id`.
The profile commits its governance ID, ordered action declarations, exact initial
cells, closed outcome plans and all four finite limits. It is constructed before
task admission; full governed tool receipts are bound after admission, avoiding
an identity cycle. Native creation independently checks the original task and
governance identities already bound to its continuation supervisor capability.

Each entry carries the exact typed capability, proposal, admission decision,
dependency fingerprint and occurrence identity. Governance must authorize the
corresponding mutation class, forbid cache treatment and bind the same action,
arguments, task and policy. Legacy capability/policy/task versions retain their positive 256-bit canonical
integer domain; admitted logical ticks retain the corresponding nonnegative
domain. These identity fields are not narrowed to the u64 operational counters.
A recomputed hash alone is not issuance authority.
Creation additionally requires established native continuation lineage.

Exactly one D ledger may attach to a native task binding. Invalid or disabled
creation is state-neutral. Successful attachment is one-shot; duplicate handles,
equal public IDs, serialized records and continuation leases cannot create a new
budget or reset occurrence ownership.

## Closed operations and ordering

- `synthetic_set`: idempotent mutation, exact signed-64-bit target value.
- `synthetic_increment`: non-idempotent mutation, checked signed-64-bit addition.

Both require the exact `expected_value` precondition and a predeclared cell key.
A mismatch preserves existing synthetic content and produces a no-effect
failure. This models protection of uncommitted state; it does not inspect or
modify an actual working tree. Overflow rejects without applying a mutation.

Every mutation is occurrence-sensitive. Distinct admitted occurrences are not
collapsed because their payloads match. A previously applied occurrence never
executes again. Entries follow the original declared sequence, with successful
prior occurrences retained if a later entry fails or remains ambiguous. Scalars
are atomic; partial completion means partial ordered-manifest completion, not a
fabricated partially applied scalar write.

## Exact approvals and finite recovery

The command family is `execute_effect`, `retry_effect`, `reconcile_effect`,
`cancel_effect`. Each command binds the native effect session, current state ID,
exact action and occurrence. Only the matching non-constructible native
supervisor capability issues a one-shot native approval. Dispatch requires that
exact approval; changing command/state/epoch or replaying it cannot execute.

Approval scope is immutable original task/profile/governance plus the D state
and shared monotone revocation epoch. Unrelated parent read, progress or lease
transitions do not change this independent profile's policy, preconditions or
capacity, and cannot replenish it. A future cross-ledger dependency requires a
separately versioned binding; no implicit cross-ledger evidence promotion exists.

At most one native approval is pending. Abandoning it cannot reset authority or
create a second usable approval. A valid same-occurrence cancellation may
irreversibly replace one pending execute/retry seal with a cancellation-only
seal; the slot stays reserved and cannot be replaced again. Successful approval
issuance is therefore at most twice the finite request ceiling. The fixed limits are requests, executions,
retries and reconciliations. Bounds are committed at task creation; failures,
cancellation, interruption and rollback never refund spent capacity. Hard caps:
64 entries/cells, 16 outcomes per occurrence, 4,096 requests and 1,024 each
executions/retries/reconciliations. Canonical records are capped at 1 MiB.

## Lost acknowledgement and ambiguity

Closed, precommitted synthetic outcome plans are `success`, `fail_before`,
`crash_after`, `crash_before`, and `ambiguous_unknown`. They are test inputs,
not caller-supplied claims of external success. Rust applies modeled effects and
maintains its own occurrence journal.

A lost acknowledgement yields an ambiguous receipt. It does not mean failure.
Native reconciliation may prove that the exact occurrence was applied or was
not applied; cell-value equality alone is never sufficient. An applied result
cannot be retried. A not-applied result permits only a separately approved,
bounded retry. Unknown journal evidence remains ambiguous. Both operation
classes use this conservative rule; idempotence is not permission to disregard
occurrence ownership or approval.

Cancellation prevents later execution/retry without undoing prior work or
asserting that an ambiguous operation never happened. Revocation closes all
new D dispatch, including reconciliation; already retained receipts/snapshots
remain available for read-only inspection. Revocation cannot regrant authority.
No serialized snapshot restores a native ledger, approval, journal or capability.

## Evidence and acceptance

Native receipts include exact action/admission/argument identities, prior and
resulting state, pre/post observations when available, occurrence attempt,
counters, status, ambiguity, cancellation and a recovery event link. Receipt
shape is fixed; snapshots are explicitly bounded by the 64-entry/cell profile.
The native receipt seal proves the matching in-process source, not external
producer authenticity, remote attestation or human approval. JSON round-trips
retain structural integrity only and lose native source authority.

Diagnostic manifest completion is not global task acceptance. Synthetic
commit-before-lost-ack and pre-commit interruption exercises prove this closed
state machine only. They never prove actual GitHub, Codex, Work or filesystem
recovery. Accepted v0.2–v0.6C fixtures remain immutable.

## Live deployment boundary

There is no live effect backend in this version. Explicit `enabled=True` enables
only the native synthetic profile and is not approval of an externally visible
action. A future external executor requires genuine C live-stage evidence,
separate dedicated review and explicit operator/user authorization of the exact
action, destination and consequential payload. Neither native synthetic seals,
model proposals, repository content nor successful offline tests can satisfy
that external approval requirement. Live activation remains disabled/unverified.
