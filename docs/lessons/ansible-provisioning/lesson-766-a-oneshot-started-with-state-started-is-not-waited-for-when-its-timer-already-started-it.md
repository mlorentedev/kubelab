---
id: lesson-766-a-oneshot-started-with-state-started-is-not-waited-for-when-its-timer-already-started-it
type: lesson
status: active
created: "2026-11-17"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, systemd, oneshot, timer, race, agent-stack, curator]
---

# A oneshot started with `state: started` is not waited for when its timer already started it

**Context**: `make provision NODE=ace2 ENV=staging` failed at `Verify this run wrote the candidates` (#3575). The curator's analyzer was not broken: `systemctl show` right afterwards said `ActiveState=activating`, and its journal showed a run that began seconds before the play's `stat` and takes about 64 s. The task before the check was `ansible.builtin.systemd: state: started`.

**Problem**: For a `Type=oneshot` unit, `systemctl start` blocks until the run ends, so `state: started` looks like "run it and wait". It only does when the module issues the start. The module counts `activating` as running and issues nothing, and `systemctl start --wait` has the same hole: it waits for the job it queued, and a unit its timer already started has none for it. On a node whose timer is already enabled the play fails only when a firing falls inside the window, so it passes on most passes and the race stays invisible until one does not. Other plays in the repo carry a comment saying `started` blocks; it holds there only because they `state: stopped` the unit first.

**Solution**: Run the unit with `systemctl start --wait`, poll `ActiveState` until it is no longer `activating`, `active`, `deactivating` or `reloading`, read `Result` from systemd and assert `success`, and only then look at what the run wrote. The poll is sized in the role's defaults to outlast the run twice over and stay under the unit's `TimeoutStartSec`. The run stays `changed_when: false`: it is the measurement, the units are the change, so a second provision is still `changed=0`. `tests/test_agent_stack_oneshot_waits.py` runs the real tasks against a stand-in `systemctl` that returns at once from `start --wait`, as a unit already activating does.

**Rule**: A task that starts a oneshot and then reads its effect must wait on the unit's state, not on the start's return, unless it first stops the unit. A guard derives which units are oneshots from the role's own templates (`Type=oneshot` without `RemainAfterExit=yes`) and fails for any it starts with `state: started` and never polls; the exemptions are a named set (#3630) that a test fails to keep once its task is fixed.

**Tags**: `#ansible` `#systemd` `#oneshot` `#race` `#issue-3575`
