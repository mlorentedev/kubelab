---
id: lesson-241-2026-03-29-avoid-rebase-hell-one-branch-per-f
type: lesson
status: active
created: "2026-05-01"
owner: manu
tags: [kubelab, lesson]
---

# 2026-03-29: Avoid rebase hell — one branch per file group, one PR at the end

**Symptom:** 4 consecutive PRs touching values.yaml, each needing rebase before merge.

**Root cause:** Squash merge changes master → next branch diverges from same file.

**Rule:** When iterating on the same file/component, accumulate all fixes in one branch. Create the PR only when done. Don't fragment into micro-PRs touching the same file.
