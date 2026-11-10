---
id: lesson-728-a-sharded-check-trades-test-time-for-runner-wait
type: lesson
status: active
created: "2026-11-09"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, github-actions, pytest]
---

# A sharded check trades test time for runner wait, so measure the two apart

**Context**: #3111 split `Tests` into three shard jobs and one aggregate job. AC2 of #3078 asked for a `Tests` p50 of 10 min or less over 20 pull request runs.

**Problem**: Taken over every PR run since the merge (139 samples), the p50 was 14.1 min. That looked like a sharding failure, and it was not one. The slowest shard's own duration stayed at about 7 min in every window. The extra time was runner wait: shards that did not start together, and an aggregate job that did not start when the last shard finished. That wait came from 2026-11-06 (UTC), when five unattended sessions had PRs open together. Sharding had turned one job per PR into four, so the hosted runners' concurrent job limit filled four times as fast. Over the first 20 runs the p50 was 15.4 min. Over the last 20, with normal load, it was 8.6 min.

**Solution**: `toolkit tools tests-p50 --since <ISO>` (`make tests-p50 SINCE=<ISO>`) measures each run from the first shard's start to `Tests` completion. It reports views into that time that overlap: the slowest shard (the suite), the skew between shard starts, and the wait before `Tests` starts. They are not summed: wall = shard phase + wait + `Tests` own time, and prints the first, last and whole windows. It also reports the queue before the first shard and the aggregate job's own time, and counts the runs it dropped. Cancelled runs cluster in saturated windows, so dropping them makes such a window read better than it was. Printing all three keeps one window, chosen after seeing the numbers, from standing in for the result. The saturation finding is #3223.

**Rule**: When a critical-path job is split into parallel jobs, its wall time no longer depends only on the suite. Report the run time and the runner wait separately, and report every window, not only the one that passes. More jobs per PR buy a shorter suite only while the runners have free capacity.

**Tags**: `#github-actions` `#sharding` `#issue-3078`
