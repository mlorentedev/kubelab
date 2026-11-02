---
id: lesson-691-a-renovate-regex-that-ends-in-a-dollar-sign-matches-nothing-and-reports-success
type: lesson
status: active
created: "2026-11-02"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, renovate, testing]
---

# A Renovate regex that ends in a dollar sign matches nothing and reports success

**Context**: `renovate.json` existed for months with no engine to run it. #2931 added the workflow, and its first run finished green, opened two Galaxy PRs and created the Dependency Dashboard.

**Problem**: The dashboard listed no image. The debug log read `Matched 1 file(s) for manager regex` and then `No dependencies found in file`. Renovate compiles `matchStrings` without the multiline flag, so the pattern's trailing `$` matches only at the end of the file. `tests/test_renovate_image_coverage.py` was written to catch exactly this silence, and it compiled the pattern with `re.M`, a flag production never sets, so it passed with 29 matches while Renovate found 0.

**Solution**: Put the flag inside the pattern, `(?m)image:...`, and compile it in the test with no flags. A run of the pinned engine on a temporary branch, with `RENOVATE_DRY_RUN=extract` and `LOG_LEVEL=debug`, then reported `"regex": {"depCount": 29}`. #2931.

**Rule**: A test of a config another engine reads must compile it the way that engine does, adding nothing. A green run and a dashboard prove the engine ran, not that it read anything: read the detected dependencies per manager, and the extract-only dry run answers that before any PR opens.

**Tags**: `#renovate` `#testing` `#issue-2931`
