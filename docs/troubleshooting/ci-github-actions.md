---
id: "kubelab-troubleshooting-ci-github-actions"
type: troubleshooting
status: active
tags: [troubleshooting, kubelab, ci, github-actions, gh-cli, dependabot]
created: "2026-08-31"
owner: manu
---

# CI and GitHub Actions

Symptoms from workflow runs and from `gh` calls made inside them. Reasoning
lives in the linked lessons; this file is only where to look.

## A `gh` step dies with `fatal: not a git repository`

### Problem

A job that calls `gh pr …`, `gh issue …`, `gh run …` or `gh release …` fails in
seconds, before any API call, with:

```
failed to run git: fatal: not a git repository (or any of the parent directories): .git
```

### Cause

`gh` resolves the target repository from a git remote or from `GH_REPO`. It does
**not** read `GITHUB_REPOSITORY`. The job has no `actions/checkout`, so it has
neither.

### Fix

Set `GH_REPO: ${{ github.repository }}` at job level, or give the job an
`actions/checkout`. `tests/test_gh_repo_context.py` fails the suite if a
checkout-less job reaches for a porcelain `gh` subcommand without it.

Measured 2026-08-31 on #1486-#1490: this killed the step that applies the
`merged-unreviewed` escape label, so every Dependabot PR sat red on
`review-attestation` while the gate blamed the pull request. See
[`lesson-409`](../lessons/ci-automation/lesson-409-fixing-the-error-you-got-can-leave-the-bug-you-did.md).

## `gh pr edit` reports a Projects-classic error and changes nothing

### Problem

`gh pr edit <n> --body …`, `--add-label …` or `--add-assignee …` exits non-zero:

```
GraphQL: Projects (classic) is being deprecated in favor of the new Projects
experience … (repository.pullRequest.projectCards)
```

The field you were editing is unchanged.

### Fix

Write that field through REST — it does one thing and asks for nothing:

| Instead of | Use |
| --- | --- |
| `gh pr edit <n> --body-file f` | `gh api -X PATCH repos/OWNER/REPO/pulls/<n> -F body=@f` |
| `gh pr edit <n> --add-label L` | `gh api -X POST repos/OWNER/REPO/issues/<n>/labels -F 'labels[]=L'` |
| `gh pr edit <n> --add-assignee U` | `gh api -X POST repos/OWNER/REPO/issues/<n>/assignees -F 'assignees[]=U'` |

`POST` on `/issues/<n>/labels` appends. `PUT` replaces the whole set and drops
whatever Dependabot or a human had already applied. A PR is an issue for these
two endpoints. `gh issue edit` is unaffected — only PR reads ask for
`projectCards`.

Details in [`lesson-002`](../lessons/ci-automation/lesson-002-gh-pr-edit-fails-on-a-projects-classic-field-.md)
and [`lesson-338`](../lessons/ci-automation/lesson-338-gh-pr-edit-aborts-on-this-repo-with-an-error-.md).

## A Dependabot PR is red on `review-attestation`

**Check which half of the escape is missing.** The gate requires the label
`merged-unreviewed` **and** the `## Unreviewed merge rationale` body section,
never one alone, and `dependabot-declare-unreviewed.yml` writes both. If the
section is present and the label is not, the declaring job failed — read its
`declare` log; the two causes above are the ones recorded here so far.

Once both halves are on the PR, the gate recomputes on the `labeled` event and
publishes `NOT reviewed — unreviewed merge declared`. That is the honest green;
it is not a bypass, and the check stays in the durable record.
