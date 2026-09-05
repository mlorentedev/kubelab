---
id: lesson-439-a-callers-permissions-block-is-a-ceiling-and-the-run-never-starts
type: lesson
status: active
created: "2026-09-05"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, github-actions, reusable-workflows, permissions, observability]
---

# A caller's `permissions:` block is a ceiling, and a run that breaks it never starts — so nothing turns red

**Context**: While scoping the staging churn (#1645) I checked which workflow had
opened each `chore(staging): deploy` pull request. Every one of the 104 came from
`web-image-receiver.yml`. Not one came from `staging-deploy.yml`, the staging lane
for `api`. It had run sixteen times since 2026-06-18 and its conclusion was
`startup_failure` all sixteen times (#1666).

**Problem**: Two separate failures, and the second is the expensive one.

The **defect** is a relation between two files. `staging-deploy.yml` declared

```yaml
permissions:
  contents: write
  pull-requests: write
```

and then called `ci-publish.yml`, whose `docker-build-push` job asks for
`security-events: write`. A caller's `permissions:` block is a **ceiling**: every
scope it does not name is `none`, and that applies to the workflows it calls.
GitHub refuses the run when it is created:

```
Invalid workflow file: .github/workflows/staging-deploy.yml#L46
Error calling workflow '.../ci-publish.yml@dced2265'. The nested job
'docker-build-push' is requesting 'security-events: write', but is only
allowed 'security-events: none'.
```

`actionlint` reports nothing, and it is right not to — each file is valid alone.
The defect exists only in the pair, so a single-file linter is structurally blind
to it. The fix was already in the repository: `release.yml` calls the same
reusable workflow and grants the scope. It had been correct for months and never
propagated, because nothing asserted the relation.

The **invisibility** is the other half. A `startup_failure` creates no job, so it
creates no check run, so there is nothing to annotate and nothing to go red.
Measured on run `32815342422`:

```
$ gh api repos/O/R/check-suites/88893127233/check-runs --jq .total_count
0
$ gh api repos/O/R/commits/dced2265/check-runs --jq '.check_runs|length'
0
```

The error above exists **only in the web UI**. Ten weeks of `apps/api/**` never
reaching staging produced no alert, no red check, and no failed pull request.

**Solution**: One line — `security-events: write` on the caller — and a guard for
the relation, `tests/test_reusable_workflow_permission_ceiling.py`, which walks
every local `uses:` call and compares what the callee's jobs request against what
the caller grants. Verified in three states: red against pre-fix master with
GitHub's own wording, green with the fix, red under a mutation that removes the
scope from `release.yml`.

A caller that declares **no** `permissions:` block is skipped rather than
assumed permissive — the repository default is a setting, not a fact in the tree,
and inventing one would either wave through a real violation or manufacture a
false one. That skip is not a gap; it is why `ci-pipeline.yml` has always worked.
It never declared a ceiling to fall short of.

**Rule**: When a workflow declares `permissions:`, it has capped every scope it
did not list — for itself **and** for everything it calls. Check the callee's
job-level requests against it, because no linter will: the fact lives between two
files.

And when a class of failure produces no job, stop expecting a check to report it.
`startup_failure` is reachable from `GET /actions/workflows/<file>/runs` as a
`conclusion`; the reason is not reachable at all. A delivery lane that can fail
this way needs something that reads that field on a schedule, or it fails in
silence for as long as nobody thinks to look.

**Tags**: `#github-actions` `#reusable-workflows` `#permissions` `#startup-failure` `#observability` `#pr-1683`
