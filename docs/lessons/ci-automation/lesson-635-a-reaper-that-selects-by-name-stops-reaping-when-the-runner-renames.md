---
id: lesson-635-a-reaper-that-selects-by-name-stops-reaping-when-the-runner-renames
type: lesson
status: active
created: "2026-10-27"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, gitea, docker, maintenance]
---

# A reaper that selects by name stops reaping when the runner renames what it creates

**Context**: the Beelink's daily maintenance removes CI residue with
`toolkit/features/docker_reclaim.py` (#1657, lesson-522). It takes only volumes
whose name says a runner made them for one job. The pattern was
`GITEA-ACTIONS-TASK-<n>_...`, measured against act_runner 0.2.13.

**Problem**: #2425 moved the forge to gitea/runner 4.1.0, which names a job's
volumes `GITEA-ACTIONS-TASK-6071-WORKFLOW-CI-JOB-build-pdf-build-pdf-<hash>`,
plus `-env`. The separator after the task number is `-` where it was `_`. From
then on, no job volume matched. The reaper removed nothing, and it reported
success, since an empty plan is a valid outcome. The unit tests kept passing,
because their fixtures were the old names captured on 2026-09-05. What saw it
was `tests/infra/test_backup_coverage.py`, which asks the live node for every
volume and refuses one that is neither declared nor bounded: the running job's
two volumes came back undeclared.

**Solution**: the pattern accepts both separators,
`GITEA-ACTIONS-TASK-\d+[_-].*`. `tests/test_docker_reclaim.py` holds a
parametrised case for each runner's names, taken from the node. Narrowing the
class back to `_` turns the 4.1.0 cases red.

**Rule**: a selector written against the names a third-party tool generates
belongs to that tool's version. When the tool is upgraded, read the names it
creates on the node before trusting the selector. Keep at least one check that
reads the live node and fails on what it cannot classify: a fixture records
the names from the day it was captured, and an empty plan does not look broken.

**Tags**: `#docker-reclaim` `#gitea-runner` `#ops-024` `#issue-2425`
