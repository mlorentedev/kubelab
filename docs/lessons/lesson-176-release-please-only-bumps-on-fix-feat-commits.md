---
id: lesson-176-release-please-only-bumps-on-fix-feat-commits
type: lesson
status: active
created: "2026-03-22"
owner: manu
tags: [kubelab, lesson, ci, release-please, versioning]
---

# release-please only bumps on fix:/feat: commits — chore: is ignored

**Context:** Made changes to error pages HTML + middleware under a `chore:` commit. release-please didn't create a version bump. Had to add a separate `fix(errors):` commit touching `edge/errors/` for release-please to detect it.

**Rule:** If changes need a Docker image rebuild, use `fix:` or `feat:` prefix (not `chore:`). release-please ignores `chore:` for versioning.
**Tags:** `#ci` `#release-please` `#versioning`
