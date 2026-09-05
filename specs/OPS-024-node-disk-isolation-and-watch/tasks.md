---
tags: [spec, tasks, templates]
created: "2026-09-04"
---

# Tasks - OPS-024-node-disk-isolation-and-watch

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers**: `[P]` = no dependency on another unchecked task. `[AC<n>]` = satisfies acceptance criterion #`<n>`.

## Setup

- [ ] Branch created from main: `feat/OPS-024-node-disk-isolation-and-watch`
- [x] `proposal.md` is complete and acceptance criteria are testable
- [x] No open questions left in `proposal.md` "Risks / open questions"

> Both open questions were settled by the pre-implementation adversarial review
> (`review.md`, `nan/deepseek-v4-flash`, verdict FAIL on the draft): direct Loki
> push, and `by (node)` survives. That review also found what the questions had
> not asked about — `obs015-disk-root-saturation` carries `noDataState: OK`,
> so a dead producer reads as healthy — which is now AC8.
>
> Running the review *before* implementation is off-label for the skill, which is
> written for the verification window. Stated here as a decision: the three Major
> findings were all in the plan, and finding them after four PRs would have cost
> four PRs. A second review is still owed in the verification window.

## Implementation

Four PRs. PR-A is the only one that changes the failure mode; the rest reduce
probability or add detection.

### PR-A — `node_storage`: `/var/lib/docker` on its own LV (AC1, AC3)

- [ ] [P] [AC1] Failing test: the role's declared LV size comes from
      `networking.nodes.<node>.storage.*` in the SSOT, not a literal
- [ ] [AC1] Role converges an already-migrated host to `changed=0` (steady state
      first — it is the path that runs forever, the migration runs once)
- [ ] [AC3] Failing test: the migration path refuses to start when the target LV
      already holds data, so a re-run cannot half-copy over a live tree
- [ ] [AC3] Migration: stop Docker → `rsync -aHAX --numeric-ids` → verify the
      copy → mount → start. Verification happens **before** Docker restarts
- [ ] [AC3] Rehearse on a throwaway target (ace2 when powered, or a loopback LV
      on any host). Not the Beelink first

### PR-B — prove the isolation, or name the residual (AC2)

- [ ] [AC2] Fill the isolated LV deliberately (small LV, `fallocate`) and record
      what Gitea does: still serving? still accepting writes? container alive?
- [ ] [AC2] Write a real issue or push through Gitea while the LV is full —
      a health check is not evidence, it was `healthy` throughout the incident
- [ ] [AC2] If Gitea degrades: add a reserve inside the LV and re-measure.
      Record the residual in the proposal either way

### PR-C — node disk producer → the existing rule (AC4, AC5)

- [ ] [P] [AC4] Failing test: a node emits the `disk_root_usage` JSON shape the
      rule already parses, including the label that distinguishes it from the
      CronJob's stream
- [ ] [AC4] systemd timer on Docker hosts, pushing to Loki's HTTP API
      (`loki.kubelab.live`, Bearer). Token via SOPS, never on a command line
- [ ] [AC4] Verify by consequence: cross 90% on a real node, `make alerts`
      shows it. A log line in Loki is not the AC
- [ ] [AC5] Failing test: every node in `networking.nodes` is covered by either
      the CronJob or the timer. Adding a node to the SSOT without one goes red
- [ ] [P] [AC8] Failing test: no **always-on** node (ADR-028) relies on
      `noDataState: OK`; on-demand exemptions are declared per node, so a new
      node forces the choice instead of inheriting silence

### PR-D — the timer reaps what it used to report (AC6, AC7)

> **Blocked on #1665 merging.** `toolkit/features/docker_reclaim.py` is not on
> `master` — verified, `git cat-file -e origin/master:…` fails — so a branch cut
> from master cannot reuse the planner. Sequenced last for that reason.

- [ ] [P] [AC6] Failing test: `node_maintenance` calls #1665's planner with an
      age gate, rather than printing a warning
- [ ] [AC6] Replace the report-only block; `changed=0` on re-run
- [ ] [AC7] Close or update #1456, naming what changed: the age signal it
      lacked now exists

## Closing

- [ ] Every acceptance criterion from `proposal.md` is covered by at least one test
- [ ] Every acceptance criterion has a matching entry in `features.json` with a non-vacuous verification command
- [ ] Type checks pass
- [ ] Lint passes
- [ ] No unrelated changes in the diff (no scope creep)
- [ ] `verification.md` filled in
- [ ] PR opened referencing this spec folder

## Machine-readable features

See sibling `features.json`. The agent cannot write `"state": "passing"` — only
the harness may, after running `verification` and capturing exit code 0.
