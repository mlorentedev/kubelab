---
id: lesson-661-a-dry-run-reads-the-file-the-previous-run-rendered
type: lesson
status: active
created: "2026-10-29"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, ansible, check-mode, docker]
---

# A dry run reads the file the previous run rendered, not the one this run would write

**Context**: Sizing the Beelink's stack pull behind the lab edge (#2742). The estimate needs the list of images the pull fetches.

**Problem**: `docker compose config --images` on the node's `compose.yml` looked like the single source: the same file the pull reads, so the two could not drift. But a `template` task in check mode reports the change and writes nothing. A dry run would then read the file the previous run wrote and size the old stack: an image bumped or added in the change being rehearsed is counted at its old size, or not at all. A node's first provision has no file to read.

**Solution**: Each call of the include passes its images from the variables the template renders (`gitea_image`, `runner_image`, and `act_runner_image` under the same condition as its service). `tests/test_image_pull_budget.py` parses each template a call pulls from and fails on a service image the call does not list.

**Rule**: In check mode, a task that reads a file an earlier task renders gets the previous run's file. Read the inputs the template renders instead, and hold the two together with a test.

**Tags**: `#ansible` `#check-mode` `#pr-2806`
