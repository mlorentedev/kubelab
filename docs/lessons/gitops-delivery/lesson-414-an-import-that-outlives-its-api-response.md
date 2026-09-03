---
id: lesson-414-an-import-that-outlives-its-api-response
type: lesson
status: active
created: "2026-09-02"
owner: manu
category: gitops-delivery
tags: [kubelab, gitops-delivery, gitea, migration, verification]
---

# An import that outlives its API response turns a verification count into a reading of the clock

**Context**: TOOL-035 PR2 migrated `mlorentedev/resume` into the self-hosted Gitea forge with
`POST /repos/migrate`, and AC3 required proving that issues and pull requests carried over — verified
by counting through the API against a GitHub baseline of 28 open issues and 165 pull requests.

**Problem**: The counts moved. Read at three moments minutes apart on the same repository:

| reading | pull requests | max PR number |
|---|---|---|
| 1 | 98 | 137 |
| 2 | 147 | 228 |
| 3 | **165** | — |

The first reading also showed **0 open pull requests against a baseline of 5**, and the five open PR
numbers (`#253, #255, #256, #258, #259`) answered **404**. That is indistinguishable from "pull
requests did not carry over" — a finding severe enough to have been written into `verification.md` as
evidence of a partial migration. Gitea answers `200` throughout and never reports that an import is
still running; the repository reads as complete from the first moment it exists.

The same asynchrony bit one layer up: `POST /repos/migrate` had not returned after the client's 15s
default and `requests` raised `ReadTimeout` — while the server carried on succeeding. An error whose
meaning is "it may or may not have worked" is worse than a slow call.

**Solution**: Waited for the counts to stop moving, then recorded them: 165/165 pull requests, 5/5
open, 28/28 open issues, all five `mergeable=True`. Nothing had failed to carry over. The reconcile
now reports `repo migration accepted` rather than "migrated" and prints that the import continues in
the background, and `MIGRATION_TIMEOUT = 600` applies to that one call.

**Rule**: **A count is evidence only once it stops changing.** Before recording any number as
verification of an asynchronous operation, take it twice and require the two to agree — a single
reading measures the clock, not the system. This is lesson-408's family (`gh issue list --limit 20`
measuring the flag rather than the repository) with a different disguise: there the bound came from a
query parameter, here from time. Both produce a number that is real, wrong, and carries no signal
that it is wrong. And when a long operation times out client-side, **check the server's state before
concluding failure** — `ReadTimeout` on a call that mutates means "unknown", never "no".

**Tags**: `#gitea` `#migration` `#verification` `#async` `#pr-1564`
