---
id: lesson-302-the-same-linter-behind-two-gates-in-different
type: lesson
status: active
created: "2026-08-09"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling]
---

# The same linter behind two gates in different environments is two linters — and only the lenient one was running (CI-GATE-005/006)

**Context:** Rebasing #865 and re-running the local gate showed `make type` failing on `toolkit/features/notify_smoke.py` — missing `types-requests` stubs. The obvious suspicion was the rebase, since master had just moved mypy `^2.1 → ^2.3`. Checking out `master` and running `make type` there reproduced the identical error, so it was not the rebase and not the bump. It had been red for a while: the `requests` import dates from #670.

**Problem:** mypy runs behind two gates in this repo, and they do not agree.

| Gate | Environment | `types-requests` | Extra args |
| --- | --- | --- | --- |
| `make type` | the project venv (`pyproject.toml`) | absent | none |
| pre-commit `mirrors-mypy` | its own isolated env | present via `additional_dependencies` | `--ignore-missing-imports` |

`[tool.mypy]` overrides `ignore_missing_imports` for `sh`, `yaml`, `argon2`, `uptime_kuma_api` — not `requests`. So the venv had neither the stubs nor a suppression, while pre-commit had both. Every commit passed; the documented pre-push gate had been failing on an untouched tree the whole time.

The second, larger question is why nobody tripped over it. Because nothing ever ran it: `.github/workflows/ci.yml` has four jobs — branch-name regex, `yamllint` on the workflow dir, `make -n help`, and the two path-filtered app pipelines. **No CI job runs pytest, ruff, or mypy over `toolkit/`.** The PR that surfaced this changes only toolkit code, and all nine of its checks were green while its test suite never executed in CI. The first failure was invisible because the only gate that would have caught it does not exist.

**Solution:** Add `types-requests` to the dev dependency group (#903) so the venv matches what pre-commit already supplies. Real stubs rather than widening the `ignore_missing_imports` list — the calls then get type-checked instead of skipped, and they pass, so the annotations were correct all along and merely unverified. `make check` now completes all four legs; it had been aborting at `type` and never reaching `test` or `validate-sync`. The missing CI gate is filed separately as CI-GATE-006 because choosing what CI should run is a design call, not a fix.

**Rule:** When the same tool is configured in two places, treat them as two tools until proven identical — an isolated hook environment with its own dependency list and its own flags is not the environment your Makefile uses, and the discrepancy surfaces as "works for me". Corollary: a gate whose failure nothing observes will eventually be red, so before trusting a green check, ask which command it actually ran. Green checks on a PR are evidence about the checks that ran, not about the code.

**Tags:** `#mypy` `#pre-commit` `#ci` `#tooling` `#silent-failure` `#ci-gate-005` `#ci-gate-006` `#gotcha`
