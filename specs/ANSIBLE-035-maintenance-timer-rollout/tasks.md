---
tags: [spec, tasks, templates]
created: "2026-08-14"
---

# Tasks - ANSIBLE-035-maintenance-timer-rollout

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> Sequenced so the fleet rollout (the ticket's actual ask) is shippable standalone if the notify piece hits an unexpected wall — the timer rollout does not depend on the notify unit existing.

## Setup

- [x] Branch created from master: `feat/ANSIBLE-035-maintenance-timer-rollout`
- [x] `proposal.md` complete; acceptance criteria testable
- [x] No open questions left in "Risks / open questions" (gate-var design and notify-target design both resolved and user-confirmed)

## Implementation — Part 1: gate-var + fleet rollout (AC1-AC4)

- [ ] [AC1] Add `maintenance_run_cleanup: true` default to `roles/node_maintenance/defaults/main.yml`; flip `maintenance_install_timer` default to `true`.
- [ ] [AC1] Gate every cleanup task in `roles/node_maintenance/tasks/main.yml` behind `when: maintenance_run_cleanup | bool` (APT/journal/rsyslog/snap/Docker/crictl/temp-file sections); leave the timer-install section's existing `maintenance_install_timer` gate untouched.
- [ ] [AC3] Confirm `maintain.yml` is unaffected: it doesn't set `maintenance_run_cleanup`, so it inherits the new `true` default and keeps running full cleanup on manual invocation; diff its rendered task list before/after (`--list-tasks`) to prove no change.
- [ ] [P] [AC2] Add `- role: ../roles/node_maintenance` with `maintenance_run_cleanup: false` to `provision-vps.yml`.
- [ ] [P] [AC2] Same for `provision-aws1.yml`.
- [ ] [P] [AC2] Same for `provision-bee.yml`.
- [ ] [P] [AC2] Same for `provision-rpi3.yml`.
- [ ] [P] [AC2] Same for `provision-rpi4.yml`.
- [ ] [P] [AC2] Same for `provision-ace1.yml`.
- [ ] [P] [AC2] Same for `provision-ace2.yml`.
- [ ] `ansible-playbook --syntax-check` on all 7 touched playbooks; `make lint` / `make type` / `make test`.
- [ ] [AC4] Enumerate live reachability for all 7 nodes before any real run (always-on: vps, aws1, rpi3 — expected up; on-demand: beelink, ace1, ace2, rpi4 — ask user to power on what's off, never assume).
- [ ] [AC4] Real (non-check) provisioning run per node; `systemctl list-timers | grep kubelab-maintenance` confirms active.
- [ ] [AC4] Second real run per node converges `changed: 0` for all `node_maintenance` tasks (idempotence).
- [ ] [AC4] aws1 specifically: confirm the pre-existing timer converges (not a fresh install) — this is the ticket's actual motivating case.

## Implementation — Part 2: OnFailure notify wiring (AC6-AC8)

- [ ] [AC6] Move `apps.services.automation.notify.webhook_secret`'s prod value from `prod.enc.yaml` into `common.enc.yaml` (same key path); remove the now-redundant prod override. Re-run `make secrets-audit` to confirm both envs still resolve correctly (staging keeps its own distinct value, prod now resolves via common).
- [ ] [AC6] `toolkit infra n8n import --env prod` (or equivalent) still upserts the same Header Auth credential value — confirm no behavior change on the n8n side.
- [ ] [AC8] Update `rotate_note` on that `SecretSpec` in `secrets_manager.py`: rotating the prod value now requires re-provisioning the fleet.
- [ ] [AC6] Write `roles/node_maintenance/templates/kubelab-maintenance-notify.sh.j2` — reads the fleet secret file, POSTs `{domain, severity: "log", title, body, source}` to `https://n8n.kubelab.live/webhook/notify` with the Bearer header; body includes the last N lines of `journalctl -u kubelab-maintenance.service`.
- [ ] [AC6] Write `roles/node_maintenance/templates/kubelab-maintenance-notify.service.j2` (oneshot, `ExecStart=` the script above).
- [ ] [AC6] Add `OnFailure=kubelab-maintenance-notify.service` to `kubelab-maintenance.service.j2`.
- [ ] [AC6] Ansible tasks: write the fleet secret to a 0600 file (from the now-common-resolvable secret), template + install both new units, `daemon_reload`. Gated the same way as the rest of the timer install (`maintenance_install_timer`), not `maintenance_run_cleanup`.
- [ ] [AC7] Live proof (a): `systemctl start kubelab-maintenance-notify.service` on one node, confirm delivery (n8n/Apprise log or Telegram read-back).
- [ ] [AC7] Live proof (b): temporary failure injection (drop-in override, reverted after) on the same node proves `OnFailure=` actually fires the notify unit — not just that the unit works standalone.
- [ ] [AC7] Roll the notify unit out to the remaining 6 nodes once the design is proven on one; re-run idempotence check per node.

## Implementation — Part 3: documentation (AC5)

- [ ] [AC5] Write `docs/runbooks/maintenance-timer.md`: what the timer does, `systemctl status/list-timers` checks, log locations, how to temporarily disable it on a node, and what an OnFailure notification means / how to respond to one.

## Closing

- [ ] Every acceptance criterion from `proposal.md` is covered by the tasks above
- [ ] `docs/runbooks/` maintenance-timer entry written (AC: runbook)
- [ ] Type checks pass (`make type`)
- [ ] Lint passes (`make lint`)
- [ ] `make test` green
- [ ] No unrelated changes in the diff (no scope creep)
- [ ] `verification.md` filled in with live evidence per node
- [ ] PR opened referencing this spec folder

## Machine-readable features

This spec emits a sibling `features.json` (alongside this file) following [[pattern-feature-list-as-primitive]]. The JSON is the harness-facing contract: each acceptance criterion maps to ≥1 feature with `id`, `behavior`, `verification` (executable command), `state` (lifecycle), and `evidence` (harness-captured output).

**Pass-state gating:** the agent CANNOT write `"state": "passing"` — only the harness, after running `verification` and capturing exit code 0, may set that terminal state. Reviewers must reject PRs where features.json contains `passing` entries with empty `evidence`.
