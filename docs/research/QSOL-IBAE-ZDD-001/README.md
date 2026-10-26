# ZERO-DAY-DREAD: evidence-governed engineering case

Status: proposed documentary contribution; no runtime assurance claim.

The source case is QSOLKCB/ZERO-DAY-DREAD PR #2, final head
`d8728a0150e8986479a7268aba396d8fd29af5e2`, merged by the maintainer at
`a704bd329e82ede16ade06ffc1e7a29e87facd4c`. Main Actions run 40295247316
completed all 12 jobs successfully, including Pages deployment. During the
26 October 2026 documentary recovery, the public source marker matched that
merge. The maintainer's no-issues report is a manual statement, separate from CI.

Period A (PR #1) is retrospective: six Sourcery findings and one later Codex
finding. Period B begins with registration commit
`497f2564c68b5b2556c5f1c3bf90a2309a613264`, before implementation. It contains
two Sourcery findings and later corrections, plus four retained Codex
no-major-issues receipts across revisions, including the final head.
No final-head formal Sourcery approval was recovered. No reviewer ranking is
justified by sequential review of different revisions.

The case retains unsupported browser setup, WebKit file-navigation failure,
and a cancelled workflow despite Chromium PASS text. Playwright 1.64.1 with
matching bundled browsers and a 20-minute browser-job budget preceded the
successful final workflow; the WebKit root cause was not isolated.

## Relevance to IBAE

Read the existing root `RECOVERY_PROTOCOL.md` and `EVIDENCE_PROTOCOL.md`.
This case illustrates exact-commit review invalidation, explicit evidence
classes, preservation of failure and uncertainty, and human integration
authority. It occurred in ordinary ChatGPT Work, not inside the IBAE runtime.
Its archive checksums are not native seals, bounded leases or finalization.
Recovered historical records cannot restore lost native authority.

The interrupted local manuscript, complete event trace and standalone
before/after reproduction logs were not recovered. A newly assembled
manuscript/ledger uses recovered source records and labels missing evidence.
Original attachment bytes and committed source were recovered and hashed.

Companion preparation archive:
`QSOL-IBAE-ZERO-DAY-DREAD-Case-Study-v1.0.0.zip`.
It has no assigned publication DOI here. Consult its SHA256SUMS and external
ZIP checksum; the package is not a software release or publication approval.

## Scope of this contribution

Documentation only. No changes to invariants, their enforcement status,
canonical schemas, runtime code, fixtures, transport activation or release
state. The inspected IBAE base is `d4a5ee812b929073c6fa494b3367e85a1fcda0a1`.
Any later PR requires current repository policy and maintainer review.
