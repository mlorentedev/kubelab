---
id: lesson-637-a-dry-run-creates-no-directory-so-the-next-task-writing-into-it-fails-the-check
type: lesson
status: active
created: "2026-10-27"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, check-mode, gateway, rpi4]
---

# A dry run creates no directory, so the next task writing into it fails the check

**Context**: `make provision NODE=rpi4 ENV=prod BOOTSTRAP=1 CHECK=1` against the lab edge, which still held a hand-written netplan the `gateway` role backs up before it replaces it (#2696).

**Problem**: The run failed at `Back up hand-written netplan files` with `Destination directory /var/backups/kubelab-netplan does not exist`. The task before it, `Create the netplan backup directory`, reported `changed` under `--check`, which only says it would have created the directory. The `copy` then ran for real against a path that was never made. A live run passes. Only the dry run fails, and it fails on every edge that still holds a hand-written netplan, which is every edge the role has not converted yet.

**Solution**: Register the directory task, and skip the copy only when the dry run is the one that would have created the directory:

```yaml
  when: not (ansible_check_mode and gateway_netplan_backup_dir is changed)
```

On a re-run the directory exists, so the dry run still reports the backup it would take. `when: not ansible_check_mode` would hide that on every dry run. `ignore_errors` would put an `ignored=1` in every recap, and a reader learns to treat that column as noise. `check_mode: false` on the directory makes the dry run write to the host. `tests/test_gateway_role_tasks.py` evaluates the real `when` for each pair of check mode and directory state.

**Rule**: Under `--check`, `changed` on a task that creates something means the thing does not exist. A later task that needs it must ask whether its producer `is changed` in check mode, not skip every dry run.

**Tags**: `#check-mode` `#gateway` `#pr-2696`
