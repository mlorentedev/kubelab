---
tags: [spec, tasks]
created: "2026-05-18"
---

# Tasks - TOOL-006-argo-revision-cli

> TDD order. One task = one focused commit. Tick as you go. Frozen on entry to `implementing` state.

## Setup

- [x] Branch created from master: `feat/tool-006-argo-revision-cli`
- [x] `proposal.md` complete with testable acceptance criteria
- [x] No unresolved questions in `proposal.md`

## Implementation

> TDD order: failing test first, then minimal implementation. One commit per ticked pair.

- [ ] Add failing unit test: `set_revision` happy-path returns expected patch payload (`{"spec":{"source":{"targetRevision":"<rev>"}}}`).
- [ ] Implement `toolkit/features/argo_manager.py` with `set_revision(app, rev, kubeconfig)` invoking `kubectl patch application --type merge`. Capture old/new revision + sync status. Subprocess wrap following existing pattern.
- [ ] Add failing unit test: missing-application path returns `ApplicationNotFoundError` with the app name in the message.
- [ ] Implement pre-flight `kubectl get application NAME -n argocd` check; raise typed error mapped to non-zero exit.
- [ ] Add failing CLI test (Typer `CliRunner`): `toolkit infra argo set-revision --app X --rev Y` produces expected output lines and exit code.
- [ ] Wire `argo` Typer subcommand into `toolkit/cli/infra.py`. Reuse `KUBECONFIG_HUB` env var pattern from existing modules.
- [ ] Add Makefile target `argo-set-revision` with usage hint and dependency check (`@test -n "$(APP)"` / `@test -n "$(REV)"`).
- [ ] Update `make help` section (under Hub block) with one-line entry.

## Closing

- [ ] All acceptance criteria from `proposal.md` covered by ≥1 test.
- [ ] `make test` (or `pytest toolkit/`) passes.
- [ ] `mypy toolkit/features/argo_manager.py toolkit/cli/infra.py` clean.
- [ ] `ruff check` clean.
- [ ] No unrelated diff (Makefile + 2-3 toolkit files + tests + spec only).
- [ ] Smoke test on live hub executed (closes inherited drift); evidence captured in `verification.md`.
- [ ] `verification.md` filled with command outputs and commit hashes.
- [ ] PR opened linking this spec folder.
- [ ] On merge: `git mv specs/TOOL-006-argo-revision-cli specs/archive/TOOL-006-argo-revision-cli` + tick TOOL-006 in `11-tasks.md` with PR link.

## Machine-readable features

Deferred until after first failing test passes — keeps the JSON honest. To be created at `specs/TOOL-006-argo-revision-cli/features.json` with entries for each AC, mapping to actual pytest node IDs or shell commands.
