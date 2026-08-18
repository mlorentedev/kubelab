---
id: lesson-258-revert-ad-hoc-commits-in-a-feature-branch-to-
type: lesson
status: active
created: "2026-05-19"
owner: manu
tags: [kubelab, lesson, git, pr-hygiene, workflow, scope-management]
---

# Revert ad-hoc commits in a feature branch to keep PR scope atomic (alternative to interactive rebase + force-push)

**Context:** During PR3a (DASH-DT-014a) the working branch had accumulated an earlier commit (`88cea7a`) that introduced ad-hoc `vps_services` and `rpi4_services` Ansible roles. That commit belonged to the planned PR3b (DASH-DT-014b) scope, not PR3a. Leaving it in PR3a would have meant ~190 LOC of code that PR3b would immediately delete — wasteful for the reviewer and confusing for the post-merge history.
**Problem:** Three options were on the table: (a) `git revert 88cea7a` adds a visible revert commit; (b) interactive rebase to drop the commit + `git push --force-with-lease`; (c) keep the commit and merge a bloated PR. Option (b) is the "cleanest" history but destructive on remote — requires force-push to an already-pushed branch. The default CLAUDE.md instructions discourage force-push without explicit user consent.
**Solution:** Use `git revert <commit>` (option a) as the non-destructive default. The branch ends with extra commits (original + revert) but the net diff vs master is identical to what option (b) would produce. Critically: when the PR is squash-merged (kubelab default), all branch-intermediate commits collapse into one — the final history in master is identical for both option (a) and option (b). For squash-merge workflows, revert is strictly better: zero force-push risk, no rewrite of pushed history, and the revert commit itself is a useful audit trail showing intent ("this code intentionally not in PR3a").
**Tags:** `#git` `#pr-hygiene` `#workflow` `#scope-management`
