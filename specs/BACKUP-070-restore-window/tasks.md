---
tags: [spec, tasks, templates]
created: "2026-10-01"
---

# Tasks - BACKUP-070-restore-window

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers** (optional, additive — borrowed from `github/spec-kit`, adapt-not-adopt per #141):
> - `[P]` — this task has **no dependency on another unchecked task**, so it is safe to run in parallel (fan out to a `Workflow`, or just batch). TDD chains (test → implement → refactor of the *same* behavior) are sequential and must NOT carry `[P]`; independent behaviors can.
> - `[AC<n>]` — this task helps satisfy **acceptance criterion #`<n>`** from `proposal.md`. Lets `/spec check` map coverage deterministically; omit it and the check falls back to semantic judgment.

## Setup

- [ ] Spec PR merged (this folder, `docs/backup-070-spec`)
- [ ] Branch `feat/backup-070-restore-window` from master, worktree `~/Projects/kubelab-backup-070-impl-wt`, `make worktree-init`
- [ ] Verify the hub's Argo CD accepts `spec.syncPolicy.automated.enabled`: `kubectl --kubeconfig $HUB_KUBECONFIG explain application.spec.syncPolicy.automated.enabled` names the field. If it does not, switch the open to removing `automated` (proposal Risks) before writing code.

## Implementation

All in `toolkit/features/restore_window.py`, with tests in `tests/test_restore_window.py`. kubectl is stubbed at the argv boundary (the unit-test host-client barrier refuses a real one), same shape as `tests/test_argo_manager.py`.

- [ ] [AC4] Test: the open builds one merge patch on `application/kubelab-<env>` carrying `automated.enabled: false`, the holder annotation and the read's `resourceVersion`. Run `poetry run pytest -q tests/test_restore_window.py` → FAIL (module missing)
- [ ] [AC4] Implement `open_window()` up to the Application patch → PASS. Commit
- [ ] [AC2] Test: an Application that already carries the annotation makes `open_window()` raise `WindowHeldError` naming the holder, with no patch issued → FAIL, implement → PASS. Commit
- [ ] [AC1] Test: after the patch, the spoke Deployment is scaled to 0, and the wait polls until no pod of its selector exists and none mounts its claims (bounded, timeout → error that says the window stays open) → FAIL, implement → PASS. Commit
- [ ] [AC3] Test: `close_window()` reads `infra/k8s/argocd/applications/<env>.yaml` and patches exactly its `spec.syncPolicy` plus the annotation's removal (with `resourceVersion`). The restored policy equals the git manifest's for both envs → FAIL, implement → PASS. Commit
- [ ] [AC3] Test: after the policy patch, the close issues one sync `operation` on the Application (a re-enabled policy alone does not restore replicas under `selfHeal: false`), then waits for Synced/Healthy and the declared replicas, and exits non-zero with what it saw on timeout. Closing with no annotation exits 0 with "no window open" → FAIL, implement → PASS. Commit
- [ ] [AC1] [AC3] CLI `toolkit backup restore-window --app --env [--end]`, plus `make restore-window APP= ENV= [END=1]` (Makefile help line, env-default table). The open prints the replaced policy, and the close prints the policy it replaced. Commit
- [ ] [AC5] Test + implement `toolkit infra argo check-window` (exit 1 naming the holder when any Application carries the annotation), called by `deploy-apps` before its `kubectl apply`. Commit
- [ ] [AC6] Runbook: the Postgres (line ~333) and Authelia/n8n (line ~484) sections open the window before replacing data and close it after. Remove the "#1998 is the fix; until it lands" text. Commit
- [ ] [AC1] [AC2] [AC3] Live on staging: open `APP=n8n ENV=staging`, read back the Application and Deployment, try a second open (refused), close, read back Synced/Healthy and 1/1. Record the output in `verification.md`

## Closing

- [ ] Every acceptance criterion from `proposal.md` is covered by at least one test
- [ ] Every acceptance criterion has a matching entry in `features.json` (see below) with a non-vacuous verification command
- [ ] Type checks pass
- [ ] Lint passes
- [ ] No unrelated changes in the diff (no scope creep)
- [ ] `verification.md` filled in
- [ ] PR opened referencing this spec folder

## Machine-readable features

This spec emits a sibling `features.json` (alongside this file) following [[pattern-feature-list-as-primitive]]. The JSON is the harness-facing contract: each acceptance criterion maps to ≥1 feature with `id`, `behavior`, `verification` (executable command), `state` (lifecycle), and `evidence` (harness-captured output).

**Pass-state gating:** the agent CANNOT write `"state": "passing"` — only the harness, after running `verification` and capturing exit code 0, may set that terminal state. Reviewers must reject PRs where features.json contains `passing` entries with empty `evidence`.

Minimal `features.json` skeleton (drop into `<repo>/specs/BACKUP-070-restore-window/features.json`):

```json
[
  {
    "id": "BACKUP-070-restore-window-f1",
    "behavior": "<one-line copy of an acceptance criterion>",
    "verification": "<single shell command; exit 0 means pass>",
    "state": "pending",
    "evidence": ""
  }
]
```
