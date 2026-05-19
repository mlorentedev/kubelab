---
tags: [spec, verification]
created: "2026-05-18"
---

# Verification - TOOL-006-argo-revision-cli

## Evidence

- [x] AC1 (CLI patches + prints old→new + sync) -> commit `6ec6874`, tests `TestArgoSetRevisionCLI::test_happy_path_prints_old_and_new`, `TestSetRevisionHappyPath::test_returns_old_and_new_revision`. Live smoke output:

  ```
  [INFO] targetRevision: fix/dash-ui-cosmetic → master
  [INFO] sync status: Unknown
  [SUCCESS] Application patched
  ```

- [x] AC2 (`make argo-set-revision` exits 0 on success) -> commit `6ec6874`, smoke test executed `make argo-set-revision APP=kubelab-staging REV=master` against hub aws1, exit code 0.
- [x] AC3 (missing app: clean error + non-zero) -> commit `6ec6874`, tests `TestSetRevisionErrors::test_missing_application_raises` (feature layer) + `TestArgoSetRevisionCLI::test_missing_app_exits_nonzero` (CLI layer).
- [x] AC4 (missing --app/--rev: typer usage + non-zero) -> commit `6ec6874`, test `TestArgoSetRevisionCLI::test_missing_required_args_exits_nonzero`. Manual: `env -u APP -u REV make argo-set-revision` prints `Usage: make argo-set-revision APP=kubelab-staging REV=master`, exits 1.
- [x] AC5 (unit tests: happy-path + missing-app + CLI validation) -> 7 tests in `tests/test_argo_manager.py`, all passing.
- [x] AC6 (smoke test on live hub closes drift) -> executed 2026-05-18 20:43 MDT. Pre-state: `targetRevision=fix/dash-ui-cosmetic`, `sync=Unknown` (5-day drift from PR #171 preview never reverted). Post-state: `targetRevision=master`, `sync=Synced`. Verified via `kubectl ... get application kubelab-staging -o jsonpath='{.spec.source.targetRevision}'`.
- [x] AC7 (`make help` shows new target) -> commit `6ec6874`. `make help | grep argo-set-revision` returns: `make argo-set-revision APP=x REV=y  Patch Application targetRevision (preview/patch-back)`.

## Test status

- Test suite: `poetry run pytest tests/ --ignore=tests/e2e --ignore=tests/infra` -> **91 passed in 1.83s** (84 pre-existing + 7 new for TOOL-006).
- Manual smoke test: live hub patch executed; closed the inherited drift from PR #171 (`fix/dash-ui-cosmetic` → `master`). Sync state transitioned `Unknown` → `Synced` within ~1s after patch.
- No regressions: all 84 pre-existing unit tests still pass.
- Type checks: `mypy toolkit/features/argo_manager.py toolkit/cli/infra.py` -> clean.
- Lint: `ruff check` -> clean.

## Decisions made during implementation

- **2 kubectl calls instead of 3.** The PATCH command with `-o json` returns the updated Application object, so we don't need a separate GET after the patch. Trade-off: the sync status reported in the patch response is the *pre-reconciliation* value (Argo's controller re-evaluates async), so the CLI's printed `sync status: Unknown` may lag the actual state by ~1s. Documented as "expected behavior" rather than fixed — a re-GET would add latency without changing the outcome. Confirmed during smoke test: immediate re-query showed `Synced` while CLI output said `Unknown`.
- **Dataclass `SetRevisionResult` over plain tuple/dict.** Makes the CLI test pure (no subprocess) by mocking only the feature function. Tradeoff: extra type definition. Justified by testability — CLI test would otherwise duplicate subprocess setup.
- **Pre-flight `kubectl get` before patch.** Rejected fast-failing on patch error alone — that path produces a generic "exit 1" without an actionable message. The pre-flight costs one extra round-trip but yields `Application 'X' not found in namespace argocd` which is parseable by humans and future automation.
- **No SSOT pull for kubeconfig path.** Used env var `KUBECONFIG_HUB` with `~/.kube/kubelab-hub-config` default (matches existing `k8s_secrets.py` pattern). Pulling from `common.yaml` would have required loading the full config tree for one path — over-engineered for one wrapper.

## Promotion candidates

- [x] Lesson for `kubelab/90-lessons.md`? **Yes** — codify the Argo CD targetRevision swap workflow (preview-per-PR + patch-back) now that it has a stable Makefile/toolkit entry point. Future operator should reach for `make argo-set-revision` reflexively rather than `kubectl patch`.
- [ ] ADR-worthy decision? **No** — operational tooling, not architecture.
- [ ] New `00_meta/patterns/`? **No** — kubelab-specific (aws1 hub, argocd namespace). General "encapsulate kubectl in CLI" is already implicit in `feedback_no_manual_kubectl`.

## Archive checklist (post-merge)

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/TOOL-006-argo-revision-cli/` -> `specs/archive/TOOL-006-argo-revision-cli/`
- [ ] Backlog entry in vault `11-tasks.md` ticked with PR link
- [ ] Lesson added to vault `kubelab/90-lessons.md` (see Promotion candidates)
