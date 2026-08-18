---
id: lesson-316-rebasing-a-pr-onto-another-pr-s-pre-merge-bra
type: lesson
status: active
created: "2026-08-12"
owner: manu
tags: [kubelab, lesson, git, squash-merge, rebase, merge-conflict, cross-session-coordination, gotcha]
---

# Rebasing a PR onto another PR's pre-merge branch tip conflicts against the real post-squash master

**Context:** #1019 depended on #1015 (both touched the tail of `docs/lessons.md`). Once #1015 merged, a peer session rebased #1019's branch onto #1015's original branch tip (`54c1254`) to resolve the shared conflict, resolved it cleanly, force-pushed — and reported #1019 mergeable.

**Problem:** GitHub reported #1019 as `CONFLICTING`/`DIRTY` anyway. This repo squash-merges every PR (ADR trunk-based rule), so `master`'s actual tip after #1015 was a *new* commit (`e0fb86f`) with `master`'s pre-#1015 tip as its parent — `54c1254` was never one of its ancestors, despite carrying identical file content. `git merge-base origin/master origin/<branch>` therefore resolved to the commit *before* #1015's change on both sides, not to `54c1254`/`e0fb86f`. From that base, git saw both `master` and the rebased branch independently inserting the same `docs/lessons.md` entry — a real conflict, confirmed by reproducing the merge in a scratch clone (`git merge-base --is-ancestor 54c1254 origin/master` → `NO`).

**Solution:** Merged current `origin/master` into the PR branch (not another rebase) — a squash-merged base only needs to be picked up once, and a merge commit is squashed away at final merge anyway so it costs nothing. Resolved the now-trivial conflict (branch content already had everything `master`'s side lacked), verified with `markdownlint`, pushed as a normal fast-forward (`350a541`, no force needed). `mergeable` flipped `CONFLICTING` → `MERGEABLE`.

**Rule:**
- **After a dependency PR squash-merges, rebase the dependent branch onto the new `master` tip — never onto the source branch's pre-merge commits.** They carry the same file content but are not the same commit; git's 3-way merge cares about ancestry, not content equality.
- **`mergeable: CONFLICTING` from the GitHub API is ground truth — a peer's local conflict-resolution success is not,** if that resolution happened against a branch tip that never reached `master`. Verify against `origin/master`, not against the branch that was rebased onto.
- **Once truly caught up, prefer a merge commit over a second rebase to reconcile a dependent branch.** It avoids a second force-push (and the coordination risk of two sessions racing on the same ref) and gets squashed away regardless at merge time.

**Tags:** `#git` `#squash-merge` `#rebase` `#merge-conflict` `#cross-session-coordination` `#gotcha`
