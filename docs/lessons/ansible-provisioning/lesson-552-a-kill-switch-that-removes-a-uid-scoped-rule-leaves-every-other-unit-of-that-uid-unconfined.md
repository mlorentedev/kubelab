---
id: lesson-552-a-kill-switch-that-removes-a-uid-scoped-rule-leaves-every-other-unit-of-that-uid-unconfined
type: lesson
status: active
created: "2026-10-10"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, systemd, nftables, hermes]
---

# A kill switch that removes a uid-scoped rule leaves every other unit of that uid unconfined

**Context**: hermes-kubelab's egress rule matches the agent's uid
(`meta skuid`, #2161). The kill switch is `systemctl stop
agent-stack-egress.service`. The agent's user manager `Requires=` that unit, so
the manager, the rootless daemon and every container stop with it. The
runbook said "it removes the agent and the rule that confines it together,
never one without the other."

**Problem**: The drill on 2026-10-10 proved the manager half. Nothing came
back: no process was left under the uid at 180 s, and lingering did not
restart the manager in ~15 min. But `hermes-kubelab-vault-sync.service` is a
**system** unit with `User=hermes-kubelab`, started by a timer, and it is not
under the user manager. At 12:41:58 it ran and succeeded with no
`agent_egress` table loaded: a process of the confined uid, holding the vault
token, with no confinement. The first fix, `Requisite=` on the service, made
the next start fail with result `dependency`. That failure still triggers
`OnFailure=` (measured: `kubelab-notify@…` ran), so every firing during a kill
would have paged.

**Solution**: The service gets `Requisite=agent-stack-egress.service` with a
matching `After=`. Requisite refuses the start while the rule is down, and
never pulls the rule up again. `Requires=` or `BindsTo=` would undo the kill.
The timer gets `PartOf=agent-stack-egress.service`, so stopping the rule stops
the timer, and no refused firing pages. Drill: kill, then the timer, the rule
and the manager are all `inactive` with no page. A provision brings all three
back (`changed=3`), and the next run reports `changed=0`. Mutants that swap
`Requisite` for `Requires`, or drop `PartOf`, go RED in
`tests/test_hermes_vault_sync.py`.

**Rule**: A rule scoped to a uid confines a uid, not a unit tree. Before
calling a stop a kill switch, list every unit that runs as that uid: user
units, system units with `User=`, timers, and paths. Bind each one to the rule
with `Requisite=`, which refuses, and never with `Requires=`, which restarts.
A refused start is still a failure to `OnFailure=`, so whatever starts that
unit (a timer or a path) needs `PartOf=` the rule too.

**Tags**: `#systemd` `#kill-switch` `#ai-009` `#pr-NNNN`
