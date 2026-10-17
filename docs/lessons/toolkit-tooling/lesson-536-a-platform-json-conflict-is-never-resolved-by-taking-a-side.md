---
id: lesson-536-a-platform-json-conflict-is-never-resolved-by-taking-a-side
type: lesson
status: active
created: "2026-10-07"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, git, generated-files, ssot]
---

# A platform.json conflict is never resolved by taking a side

**Context**: rebasing #2102 onto a master that had moved while the PR was open.
Both sides had changed `infra/config/values/common.yaml`, and the rebase stopped
on a conflict in `infra/config/platform.json`.

**Problem**: the conflict was only in the `generated_at` and `source_commit`
lines, so it looked like timestamp noise. It was resolved with master's copy.
`make sync-platform-json` regenerated a file that differed from it in those same
two lines, and that diff was reverted as "only the timestamp". CI then failed
twice: `test_the_committed_manifest_matches_its_ssot` and the Windows sync check.
`source_commit` is not a commit. It is the git blob SHA-1 of `common.yaml`
(`compute_source_hash`, `toolkit/features/platform_manifest.py`). The rebased
`common.yaml` is a third blob, matching neither side, so neither side's
manifest can be current. `generated_at` is kept only while that hash still
matches, so the timestamp moving is the symptom of the hash moving, not noise.

**Solution**: run `make sync-platform-json` after the rebase and commit what it
writes, `source_commit` line included (5f71ead4). The same rebase left #2115's
manifest stale with no conflict at all, because only master's side had changed
the file there.

**Rule**: after any rebase or merge that brings in a change to `common.yaml`,
regenerate `platform.json` and commit the result, conflict or not. Never pick
`--ours` or `--theirs` for it, and never revert its `source_commit` line as
noise: that line is the check.

**Tags**: `#platform-json` `#rebase` `#generated-files`
