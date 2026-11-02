---
id: lesson-653-a-oneshot-that-waits-holds-a-job-and-the-boot-is-finished-only-once-no-job-is-left
type: lesson
status: active
created: "2026-10-29"
owner: manu
category: containers-docker
tags: [kubelab, containers-docker, systemd, boot-race, tailscale]
---

# A oneshot that waits holds a job, and the boot is finished only once no job is left

**Context**: NET-005's hard-reset test (B14, #2661) booted the lab with its uplink missing. `multi-user.target` was reached, but `systemctl is-system-running` stayed `starting` (#2776). The stack units that publish on the Tailscale address were oneshots that waited about two minutes for the address in `ExecStartPre`, retried with `Restart=on-failure` (lesson-624).

**Problem**: systemd records the boot as finished only when its job table is empty (`manager_check_finished` in `src/core/manager.c`), so reaching a target is not enough. A oneshot is in its start job until its last command has exited, so each attempt of a unit that waits for the network holds a job for the whole wait: 120 s of every 150 s cycle while the tailnet is unreachable. Measured on systemd 259: a restarting oneshot has no job during `RestartSec`, so these units only made the moment the boot finished a matter of chance. The hand-made `tailscale-watchdog` on the edge held the table forever: a oneshot with no `TimeoutStartSec`, which is unbounded for a oneshot, running a `tailscale up` that blocks while the control server is unreachable (#2675).

**Solution**: The four stack units became `Type=exec`, whose start job ends when the command is executed. The wait moved into `ExecStart` (`sh -c '<wait> || exit 75; exec docker compose ...'`), so it still retries while `RestartPreventExitStatus=1` still stops on compose's own error. `RuntimeMaxSec=180` replaces `TimeoutStartSec` as the bound on the wait and compose together. Since `systemctl start` now returns at exec, the provision waits for the unit to leave `running` and asserts `exited` (`playbooks/_includes/stack-unit-settled.yml`). Otherwise the role's own `docker compose up -d` would race the unit's recreate. `tests/test_tailscale_bound_boot_units.py` holds the unit type, where the wait runs, the exit code, and that no shipped oneshot restarts.

**Rule**: A unit that waits for something outside the node does not wait inside its start job. Either it starts and then waits (`Type=exec`), with whoever needs the result reading the unit's state, or its start is bounded. Ordering it after the target does not help: boot ends when every job ends, not when a target is reached.

**Tags**: `#systemd` `#boot-race` `#issue-2776` `#issue-2675`
