---
id: maintenance-timer
type: runbook
status: active
created: "2026-08-14"
---

# Fleet maintenance timer — operational runbook

> `kubelab-maintenance.timer` runs weekly disk hygiene (APT cache, journal
> vacuum, rotated-log retention, snap/Docker/crictl pruning, temp files) on
> every Ubuntu/Debian node in the fleet. Property of provisioning since
> ANSIBLE-035 — a freshly provisioned or freshly replaced node comes up with
> it already scheduled, rather than needing a manual follow-up step.

## Scope

- **Covered**: vps, aws1, beelink, rpi3, rpi4, ace1, ace2 — every node
  `provision-<node>.yml` includes `roles/node_maintenance` for.
- **Not covered**: Jetson (Ubuntu 18.04, `legacy_python`, raw-module-only
  provisioning — the role's Ansible-module tasks aren't reachable there).

## Checking status

```bash
# Is the timer active and scheduled?
ansible <node> -i infra/ansible/generated/<env>/hosts.yml -b -m command \
  -a "systemctl list-timers kubelab-maintenance.timer"

# Did the last run succeed?
ansible <node> -i infra/ansible/generated/<env>/hosts.yml -b -m command \
  -a "systemctl show kubelab-maintenance.service -p Result -p ExecMainStatus"

# What did it actually do?
ansible <node> -i infra/ansible/generated/<env>/hosts.yml -b -m command \
  -a "journalctl -u kubelab-maintenance.service -n 50 --no-pager"
```

`<env>` is that node's own `deploy_env` in its provisioning playbook (prod
for vps/rpi3/rpi4, staging for beelink/ace1/ace2, hub for aws1) — the
inventory only exists per-env, not per-node.

## Running it manually

`make maintain NODE=<node> [ENV=staging|prod] [TIMER=1]` — see
`infra/ansible/playbooks/maintain.yml`. Without `TIMER=1` this runs cleanup
once, immediately, without touching the timer. This is the only path that
runs cleanup synchronously — `make provision` never does (see "Why
provisioning doesn't run cleanup" below).

## Temporarily disabling the timer on a node

```bash
ansible <node> -i infra/ansible/generated/<env>/hosts.yml -b -m command \
  -a "systemctl disable --now kubelab-maintenance.timer"
```

The next `make provision NODE=<node> ...` re-enables it (`maintenance_install_timer`
defaults `true`) — this is a temporary pause, not a permanent opt-out. For a
permanent exclusion, add `maintenance_install_timer: false` to that node's
role invocation in its `provision-<node>.yml`, with a comment explaining why.

## Why provisioning doesn't run cleanup

`node_maintenance`'s cleanup tasks (APT lists wipe, `docker image/builder
prune -af`, `crictl rmi --prune`, …) are gated behind `maintenance_run_cleanup`
(default `true`), which every `provision-<node>.yml` sets `false` when
including the role. Including the role unconditionally would run the full
cleanup pass on every single `make provision`, not just install the timer —
wiping `/var/lib/apt/lists` right after `base_system` populates it (a
`--check` dry-run in that window fails on a completely standard package,
even though a real run succeeds — see the "check-mode apt cache" note
below), and evicting build/image caches on every re-provision. Cleanup only
ever runs on the timer's own weekly schedule, or via `make maintain
TIMER=1`'s explicit manual invocation.

## What an OnFailure notification means

A failed `kubelab-maintenance.service` run (a hard script abort — most
individual sub-tasks tolerate failure deliberately via `ignore_errors`, so
this means something like `apt-get clean` or `journalctl --vacuum-size`
failing outright, not a single skipped prune) triggers
`kubelab-notify@kubelab-maintenance.service.service`, which POSTs a
`log`-severity envelope to n8n's public `/webhook/notify` ingress
(NOTIFY-001). That name is not a typo: `kubelab-notify@.service` is one
template serving every unit in the fleet, and the instance is the full name
of the unit that failed — which is how the notifier knows whose journal to
read. Any unit gains this with one line, `OnFailure=kubelab-notify@%n.service`.
The envelope lands wherever `log`-tier fleet alerts land (Apprise → Telegram
at the time of writing).

**Always prod n8n** (`n8n.kubelab.live`), regardless of the node's own
`deploy_env` — this is deliberate: three of the seven nodes provision under
`deploy_env: staging`, and routing their alerts through staging n8n would
make the alert path depend on ace1 (staging n8n's host) being powered on.

**Responding to one**: check the linked node's `kubelab-maintenance.service`
journal (see "Checking status" above) for the actual failure. A delivery
failure of the notification itself (wrong token, n8n unreachable) shows up
as `kubelab-notify@kubelab-maintenance.service.service` itself failing —
check that unit's own journal separately if the alert never arrived but you
suspect a run failed.

**A failed delivery has already been retried** (ANSIBLE-038). `curl` retries
transient failures — connection refused, timeouts, and 5xx — up to 3 times
with a 5s delay, so the unit failing means roughly 4 attempts over ~30s all
failed, not one unlucky packet. Two consequences when reading its journal:

- The unit legitimately takes tens of seconds against an unreachable n8n. It
  is not hung; `TimeoutStartSec=45` is the real ceiling.
- The retry lives in `curl`, **not** as `Restart=` on the unit. If you add
  `Restart=` you get both, and systemd will re-run the whole script — journal
  read and payload encode included — to retry one HTTP request. The rationale
  is in the unit template, and `tests/test_node_notify_role.py` fails if the
  two ever drift apart or the retry budget outgrows the timeout.

**Testing the path without waiting for a failure**:

```bash
make maintain-notify-test NODE=rpi3        # one node
make maintain-notify-test NODE=all         # the whole fleet
```

This starts the notify unit directly and asserts `Result=success` and
`ExecMainStatus=0`. Because the unit's `curl` uses `-f`, exit 0 means n8n
really answered 2xx — it is an end-to-end delivery check, not a "the file is
installed" check. **It really notifies**: expect the message to arrive, and
ignore it. A delivery test that suppressed delivery would prove nothing.

Run it after any change to the notify script or its unit — ANSIBLE-038's
fixes require it. Node ENVs are the same as `make provision`: `vps` is
`ENV=prod`, `aws1` is `ENV=hub`, the homelab nodes default to staging.

## Known artifact: `--check` dry-runs after a cache-wiping event

Both `kubelab-maintenance.sh.j2` (the timer's actual weekly payload) and the
`maintenance_run_cleanup` path wipe `/var/lib/apt/lists`. Ansible's `apt`
module skips the real `apt-get update` under `--check` (it only predicts the
change) but still reports the cache-update task as `changed` — so a
`--check` dry-run run in the window between a cache wipe and the next real
`apt-get update` can fail on a completely standard package (observed with
`vim` on rpi3 during ANSIBLE-035's own rollout, before `base_system` had
ever populated its cache). This is a known, understood check-mode artifact,
not a functional bug: a real (non-`--check`) run genuinely refreshes the
cache first and succeeds. If a `--check` run fails this way, re-run without
`--check` — it will resolve on the first real run afterward.

## References

- Roles: `infra/ansible/roles/node_maintenance/` (the timer) and
  `infra/ansible/roles/node_notify/` (the notifier every unit shares)
- Spec: `specs/ANSIBLE-035-maintenance-timer-rollout/` (or
  `specs/archive/ANSIBLE-035-maintenance-timer-rollout/` once archived)
- NOTIFY-001 webhook contract: `infra/n8n/workflows/README.md`
