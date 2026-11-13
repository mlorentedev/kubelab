---
id: lesson-744-prune-by-disk-pressure-not-by-calendar-and-until-reads-the-build-date
type: lesson
status: active
created: "2026-11-13"
owner: manu
category: containers-docker
tags: [kubelab, containers-docker, ci, maintenance, beelink]
---

# Prune Docker by disk pressure, not by calendar, and `until` filters on the build date

**Context**: `node_maintenance` runs `docker image prune -af` and `docker builder prune -af` every day on every Docker host. The Beelink runs the forge's CI and an hourly Renovate engine.

**Problem**: Every morning the Beelink started cold. Its first jobs re-downloaded TeXLive (2.31 GB, 1,741 s against 1.5 s warm) and the runner image (5 min against 0.3 s), and rebuilt the dev image (142 s against 2 s) (#3079). The same prune deleted the Renovate engine between its `--rm` runs (#3403). The disk was 42 % full, so the prune bought nothing on those days.

The obvious fix, `--filter until=168h`, does not work. `docker image prune` compares `until` with the image's own `Created` time, which is when the publisher built it, not when this node pulled it. A two-week-old upstream image is removed on the first prune after a fresh pull. The other prune filter, `label`, matches labels inside the image, which nobody here sets on upstream images. So a keep-list cannot be a prune flag.

**Solution**: `maintenance_docker_prune_above_percent`. On `platform_nodes` (the Beelink) it is 70, under the 80 % disk alert; everywhere else it is 0, which keeps the full prune. When it is above 0, `-a` applies only once the filesystem holding Docker's root reaches it. Below it, only dangling images and dangling build cache go. An unreadable `df` prunes everything. The script and the Ansible twin share the gate. `tests/test_node_maintenance_docker_cleanup.py` runs the rendered block against stub `docker` and `df`. The Renovate engine keeps its holder container (#3414), because a disk at threshold still prunes.

**Rule**: Clean up on a resource signal, not on a schedule. Pruning a cache that has room only adds a cold start. This is how the kubelet treats images (`imageGCHighThresholdPercent`). Before using a time filter, check whether the timestamp it reads means what you assume.

**Tags**: `#docker` `#issue-3079` `#issue-3403`
