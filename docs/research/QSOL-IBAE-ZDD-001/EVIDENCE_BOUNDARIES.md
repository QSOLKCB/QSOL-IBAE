# Governance analysis and formalization status

This case occurred in an ordinary ChatGPT Work session. The mission label names Astra, but no independent model/reasoning telemetry is available. It was not run inside QSOL-IBAE. Recovered records show an evidence-governed workflow; they do not establish native bounded execution.

## Evidence and authority

- OBSERVED: retrieved GitHub records and exact source/attachment bytes, successful HTTP fetch and deployed SHA. Observing an author claim in a comment does not turn its claimed experiment into an independently observed reproduction.
- DERIVED: counts, source-order ledger, hash matches and acceptance mappings computed from those records.
- PROPOSED: publication metadata and documentation-only QSOL-IBAE contribution.
- UNKNOWN: missing local traces, independent model identity, unmeasured resource costs and unverified native-device behavior.

Integration authority came from the human maintainer. CI supplied test conclusions, Codex supplied an exact-head code-review result, and the maintainer supplied a manual no-issues report and merge. None substitutes for another. Main deployment is an observed external effect; cancellation would not prove that an external effect was reversed. Recovery consulted existing commits and results instead of replaying mutations or restarting the experiment.

The inspected QSOL-IBAE reference is `d4a5ee812b929073c6fa494b3367e85a1fcda0a1`. Its `RECOVERY_PROTOCOL.md` distinguishes structural historical records from live native witnesses and explicitly says cross-process restoration of old native authority is unsupported. This handoff is therefore a newly authorized documentary recovery from durable evidence, not `resume_verified_live_task` inside an IBAE runtime. Its SHA-256 manifest is not an IBAE receipt or native seal.

## Formalization inventory

| Layer | Present evidence | Status and boundary |
| --- | --- | --- |
| Written contracts | the companion archive source/main/docs/CONTRACTS.md | Inspectable specifications with deployment assumptions. |
| Engine/serialization regressions | tests and CI | Executed software checks on finite input sets; no exhaustive correctness proof. |
| Deployment state exploration | tests/governance-model.test.cjs | Finite three-commit model with monotonic main, common lock and completion assumptions; not a GitHub service proof. |
| Counterexample | Same test file | Abstract stale-publication schedule for freshness-only policy; no live production race. |
| Exact-commit predicate | Same test file | Enumeration of head/review/CI/human combinations; a small executable specification, not enforcement of GitHub permissions. |
| Lean or other proof assistant | No Lean files/toolchain/build evidence recovered in either source tree | Not provided; no machine-checked theorem claim. |
| Native IBAE runtime | No native session, seals, lease or finalization records | Not tested; no assurance imported from the IBAE documentation. |

The exact-commit predicate is essentially an executable statement of the desired gate. It should be read as a specification check, not independent validation of policy enforcement. The deployment model excludes external deployers, old workflow reruns, runner loss, force-push/nonmonotonic main and uncertain external completion. The corrected freshness predicate tests actual application helper behavior, which is a narrower and more concrete result.

## Governance findings

The useful outcome is recoverable separation: a new final commit requires new evidence; a reviewer finding remains visible after correction; a cancelled workflow stays cancelled despite PASS text; a human report remains a human report; an integrated application does not authorize release or publication. These are case observations and design lessons, not causal proof that governance improved performance or prevented every unauthorized action.
