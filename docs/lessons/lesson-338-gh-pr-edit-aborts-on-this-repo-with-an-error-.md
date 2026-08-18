---
id: lesson-338-gh-pr-edit-aborts-on-this-repo-with-an-error-
type: lesson
status: active
created: "2026-08-15"
owner: manu
tags: [kubelab, lesson, github, gh-cli, tooling, gotcha]
---

# `gh pr edit` aborts on this repo with an error about a board, and leaves the body unchanged

**Context:** editing a PR description here with `gh pr edit <n> --body-file f` exits non-zero with:

```
GraphQL: Projects (classic) is being deprecated in favor of the new Projects
experience [...] (repository.pullRequest.projectCards)
```

**The trap:** the error names *Projects*, so it reads as a board-metadata problem, incidental to the edit. It is not — the body silently does not update. Confirmed by grepping the fetched body for the new text: 0 matches before the workaround, 1 after. An agent that reads the error, concludes "that's just the deprecated board", and moves on has left the PR description stale while believing it published.

**Fix:** the REST endpoint has no such coupling.

```bash
gh api -X PATCH repos/<owner>/<repo>/pulls/<n> -F body=@body.md
```

The same `-F body=@file` form repairs an issue or comment body (`.../issues/<n>`), which is also the remedy when zsh has eaten backticks out of a `--body` string.

**Rule:**
- **Verify a write landed by reading it back, not by reading the exit path.** This one failed loudly *and* partially: an error was printed, and it pointed at the wrong subsystem.
- **Prefer `gh api` over the porcelain for body writes.** `gh pr edit` bundles unrelated GraphQL calls; the REST endpoint does exactly one thing.

**Tags:** `#github` `#gh-cli` `#tooling` `#gotcha`
