---
id: lesson-322-a-cleanup-step-that-reverts-more-than-the-ste
type: lesson
status: active
created: "2026-08-12"
owner: manu
tags: [kubelab, lesson, makefile, destructive, git, ssot, drift-check, tool-031, gotcha]
---

# A cleanup step that reverts more than the step wrote is a destructive op wearing a check's clothing

**Context:** `make config-check-drift ENV=<env>` regenerates config into the working tree, diffs it against the committed files, then cleans up after itself. Run mid-PR to prove that new `common.yaml` fields did not change any generated ConfigMap.

**Problem:** It reported `✓ No drift` and, in the same breath, deleted the hand-written edits it had just been run to validate.

`Makefile:259`:

```make
git checkout -- infra edge 2>/dev/null || true; \
```

The comparison immediately above it is scoped to exactly three files. The cleanup is scoped to two entire top-level trees. So the target already knows precisely which paths it dirties — the revert simply does not use that knowledge, and `infra/config/values/*.yaml`, the repo's declared source of truth and hand-edited by definition, sits inside the blast radius.

Two details turn a rough edge into a trap. `2>/dev/null || true` means the step cannot fail and cannot warn, so there is no output distinguishing "reverted the two files I generated" from "reverted your unstaged SSOT edit". And `git checkout --` on unstaged changes leaves no reflog entry and no stash: it is the one git operation with no undo.

The workflow it punishes is the correct one. Running the drift check *before* committing is the entire point of the check; the target is safe only if you have already committed, which inverts its purpose.

**Solution:** Filed as #1034 rather than fixed inline, to keep the PR to one concern. The fix is the same shape as OPS-016's: derive the revert set and the diff set from **one** declaration instead of maintaining two.

Recovery was cheap only by accident — the edits had been applied by a script rather than typed, so re-running it restored them exactly. That is not a safety property, it is luck that happened to hold.

**Rule:**
- **Scope a cleanup to what the step actually wrote, never to the tree it wrote into.** "Revert the directory" is not a conservative choice; it is the widest possible one, and it silently includes files the step never touched.
- **This is the sixth instance of one shape: a declared set and an applied set maintained separately.** `WRITABLE_FIELDS` (#986) was the fifth. When two lists must agree, make them one object — the drift is invisible precisely because both halves look correct in isolation.
- **Commit before running any target whose recipe contains `git checkout`, `git clean`, or `git restore`.** Grep the Makefile for those verbs before trusting a target with uncommitted work; here exactly one target had one, and one was enough.
- **A step that cannot fail cannot be audited.** `2>/dev/null || true` on a destructive operation removes the only signal that would have distinguished intended cleanup from collateral damage.

**Tags:** `#makefile` `#destructive` `#git` `#ssot` `#drift-check` `#tool-031` `#gotcha`

---
