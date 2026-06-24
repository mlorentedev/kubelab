---
id: "TOOL-006-argo-revision-cli"
type: spec
status: archived # draft | implementing | verifying | archived
created: "2026-05-18"
tags: [spec, proposal]
template_version: "1.0"
---

# TOOL-006-argo-revision-cli

## Why

Argo CD `targetRevision` swaps are a recurrent operation in this repo: previewing a PR on staging requires pointing the `kubelab-staging` Application at the feature branch, and patching it back to `master` after merge. Today both operations are manual `kubectl patch application` calls, which violates `feedback_no_manual_kubectl` and `feedback_never_adhoc_commands`. The 2026-05-13 preview of PR #171 left staging anchored to `fix/dash-ui-cosmetic` after merge — the patch-back was skipped because no Makefile/toolkit target existed. The drift went undetected for 5 days. Closing this gap stops both this incident and the next one.

## What

Two new entry points:

1. `poetry run toolkit infra argo set-revision --app NAME --rev REF` — Typer subcommand that resolves the hub kubeconfig, verifies the Application exists in namespace `argocd`, patches `spec.source.targetRevision` to `REF`, and prints the before/after revision plus the current sync state.
2. `make argo-set-revision APP=NAME REV=REF` — thin Makefile wrapper around the above so the command surfaces in `make help` and follows the project's "always go through Makefile" rule.

Both commands target the hub cluster (aws1) only.

## Out of scope

- `status` and `list-apps` subcommands (separate future TOOL-XXX once needed).
- Preview-per-PR ApplicationSet automation (ADR-pending; out of this spec's surface).
- Validating that `REF` exists on the remote git source (Argo CD surfaces broken refs on next sync; pre-checking adds latency without preventing user error).
- Spoke clusters (this spec targets the hub Application list only; spoke targeting would require kubeconfig switching logic).
- Rolling back the revision atomically if the patch succeeds but sync fails (Argo CD self-heal handles that domain).

## Risks / open questions

- **Hub kubeconfig discovery**: existing convention is `~/.kube/kubelab-hub-config` (per lessons). RESOLVED: use `KUBECONFIG_HUB` env var with that path as default; matches the existing toolkit patterns in `cli/monitoring.py` and `cli/infra.py`.
- **`kubectl` invocation**: 5 toolkit modules already shell out to `kubectl` via `subprocess`. RESOLVED: follow the same pattern; do NOT introduce a Python K8s client dependency just for one `patch` call.
- **Error UX when Application is missing**: pre-flight `kubectl get application NAME -n argocd` for a clean error message before attempting the patch.

## Acceptance criteria

- [ ] `poetry run toolkit infra argo set-revision --app kubelab-staging --rev master` patches the Application and prints lines like `targetRevision: fix/dash-ui-cosmetic → master` plus the current `status.sync.status` value.
- [ ] `make argo-set-revision APP=kubelab-staging REV=master` invokes the toolkit subcommand and exits 0 on success.
- [ ] Running against a non-existent app prints `Application '<name>' not found in namespace argocd` and exits with non-zero code.
- [ ] Running the CLI without `--app` or `--rev` prints Typer usage and exits non-zero.
- [ ] Unit tests cover: happy-path patch payload construction, missing-application error path, CLI argument validation.
- [ ] Smoke test on live hub: `make argo-set-revision APP=kubelab-staging REV=master` closes the inherited drift; `kubectl --kubeconfig ~/.kube/kubelab-hub-config get application kubelab-staging -n argocd -o jsonpath='{.spec.source.targetRevision}'` returns `master`.
- [ ] `make help` shows the new target with a one-line usage hint.

## References

- Vault: `10_projects/kubelab/11-tasks.md` (TOOL-006 entry, line 349)
- Lesson: `90-lessons.md` — Argo CD targetRevision swap pattern (Option A preview), already documents the `kubectl patch` payload this command encapsulates.
- Related memory: `feedback_no_manual_kubectl.md`, `feedback_never_adhoc_commands.md`, `feedback_use_makefile.md`.
- Existing toolkit kubectl-wrap pattern: `toolkit/cli/monitoring.py`, `toolkit/cli/infra.py`.
