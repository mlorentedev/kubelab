# Run report 20261106-console

Armed 2026-11-06T06:51:32Z, expires 14:51:32Z. Host: `caffeinate -i -t 28800` started at arming; the lid had to stay open. That process was killed (exit 144) around 07:10Z; another `caffeinate` (pid 20549, 28800 s, started about 07:03Z) held the wake lock from then, past expiry.

## Items

| # | Item | Outcome |
|---|---|---|
| 1 | console host root redirect | #3159 merged (dotf pr land, 09:36Z) |
| 2 | A8 usage counter (the objective) | parked: scope-violation, see below |
| 3 | AC1 down-source regression test | #3161 merged |
| 4 | AC7 rebuild test + runbook | #3162 merged (runbook `docs/runbooks/forge-console-operations.md`) |

## Item 2 parked (the objective)

A new table means a new Atlas migration, and `tests/test_api_migrations_rendered.py`
requires it verbatim in `infra/k8s/overlays/{staging,prod}/generated/migrations.yaml`.
The prod file is frozen and the staging one is outside `write_paths`, so no green PR was
possible inside the envelope. Runtime DDL would bypass the Atlas Job (DATA-007); not done.
Park comment with two options: #2570 (issuecomment-6679142480). #2570 was not moved to
Blocked: items 1, 3 and 4 share it and are live.

Ruling (advisor): the run continued with items 3 and 4 although item 2 was the objective,
because they were enumerated in the committed envelope and inside its scope.

Envelope defect, for the next one: any API change with a migration touches generated files
outside `apps/api/**`. This envelope was written without checking that, and the objective
depended on it.

## Debt found and fixed

Two store tests (`TestQueueReadsDeclaredOpenItemsNewestFirst`, `TestQueuePagesNeitherSkipNorRepeat`)
read the port inline and skipped in CI when it was unset, missing #3117's guard. Fixed in #3161.

## Reviews

PR-Agent reviewed all three; CodeRabbit and Codex posted only quota notices. Every finding was
declined with evidence or noted as tracked, in a `## Review triage` comment on each PR.
Landing hit GitHub's secondary GraphQL limit and two 502s; each was retried through
`dotf pr land`, never merged by hand.

## End

Ended 09:41Z, reason `queue-empty`: all four items processed (three merged, one parked).

Open for the operator:
- A8 counter: choose option A or B in the park comment on #2570.
- AC7 restore rehearsal (touches prod data), then tick the runbook task in `tasks.md`.
- Logged-in check of `https://console.kubelab.live/` (now redirects to `/console/`) once api
  ships a release with #3159.
