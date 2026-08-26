# AGENTS.md

Machine-facing repository rules.

1. Read `INVARIANTS.md` before changing runtime behavior.
2. Identify every invariant affected by a change.
3. Preserve deterministic canonicalization and content-derived identity.
4. Add or update tests for each affected invariant.
5. Never introduce a proprietary remote inference provider other than OpenAI.
6. Do not create a generic proprietary-provider abstraction.
7. Future local open-weight models are workers, not supervisors.
8. No worker may declare task completion, alter provider policy, or extend its own execution budget.
9. Cached observations must be invalidated when declared dependencies change.
10. No optimization may alter observable semantics without a versioned contract change.
11. Avoid new dependencies unless they materially strengthen the kernel.
12. External code contributions require a separate written contribution agreement.
