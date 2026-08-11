---
tags: [spec, tasks, templates]
created: "2026-08-11"
---

# Tasks - OPS-016-dnat-drift-healing

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers**:
> - `[P]` — no dependency on another unchecked task, safe to run in parallel.
> - `[AC<n>]` — helps satisfy acceptance criterion #`<n>` from `proposal.md`.
>
> **This spec ships as three PRs.** The scope spans three tickets by explicit decision, which breaks the ~300-line atomic-PR cap if delivered as one. The spec is the unit of design; the PR stays the unit of review. Order is load-bearing: PR 1 must land before PR 2, because adding monitors to the seed while the only way to apply it destroys all history would inflict the very bug PR 1 removes.

## Setup

- [x] Branch created from main: `feat/dnat-drift-healing` ✓ 2026-08-11
- [x] `proposal.md` is complete and acceptance criteria are testable ✓ 2026-08-11
- [x] Open question resolved: monitor identity is an explicit `key` field in the seed, persisted in `description` as a marker, matched marker-first with a key-stamping name fallback ✓ 2026-08-11
- [ ] One risk remains OPEN and is visible from here on purpose: **the delete path was never exercised**. Creates and edits are proven; whether v2 also defers deletes is untested, so AC3's poll must be written against a real delete before it is claimed to work

## Implementation

### PR 1 — non-destructive monitoring sync (#962, #925)

- [x] Prove the load-bearing API assumption FIRST — `edit_monitor(id_, description=...)` round-trips and a rename preserves the id ✓ 2026-08-11, against a throwaway 2.2.1 container. Three findings recorded in `proposal.md` Risks; two of them changed the design below
- [ ] Move the throwaway harness into the repo — pytest fixture (skip when Docker is absent) or make target carrying `UPTIME_KUMA_DB_TYPE=sqlite`, the raw-emit setup, and the image tag read from `common.yaml:639` rather than hardcoded a second time. A scratchpad script is not a dev loop
- [ ] Fix `bootstrap`'s setup path — raw-emit `setup()` (verified ack `successAdded`) and narrow the `except Exception` at `monitoring.py:298` that currently reports a timeout as "Admin user already exists". **This is the broken recovery path**; `apply_monitors` was wrongly accused and already handles `conditions` itself at lines 254-261
- [ ] [P] [AC1] Write failing test: applying an unchanged seed twice preserves every monitor `id` and issues zero deletes
- [ ] [AC1] [AC2] Replace the delete-all/recreate body of `apply_monitors` with a keyed three-way diff (create / edit / delete) over `api.edit_monitor`
- [ ] [P] [AC2] Write failing test: a seed with one added, one modified and one removed monitor converges, leaving untouched monitors' ids stable
- [ ] [AC3] Write failing test: the precondition assertion exits non-zero when live state does not converge
- [ ] [AC3] Delete the `time.sleep(3)` + discarded `remaining` and replace with a bounded poll that raises instead of logging SUCCESS
- [ ] Refactor: extract the diff into a pure function taking (seed, live) and returning the three sets, so it is unit-testable without a live Kuma
- [ ] Verify against the live rpi3 instance and record monitor ids before/after in `verification.md`

### PR 2 — monitor the per-node agent ports (#963)

- [ ] [P] [AC4] Write failing test: every node in `networking.nodes.*` publishing an agent port has a matching HTTP monitor in the seed
- [ ] [AC4] Derive the agent monitors from `common.yaml` rather than hand-writing them into `monitors.json`, so a new node inherits monitoring by existing
- [ ] [AC4] Apply to the live instance and confirm a stopped port reports down within one interval

### PR 3 — DNAT drift detection and repair (#959)

- [ ] [P] [AC5] Write failing test for the comparison logic: declared bindings vs installed DNAT, over fixture data (no live node)
- [ ] [AC5] Implement the drift task — enumerate compose projects via `docker compose ls --format json`, compare, recreate only the projects that disagree
- [ ] [P] [AC6] Write failing test: the headscale project is excluded from the recreate set even when it shows drift
- [ ] [AC6] Implement the exclusion by project name, sourced from config rather than hardcoded in the task
- [ ] [AC5] Prove the repair against a deliberately flushed chain (`iptables -t nat -F DOCKER`) on ace1 — lowest blast radius, one published port, K3s runs on containerd
- [ ] [AC5] Confirm idempotency: re-run on the repaired node reports `changed=0`
- [ ] Refactor: ensure the task carries `tags:` so `TAGS=` provisioning can select it (the failure mode #978 already fixed once)

## Closing

- [ ] Every acceptance criterion from `proposal.md` is covered by at least one test
- [ ] Every acceptance criterion has a matching entry in `features.json` with a non-vacuous verification command
- [ ] Type checks pass (`make type`)
- [ ] Lint passes (`make lint`)
- [ ] No unrelated changes in the diff (no scope creep)
- [ ] `verification.md` filled in
- [ ] PRs opened referencing this spec folder, each closing its own ticket

## Machine-readable features

This spec emits a sibling `features.json` following [[pattern-feature-list-as-primitive]]. Each acceptance criterion maps to ≥1 feature with `id`, `behavior`, `verification` (executable command), `state`, and `evidence`.

**Pass-state gating:** the agent CANNOT write `"state": "passing"` — only the harness, after running `verification` and capturing exit code 0, may set that terminal state. A `passing` entry with empty `evidence` is grounds to reject the PR. A verification command that cannot fail is worse than none: OBS-007 shipped three that exited 0 with a note calling them vacuous, and the harness honoured them as passes because it judges exit codes, not notes.
