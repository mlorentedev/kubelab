---
id: lesson-713-a-sharded-required-check-must-run-when-a-shard-fails
type: lesson
status: active
created: "2026-11-05"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, github-actions, pytest, coverage]
---

# A required check that waits on a matrix must run when a shard fails, and each shard's coverage must leave the directory before the next run

**Context**: #3111 split the suite into three shards, one runner each. The required check `Tests` became a job that `needs:` the shards and combines their coverage.

**Problem**: There were two traps.

The first is in GitHub Actions. A job whose `needs:` failed is skipped by default, and branch protection treats a skipped required check as satisfied. So a red shard would have merged under a check that never ran. `merge-grant.yml`'s own `ci-green` says "passes or is skipped", so the merge grant would have accepted it too.

The second is in pytest-cov. It erases the coverage data in the working directory when a run starts, and that includes every `.coverage.*` file. Reproducing the three shards on one workstation, each shard's data deleted the previous one's. `coverage combine` then reported "Combined 1 file" and a 40% `TOTAL` against the real 76%, without any error.

**Solution**: `Tests` runs `if: always()`. Its first step exits 1 unless `needs.test-shards.result` is `success`, so a failed, cancelled or skipped shard turns it red. `tests/test_test_shards.py` asserts both, so the condition cannot be edited away quietly. On CI each shard is a fresh runner and uploads its `.coverage.shard-N` as an artifact. Locally, each shard's data has to be moved out of the tree before the next shard starts. Done that way, the three shards combined to exactly the single run's `TOTAL` (20362 statements, 4619 missed, 6070 branches, 547 partial).

**Rule**: When a required check aggregates other jobs, give it `if: always()` and make it fail on any `needs` result other than `success`. A skip there passes the check. And never trust a combined coverage figure without reading its "Combined N files" line: a lost data file never shows up as an error, only as a lower percentage.

**Tags**: `#github-actions` `#coverage` `#issue-3111`
