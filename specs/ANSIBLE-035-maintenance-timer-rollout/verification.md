---
tags: [spec, verification, templates]
created: "2026-08-14"
---

# Verification - ANSIBLE-035-maintenance-timer-rollout

## Evidence

- [x] AC1 (gate vars: `maintenance_install_timer` defaults true, new `maintenance_run_cleanup` gates cleanup) -> `25b4e67`
- [x] AC2 (7 playbooks include the role, `maintenance_run_cleanup: false`) -> `25b4e67`
- [x] AC3 (`maintain.yml` unaffected) -> verified via `--list-tasks` (task set unchanged) + by inspection: `maintain.yml` doesn't set `maintenance_run_cleanup`, inherits the `true` default unaffected by this change; `maintenance_install_timer` is set explicitly regardless of the role default, both before and after
- [x] AC4 (live per-node rollout + idempotence) -> real `make provision NODE=<x> TAGS=maintenance` run + second real run per node, both confirmed `changed: 0` on the second pass, `systemctl is-enabled kubelab-maintenance.timer` = `enabled` on all 6 reachable nodes:
  - rpi3: first run `changed=4`, second `changed=0`, timer enabled, `Set hostname`/ufw work from OPS-017 unaffected
  - beelink: first run `changed=4`, second `changed=0`, timer enabled
  - rpi4: first run `changed=4`, second `changed=0`, timer enabled
  - ace1: first run `changed=4`, second `changed=0`, timer enabled
  - ace2: first run `changed=4`, second `changed=0`, timer enabled
  - vps: first run `changed=4`, second `changed=0`, timer enabled; K3s health re-verified after (`kubectl get nodes` -> Ready, `kubelab.live` -> HTTP 301) since this is the prod ingress node
  - **aws1: verified 2026-08-14, follow-up session.** The Spot instance recovered (`i-0be7ecf199975bf1a`'s replacement request cleared `capacity-not-available`, confirmed reachable via `tailscale ping`). Baseline checked first: the pre-existing hand-installed timer was already `enabled`/`active` (this is the ticket's original premise -- the fleet's only timer, installed by hand, on cattle), but none of this PR's additions existed yet (`/opt/kubelab-maintenance-notify.sh` missing, no `OnFailure=` on the unit, no secret file). `make provision NODE=aws1 ENV=hub TAGS=maintenance` run twice: first `changed=4` (matches all 6 other nodes exactly), second `changed=0`. Post-run: `systemctl is-enabled/is-active` both confirm, `OnFailure=kubelab-maintenance-notify.service` present, notify script + secret file present. Standalone delivery test (`systemctl start kubelab-maintenance-notify.service`) -> `Result=success, ExecMainStatus=0`, proving the fleet-wide secret resolves correctly from aws1's own `hub` env context, not just staging/prod. This closes the ticket's actual motivating case: a future Spot replacement now reinstalls the timer (with notify wiring) automatically via provisioning, not by hand.
- [x] AC5 (runbook) -> `docs/runbooks/maintenance-timer.md`
- [x] AC6 (OnFailure wiring: `OnFailure=kubelab-maintenance-notify.service` on the main unit, posts to prod n8n via a dedicated `fleet_webhook_secret`) -> `b46919b`
- [x] AC7 (notify path proven live, twice, per node where run) ->
  - Standalone delivery: `systemctl start kubelab-maintenance-notify.service` on rpi3 AND beelink (a staging-env node, to specifically prove the dedicated-secret fix works from a node whose own `deploy_env` isn't prod) -> both `Result=success, ExecMainStatus=0` (curl `-f`, so this means n8n returned 2xx)
  - `OnFailure=` linkage itself: on rpi3, installed a temporary `ExecStart=/bin/false` drop-in, ran `systemctl start kubelab-maintenance.service` -> failed as expected (`Result=exit-code`), journal shows `kubelab-maintenance.service: Triggering OnFailure= dependencies.` immediately followed by the notify unit starting and completing successfully. Drop-in removed, `systemctl reset-failed` run, timer confirmed still `enabled` afterward. Not repeated on every node -- one thorough proof of the linkage mechanism, per tasks.md's own design, then rolled out.
- [x] AC8 (rotate_note updated on both the existing `webhook_secret` SecretSpec and the new `fleet_webhook_secret` SecretSpec) -> `b46919b`

## Test status

- `make lint` / `make type` / `make test` (517 passed, 116 deselected): green after every commit in this branch.
- Manual smoke test: see AC4/AC7 above -- every node re-provisioned twice (idempotence), notify path exercised end-to-end on 2 of 7 nodes, `OnFailure=` linkage exercised via real failure injection on 1 node.
- No regressions: `secrets audit --env prod` (44/44) and `--env staging` (39/39) both 100% after the secret-catalog change.

## Decisions made during implementation

- Notify design initially assumed a direct Apprise integration; corrected after finding `apprise.yaml` is cluster-internal-only (`Cluster-internal only: no IngressRoute`). Real integration point is n8n's public `/webhook/notify` ingress.
- All 7 nodes notify to prod n8n regardless of their own `deploy_env`, to avoid the alert path depending on ace1 (staging n8n's host) being powered on -- user-confirmed design choice, measured live (prod n8n publicly reachable, real cert, 403-gated; staging needs VPN + self-signed cert).
- **Secret collision caught before shipping**: reusing the existing `apps.services.automation.notify.webhook_secret` key path for the fleet-wide notify secret would have collided with staging's own distinct value in the Ansible `combine()` merge for the 3 staging-env nodes (env override wins) -- verified by simulating the exact merge for all three node contexts (common-only, common+staging, common+prod) before writing any Ansible task. Fixed with a dedicated `fleet_webhook_secret` key, common.enc.yaml only, immune to any env override. Confirmed functionally correct afterward by running the standalone delivery test specifically from beelink (a staging-env node).
- **Second bug caught live**: 4 of the 7 playbooks (vps, aws1, rpi3, rpi4) didn't tag their config/secrets pre_tasks as `always`, so `--tags maintenance` silently skipped secret loading -- surfaced as `'secrets' is undefined` on the first attempt to deploy the notify unit. beelink/ace1/ace2 already had this tagged correctly, each with a comment naming this exact failure mode; brought the other 4 in line with that existing pattern rather than inventing a new one.
- aws1 down for the entire original session (Spot interruption); rollout there deferred, tracked as a follow-up above rather than silently claimed as done, then completed once the node recovered (see AC4/AC7 above).

## Promotion candidates

- [x] Lesson for the repo's `docs/lessons.md`? **Yes, written** -- two entries: the apt check-mode/virtual-package gotchas (OPS-017) and the untagged-pre_tasks + secret-key-collision gotchas (this ticket). Commit `0439a18`.
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? No -- these are role/playbook-level design choices (gate variables, secret key naming), not architecture-level.
- [ ] New pattern candidate for `00_meta/patterns/`? No -- single-project evidence so far (matches the same "single-project, flag for next /crystallize" disposition this lane used on the equivalent OPS-022 question).

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/ANSIBLE-035-maintenance-timer-rollout/` -> `specs/archive/ANSIBLE-035-maintenance-timer-rollout/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
- [ ] **aws1 rollout follow-up (see AC4) resolved** -- not a blocker for merging this PR, but should not be forgotten; either close it out before archiving this spec or open a small follow-up issue at archive time.
