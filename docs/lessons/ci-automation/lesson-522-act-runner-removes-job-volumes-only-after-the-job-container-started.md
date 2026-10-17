---
id: lesson-522-act-runner-removes-job-volumes-only-after-the-job-container-started
type: lesson
status: active
created: "2026-10-04"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, act-runner, gitea, docker, volumes, disk]
---

# act_runner removes a job's volumes only if the job container started, so a cancel during the image pull leaks both

**Context**: the Beelink's root filesystem filled twice (#1657, OPS-024). Both times the
most visible residue was the job volumes that act_runner leaves behind, named
`GITEA-ACTIONS-TASK-<n>_...` plus a matching `-env` volume. It looked like they were
what filled the disk. The node runs act_runner 0.2.13, which is built on gitea/act
v0.261.7.

**Problem**: neither the cause nor the size was what it looked like.

- **Cause.** In act's `pkg/runner/job_executor.go`, the cleanup that removes the container
  and both volumes is a `Finally` chained after `startContainer()` inside one
  `NewPipelineExecutor`. If `startContainer()` errors, or the context is cancelled
  while it is still pulling the image, the pipeline returns before the `Finally` is
  attached. The volumes already exist by then, so they stay.
  - The runner's `AutoRemove: true` (`--rm`) does not help. Docker's `--rm` removes
    anonymous volumes only, never named ones.
  - Measured in Gitea's `action_task` table: all nine leaked cancelled tasks were cancelled
    1 to 5 seconds after they started, during the forced `docker pull`. The one leaked
    failed task had a log that stopped 12 minutes before Gitea marked it failed, which
    looks like the node going down mid-job.
  - No setting in 0.2.13 changes this. gitea/runner v3.5.0 added an idle sweep
    (`RemoveOrphanJobVolumes`), but it only sees volumes that carry the runner's UUID
    label, and 0.2.13 never sets that label. Even v4.1.0 still returns early when the
    container start fails.
- **Size.** The leaked volumes were almost all 0 B. The disk was filled by other things:
  - the build cache: 31.5 GB, every entry 5 days old or younger;
  - exited `docker run` containers left by workflows without `--rm`: 5.2 GB;
  - images: 18.9 GB;
  - one buildx builder: 3.7 GB, running for 698 h.

  All of these grow in a day of busy CI. A weekly prune fell behind them.

**Solution**: #1657's PR does three things.

1. It bounds the residue, because no configuration change eliminates it. On the CI node
   (`maintenance_docker_reclaim`), the `node_maintenance` timer now runs the same module
   as `make node-reclaim`. That module removes a volume only if all of these hold:
   - it is a job volume, a builder state volume, or labelled anonymous;
   - no container holds it;
   - it is older than 24 h;
   - it is not named anywhere in `common.yaml`'s `backup` block. The node receives that
     list as JSON, derived when the role is provisioned, and an empty list is refused.
2. It moves the CI node's timer from weekly to daily, because a weekly cadence is
   outrun by the build cache.
3. It makes the run exit non-zero, which fires `OnFailure=kubelab-notify@`, when the
   reclaim fails or `/` stays at or above the live test's 80% after cleanup.

Evidence:
- `tests/test_node_maintenance_docker_reclaim.py` turned red under eight mutations,
  covering the invocation, the pattern, the protection, `exit 1` and the role switch.
- The first daily run removed the two leaked anonymous volumes, kept all four declared
  volumes, and took `/` from 75% to 32%.
- The second provision ran with `changed=0`.

**Rule**: before you blame the most visible residue for a full disk, measure its size;
the list of leaked objects is not the list of large ones. And when a cleanup lives in a
`Finally`, find where in the pipeline it is attached: a cleanup chained after the step
that fails never runs for that failure. Check every early return, cancellation
included, before you trust it.

**Tags**: `#act-runner` `#volumes` `#disk` `#node-maintenance` `#issue-1657`
