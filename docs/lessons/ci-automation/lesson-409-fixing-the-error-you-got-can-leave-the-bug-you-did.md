---
id: lesson-409-fixing-the-error-you-got-can-leave-the-bug-you-did
type: lesson
status: active
created: "2026-08-31"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, github-actions, gh-cli, dependabot, verify-after-write, ci-gate-016]
---

# Fixing the error you got can leave the bug you did not reach

**Context**: CI-GATE-016 (#1494). Five Dependabot PRs — #1486 to #1490 — red on
`declare` and on `review-attestation`, which is a required check. The `declare`
log ends with `failed to run git: fatal: not a git repository` on
`gh pr edit "$PR_NUMBER" --add-label "$LABEL"`, and the fix is already written
down elsewhere in this harness: dotfiles' `pat-expiry.yml` sets
`GH_REPO: ${{ github.repository }}` for exactly this, with a comment calling it
"the latent bug that silently broke this preflight since it shipped"
(lesson-134, ADR-031).

**Problem**: That one-line fix is correct *and* insufficient, and the
insufficiency is invisible from the log. Once the command can resolve a
repository it does the next thing it was never able to do: `gh pr edit` reads
the PR before mutating it, with a GraphQL query that requests
`repository.pullRequest.projectCards`, and this repository's API refuses that
field since the Projects-classic sunset — so the edit still does not happen.
`lesson-002` and `lesson-338` already record it, measured on gh 2.46.0, the
version still in use here. The two failures sit in one call chain and the first
hides the second: adding `GH_REPO` alone turns "fatal: not a git repository"
into "Projects (classic) is being deprecated", and the escape label lands as
often as before, which is never.

The structural half: `tests/test_dependabot_declaration.py` asserted this
workflow's *intent* in six tests — the actor guard, the registry read, the
permissions, the untrusted-body shape — and all six stayed green while the
workflow applied its label zero times in a week. A string-presence test proves
a file says something. Only reading the consequence back proves it happened.

**Solution**: the job writes PR fields through REST only, additively, and
verifies by consequence:

```bash
gh api -X POST "repos/${GITHUB_REPOSITORY}/issues/${PR_NUMBER}/labels" \
  -F "labels[]=${LABEL}" --silent
have=$(gh api "repos/${GITHUB_REPOSITORY}/issues/${PR_NUMBER}/labels" --jq '.[].name')
if printf '%s\n' "$have" | grep -qxF "$LABEL"; then
  echo "declared: '$LABEL' is on PR #${PR_NUMBER}"
else
  echo "::error::escape label '$LABEL' absent after the write (…)"; exit 1
fi
```

`POST /issues/<n>/labels` appends; `PUT` replaces the whole set and would drop
the `dependencies` / `toolkit` labels Dependabot applied. Guards added first and
observed red against the pre-fix workflow: `tests/test_gh_repo_context.py` (a
checkout-less job may not call a porcelain `gh` subcommand without `GH_REPO`),
plus two in `tests/test_dependabot_declaration.py` — the read-back exists, and
no `gh pr edit` survives in the declaring job.

**Rule**:

- **An error names the stage that failed, not the stages behind it.** Before
  calling a fix complete because it explains the log, search the stored lessons
  for the *command*, not for the error text — `gh pr edit` has two documented
  failures on this repository and only one of them was printing.
- **A disclosure automation must assert its own effect.** Exit 0 from a write
  means the write was attempted. Read the artefact back and fail naming the
  artefact (precedent: `pr-agent.yml`, "Fail if no review was published", #1180).
- **A red gate on a bot's PR is the weakest signal in the system**: readers
  scroll past it, and a week of it looked like policy, not breakage. Put the
  verification inside the job that is supposed to have acted, so it goes red
  with its own cause instead of leaving the blame on the pull request.

**Tags**: `#github` `#gh-cli` `#github-actions` `#dependabot` `#verify-after-write` `#ci-gate-016`
