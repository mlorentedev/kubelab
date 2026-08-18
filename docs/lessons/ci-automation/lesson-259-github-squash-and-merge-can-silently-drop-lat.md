---
id: lesson-259-github-squash-and-merge-can-silently-drop-lat
type: lesson
status: active
created: "2026-05-19"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation]
---

# GitHub "Squash and merge" can silently drop later commits on a PR — verify post-merge content, not just merge status

**Context:** During PR #177 (SSOT-005 build_node_list refactor), Codex left a P2 review flagging that the new `dashboard.ping_url` schema hardcoded `100.64.0.3:11434`, duplicating the node's `tailscale_ip`. A fixup commit `b0abbf1` was pushed to the same branch introducing a `ping_target` schema with hard-fail validation; that commit lived on `origin/refactor/ssot-005-build-node-list` and was push-verified before the merge.
**Problem:** After PR #177 was squash-merged, master commit `d8e3139` contained only the original commit `5e86848`. The fixup `b0abbf1` did not land. The Codex review comment thread still pointed at the original code, and the new ping_target validation logic was missing from `toolkit/scripts/sync_homepage_config.py`. The defect was only detected later when the Beelink cockpit flip PR re-read the file and found the old schema. Lost work was not catastrophic (the fixup could be re-applied), but the assumption that "squash merge captures everything pushed to the branch" was wrong in this case. Possible cause: merge mode mis-selected, or a race between the fixup push and the merge operation, or a manual UI choice to merge a specific commit.
**Solution:** After every merge, especially when a Codex / reviewer comment prompted a fixup commit, verify the actual file content on master matches the expected post-fixup state — do not trust the merge status alone. Concrete check: `git show origin/master -- <changed-file> | grep -E "<expected-symbol>"` for at least one symbol that the fixup introduced. If the fixup is missing, re-apply it as a new commit on a follow-up branch and PR with a clear `re-apply Codex fix that did not land in #NNN squash` note. The cheap habit of grepping for a fixup-introduced symbol on master immediately post-merge would have caught this in seconds instead of hours.
**Tags:** `#git` `#github` `#pr-hygiene` `#merge` `#review` `#verification`
