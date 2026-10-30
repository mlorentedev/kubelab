---
id: lesson-664-a-budget-that-fails-mid-role-drops-the-handlers-before-it
type: lesson
status: active
created: "2026-10-29"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, apt, handlers, lab-edge]
---

# A budget that fails the play mid-role drops the handlers notified before it; skip the step when nothing after it needs it

**Context**: Sizing `base_system`'s `apt upgrade: dist` against the lab edge's shaped downlink (#2809), the way `_includes/image-pull.yml` sizes image pulls (#2742). On 2026-10-29 ace1's upgrade of 27 packages spent about 29 minutes downloading them and 48 seconds installing them, with no output until it finished.

**Problem**: The image-pull include refuses an over-budget pull with an `assert`, which fails the play. In `base_system` two tasks before the upgrade notify handlers (`apply netplan`, `restart tailscaled`), and no play sets `force_handlers`. An `assert` there would stop the play with those handlers pending, and the rerun, seeing no change, would never fire them. That is the defect #2812 tracks for pulls placed after a gated template, here in a fifth role.

**Solution**: `_includes/apt-upgrade.yml` skips the upgrade over budget and prints a SKIPPED/WHY/FIX message instead of failing. The play continues and the handlers run. A refused pull fails because the stack after it needs the image. Nothing after the upgrade needs the new versions, so a skip loses nothing the run depends on. Within budget, the include fetches with `apt-get --download-only dist-upgrade` in a bounded, retried async task, then lets `apt` install from the cache with no bound on dpkg. The estimate is `apt-get -qq --print-uris dist-upgrade` summed on its third field. Measured on 2026-10-29 with `-o Dir::Cache::archives`, `--print-uris` leaves out a `.deb` already in the archives directory, so a rerun or a retry after a broken download counts only what is still missing.

**Rule**: Before a guard fails a play, check what the role notified ahead of it. If the guarded step is not a prerequisite of anything after it, refuse the step, not the play, and say so loudly. Fail the play only when the rest of the run cannot work without the step.

**Tags**: `#ansible` `#handlers` `#apt` `#adr-075` `#issue-2809`
