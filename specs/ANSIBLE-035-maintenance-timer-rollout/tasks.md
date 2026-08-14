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

- [x] [AC1] Add `maintenance_run_cleanup: true` default to `roles/node_maintenance/defaults/main.yml`; flip `maintenance_install_timer` default to `true`.
- [x] [AC1] Gate every cleanup task in `roles/node_maintenance/tasks/main.yml` behind `when: maintenance_run_cleanup | bool` (APT/journal/rsyslog/snap/Docker/crictl/temp-file sections); leave the timer-install section's existing `maintenance_install_timer` gate untouched.
- [x] [AC3] Confirm `maintain.yml` is unaffected: it doesn't set `maintenance_run_cleanup`, so it inherits the new `true` default and keeps running full cleanup on manual invocation; diff its rendered task list before/after (`--list-tasks`) to prove no change.
- [x] [P] [AC2] Add `- role: ../roles/node_maintenance` with `maintenance_run_cleanup: false` to `provision-vps.yml`.
- [x] [P] [AC2] Same for `provision-aws1.yml`.
- [x] [P] [AC2] Same for `provision-bee.yml`.
- [x] [P] [AC2] Same for `provision-rpi3.yml`.
- [x] [P] [AC2] Same for `provision-rpi4.yml`.
- [x] [P] [AC2] Same for `provision-ace1.yml`.
- [x] [P] [AC2] Same for `provision-ace2.yml`.
- [x] `ansible-playbook --syntax-check` on all 7 touched playbooks; `make lint` / `make type` / `make test`.
- [x] [AC4] Enumerate live reachability for all 7 nodes before any real run — measured: vps/beelink/rpi3/rpi4/ace1/ace2 up, aws1 down (Tailscale "offline, last seen 3h ago" at the time, still down hours later — Spot interruption, not homelab on-demand hardware).
- [x] [AC4] Real (non-check) provisioning run per node; `systemctl list-timers | grep kubelab-maintenance` confirms active. Done for all 6 reachable nodes.
- [x] [AC4] Second real run per node converges `changed: 0` for all `node_maintenance` tasks (idempotence). Done for all 6 reachable nodes.
- [ ] [AC4] aws1 specifically: confirm the pre-existing timer converges (not a fresh install) — this is the ticket's actual motivating case. **Not done — aws1 offline the entire session.** Tracked as a follow-up in verification.md; the role invocation is committed and identical to the other 6, just unexercised against the live node.

## Implementation — Part 2: OnFailure notify wiring (AC6-AC8)

- [x] [AC6] Move `apps.services.automation.notify.webhook_secret`'s prod value from `prod.enc.yaml` into `common.enc.yaml` (same key path); remove the now-redundant prod override. **Superseded by a better design found mid-implementation**: reusing this key path collides with staging's own distinct value in the Ansible merge for 3 of 7 nodes (verified by simulation before shipping). Landed instead as a new dedicated `apps.services.automation.notify.fleet_webhook_secret` key, common.enc.yaml only, immune to any env override; `webhook_secret` itself was restored to its original per-env storage, untouched.
- [x] [AC6] `toolkit infra n8n import` / n8n's own Header Auth credential — no behavior change, since `webhook_secret` itself was left exactly as it was (see above); no re-import needed.
- [x] [AC8] Update `rotate_note` on both the existing `webhook_secret` SecretSpec (env-scoped, unchanged rotation) and the new `fleet_webhook_secret` SecretSpec (re-provisioning the fleet required).
- [x] [AC6] Write `roles/node_maintenance/templates/kubelab-maintenance-notify.sh.j2` — reads the fleet secret file, POSTs `{domain, severity: "log", title, body, source}` to `https://n8n.kubelab.live/webhook/notify` with the Bearer header; body includes the last 20 lines of `journalctl -u kubelab-maintenance.service`, JSON-encoded via `python3` to avoid shell-interpolation breakage.
- [x] [AC6] Write `roles/node_maintenance/templates/kubelab-maintenance-notify.service.j2` (oneshot, `ExecStart=` the script above).
- [x] [AC6] Add `OnFailure=kubelab-maintenance-notify.service` to `kubelab-maintenance.service.j2`.
- [x] [AC6] Ansible tasks: write the fleet secret to a 0600 file, template + install both new units, `daemon_reload` (reused the existing "Enable and start maintenance timer" task's `daemon_reload: true` rather than adding a second one). Gated the same way as the rest of the timer install (`maintenance_install_timer`), not `maintenance_run_cleanup`.
- [x] [AC7] Live proof (a): `systemctl start kubelab-maintenance-notify.service` on rpi3 AND beelink (staging-env, to specifically prove the dedicated-secret fix) — both `Result=success`.
- [x] [AC7] Live proof (b): temporary `ExecStart=/bin/false` drop-in on rpi3, real failure, journal shows `Triggering OnFailure= dependencies.` immediately followed by the notify unit firing and succeeding. Drop-in reverted, `reset-failed` run, timer confirmed still enabled after.
- [x] [AC7] Rolled the notify unit out to beelink, rpi4, ace1, ace2, vps (5 of the remaining 6) with idempotence re-checked on each; aws1 pending per AC4's note above.

## Implementation — Part 3: documentation (AC5)

- [x] [AC5] Write `docs/runbooks/maintenance-timer.md`: what the timer does, `systemctl status/list-timers` checks, log locations, how to temporarily disable it on a node, what an OnFailure notification means / how to respond to one, plus the check-mode-artifact note carried over from OPS-017.

## Closing

- [x] Every acceptance criterion from `proposal.md` is covered by the tasks above
- [x] `docs/runbooks/` maintenance-timer entry written (AC: runbook)
- [x] Type checks pass (`make type`)
- [x] Lint passes (`make lint`)
- [x] `make test` green (517 passed, 116 deselected)
- [x] No unrelated changes in the diff (no scope creep) — the untagged-pre_tasks fix on 4 playbooks is in-scope: it's the same class of bug this ticket's own new task surfaced, on the same files, in the same PR
- [x] `verification.md` filled in with live evidence per node (6/7 — aws1 pending)
- [ ] PR opened referencing this spec folder

## Machine-readable features

This spec emits a sibling `features.json` (alongside this file) following [[pattern-feature-list-as-primitive]]. The JSON is the harness-facing contract: each acceptance criterion maps to ≥1 feature with `id`, `behavior`, `verification` (executable command), `state` (lifecycle), and `evidence` (harness-captured output).

**Pass-state gating:** the agent CANNOT write `"state": "passing"` — only the harness, after running `verification` and capturing exit code 0, may set that terminal state. Reviewers must reject PRs where features.json contains `passing` entries with empty `evidence`.
