---
id: lesson-608-a-workflow-that-stages-a-tools-output-by-name-misses-the-file-the-tool-learns-to-write
type: lesson
status: active
created: "2026-10-20"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, release, promotion, generated-files]
---

# A workflow that stages a tool's output by name misses the file the tool learns to write

**Context**: The `promote-errors` job in `release.yml` runs `toolkit deployment promote --app errors`, then opens the pin PR with `git add` naming two files: `common.yaml` and the kustomization. #2436 (closing #2430) taught the promote to also regenerate `infra/config/platform.json`, which records the blob hash of `common.yaml`.

**Problem**: The tool was fixed and the workflow was not. The regenerated manifest stayed in the runner's tree, so the errors 1.3.0 PR (#2542) opened red on `test_the_committed_manifest_matches_its_ssot`, both on `Tests` and on `Sync check (Windows)`. #2430 was closed on a local run of the tool, which wrote all three files, so its closing evidence never exercised the path that commits them. lesson-590 records that same local run as "a three-file diff identical to #2432".

**Solution**: #2552. `promotion.ERRORS_PROMOTION_FILES` declares every file the errors promote writes, and the promote derives its output paths from it. `tests/test_release_promote_errors.py` holds the job's single `git add` to exactly that list, and `TestPromoteErrors::test_writes_exactly_the_files_it_declares` holds the promote's writes to it. Dropping the manifest from either side goes red; the three mutations were proven with `make mutate`.

**Rule**: When a workflow commits what a tool wrote, the list of files is one declaration that both read, and a test ties each side to it. Verify a fix to such a tool through the workflow's own commit, not the tool's local output: the local run proves what was written, not what was committed.

**Tags**: `#release` `#promotion` `#platform-json` `#issue-2552` `#pr-2542`
