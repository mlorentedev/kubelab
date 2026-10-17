---
id: lesson-002-gh-pr-edit-fails-on-a-projects-classic-field-
type: lesson
status: active
created: "2026-08-17"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, gh-cli, github, tooling, projects-classic, verify-after-write, pr-1112, pr-1122]
---

# `gh pr edit` fails on a Projects-classic field, applies nothing, and blames Projects

**Context**: Three separate tasks across two sessions needed `gh pr edit` — setting a PR body (#1112), adding an assignee (#1122), adding a label (#1119-#1121). All three failed the same way, and in the first case the failure was not noticed until much later: #1112 shipped with the wrong body.

**Problem**: The command prints

```
GraphQL: Projects (classic) is being deprecated in favor of the new Projects experience,
see: https://github.blog/changelog/2024-05-23-sunset-notice-projects-classic/.
(repository.pullRequest.projectCards)
```

and exits 1. It is easy to read that as deprecation noise about a feature you were not using — the message names `projectCards`, not the field you were editing. It is not noise. `gh pr edit` **reads the PR before mutating it**, and its read query requests `repository.pullRequest.projectCards`, which the API now refuses. So it dies at the read step and **your edit never happens**. Measured on `gh 2.46.0`: `gh pr edit <n> --add-assignee <user>` → exit 1 with that message, then `gh pr view <n> --json assignees` → `0`. The same applies to `--body` and `--add-label`.

The scope is narrower than "the `gh` porcelain is broken", and the narrowing matters because it decides what you may still use. **`gh issue edit` is unaffected** — verified in the same session, `gh issue edit <n> --add-label debt` → exit 0 — because its query does not ask for `projectCards`. So do not route issue edits through the API on account of this; only PR edits.

**Solution**: use the REST endpoint for the specific field.

| Instead of | Use |
|---|---|
| `gh pr edit <n> --body ...` | `gh api -X PATCH repos/OWNER/REPO/pulls/<n> -F body=@body.md` |
| `gh pr edit <n> --add-assignee <user>` | `gh api -X POST repos/OWNER/REPO/issues/<n>/assignees -f 'assignees[]=<user>'` |
| `gh pr edit <n> --add-label <label>` | `gh api -X POST repos/OWNER/REPO/issues/<n>/labels -f 'labels[]=<label>'` |

A PR is an issue for these two endpoints, hence `/issues/<n>/` for both.

**Rule**: **An error that names a subsystem you were not using is still an error about your command.** The instinct to classify it as unrelated noise is what let #1112 ship with an unchanged body — the operation looked like it had failed harmlessly, when it had failed *and* left the thing you wanted undone. When a write tool errors, read the field back before believing anything about what landed; a non-zero exit tells you something went wrong, never which half.

**Tags**: `#gh-cli` `#github` `#tooling` `#projects-classic` `#verify-after-write` `#pr-1112` `#pr-1122`
