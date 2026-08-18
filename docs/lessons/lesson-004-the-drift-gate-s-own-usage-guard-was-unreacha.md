---
id: lesson-004-the-drift-gate-s-own-usage-guard-was-unreacha
type: lesson
status: active
created: "2026-08-16"
owner: manu
tags: [kubelab, lesson]
---

# The drift gate's own usage guard was unreachable, so it checked the one environment nobody deploys

**Context**: BACKUP-044. The R2 offsite destination needed four non-secret values (account id, bucket, endpoint, repo prefix) in `common.yaml`. `infra.*` is the shared-services namespace (ADR-036), and a backup destination is shared infrastructure, so `infra.backup_r2` looked like the right home. Locally I ran `make config-check-drift`, saw `✓ No drift`, and pushed. CI failed on **both** `Drift / staging` and `Drift / prod`.

**Problem**: Two independent defects, and the second is what let the first reach CI.

1. **`infra.*` is not a namespace for arbitrary shared values — it is an injection point.** `generator_k8s.py:_extract_app_env_vars` flattens everything under `infra.` into `INFRA_*` keys and emits them into *every* component's ConfigMap, verbatim. Four backup-destination keys therefore rewrote the ConfigMap of every app in both overlays. The values were correct, the placement was not: ADR-036's contract is "values consumed by more than one *component*", and a restic destination consumed by an Ansible role on four nodes is not that. Fix was a one-line move to a top-level `backup.r2`.

2. **`make config-check-drift` with no `ENV` checked `dev` and reported green.** The target opened with `@test -n "$(ENV)" || (echo "Usage: ..." && exit 1)`, which reads as a guard. It is not one: `ENV ?= dev` lives ~700 lines further down the same Makefile, and a `?=` assignment is global regardless of position, so `$(ENV)` expanded to `dev` and `test -n "dev"` always passed. The usage message had never been printed. Verified after the fact: `make -n config-check-drift` emits `test -n "dev"`. Dev generates Docker Compose configs — it does not produce the K8s overlays CI diffs — so a dev-only run is structurally incapable of seeing the failure, and prints the same `✓` as a real one. `CONTRIBUTING.md` cited the bare form twice.

**Solution**: two attempts, and the first is the more instructive. #1118 replaced the guard with `@test "$(origin ENV)" = "command line"` — the only make construct that distinguishes "the caller passed this" from "it has a value" — and deliberately kept `ENV=dev` working. That moved the hole rather than closing it: `ENV=` also has command-line origin, and `ENV=dev` still routed straight into the vacuous case, because `git diff --quiet` over a pathspec that matches nothing exits 0. Provenance was never the property that mattered. 1122 validates the *value* instead, against a declared `DRIFT_ENVS := staging prod`, with `$(words)` rejecting the empty and multi-word forms that `$(filter)` alone would wave through. A static test asserts the recipe still guards through that variable, so the allow-list cannot be quietly widened back. CI already passed `ENV` per matrix env, so it was unaffected throughout. `CONTRIBUTING.md` now spells out both commands and the `INFRA_*` fan-out.

The same shape has a third instance in this very target, found while fixing the second and already filed as #1048: one of the three paths it diffs, `infra/ansible/generated/<env>/hosts.yml`, is gitignored and has never been tracked, so `git diff` cannot see it and CI-GATE-002's Ansible half was born vacuous. It stays in place, annotated rather than silently removed, because how inventory drift *should* be detected is a separate decision.

**Rule**: A guard on a variable that has a repo-wide default is not a guard, and tightening it to *where the value came from* is not enough either — validate the value against the set the gate can actually check, and declare that set as a variable a test can assert on. More generally: **when a gate can run against a target that cannot exhibit the failure, its green is not evidence.** Ask what the check ran *against*, not whether it passed; `✓ No drift` is a claim about one environment, and the default environment is the one that ships nowhere. In a `git diff`-based gate the specific trap is that a pathspec matching nothing — a wrong env, an untracked file — exits 0, which is indistinguishable from agreement. And before putting a value under `infra.*`, check ADR-036's actual contract: that prefix has a consumer (every ConfigMap), not just a meaning.

**Tags**: `#makefile` `#drift-gate` `#adr-036` `#ssot` `#false-green` `#ci-gate-002` `#backup-044` `#pr-1118` `#pr-1122`
