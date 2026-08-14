---
id: "ANSIBLE-035-maintenance-timer-rollout"
type: spec
status: verifying # draft | implementing | verifying | archived
created: "2026-08-14"
issue: "kubelab#928"
tags: [spec, proposal]
template_version: "1.0"
---

# ANSIBLE-035: Maintenance timer rollout

> **Naming**: file lives at `<repo>/specs/<feature-id>/proposal.md`. `<feature-id>` is `AREA-NNN-slug` (e.g. `TOOL-001-secret-drift`).

## Why

<!-- from issue #928: ANSIBLE-035: the maintenance timer is installed on exactly one node, and that node is cattle -->

The `node_maintenance` role (APT cache cleanup, journal vacuum, rotated-log
retention, snap/Docker/crictl pruning, temp-file cleanup, plus an optional
systemd timer) is reachable from exactly one playbook (`maintain.yml`), which
is only ever run by hand via `make maintain NODE=x TIMER=1`. Today the timer
is installed on exactly one node fleet-wide: `aws1`. That node is a Spot
instance that has already been replaced once (2026-05-06). Its next
replacement silently deletes the only maintenance timer in the fleet, and
nothing anywhere reports the loss. A state that exists because a command was
run once does not survive the infrastructure it runs on.

## What

The maintenance timer becomes a property of provisioning, not a manual
follow-up step. `maintenance_install_timer` defaults to `true` in the role
and `node_maintenance` is included in the seven Ubuntu/Debian provisioning
playbooks (vps, aws1, beelink, rpi3, rpi4, ace1, ace2), so a freshly
provisioned — or freshly replaced — node comes up with `kubelab-maintenance.timer`
already enabled and scheduled. Provisioning does **not** also trigger an
immediate destructive cleanup pass (see Risks: this is a new gate variable,
`maintenance_run_cleanup`, defaulting `true` for `maintain.yml`'s explicit
manual invocation and `false` when the role is included from a provision
playbook) — the timer's job is to run cleanup on its own schedule, not
synchronously inside every `make provision`.

Jetson stays out of scope: Ubuntu 18.04, `raw`-module-only provisioning
(`legacy_python`), already absent from `make maintain`'s node list, and the
role's Ansible-module tasks (`apt`, `find`, `systemd`, …) aren't reachable
there the way they are on the other six.

## Out of scope

- Jetson (`legacy_python`, raw-only provisioning — the role's tasks aren't
  reachable there; no attempt made to port the timer).
- `OnFailure=` wiring into the NOTIFY-001 notify fabric for a failed
  maintenance run — the issue names this an explicit, undecided follow-up
  ("Not built here without a decision"), not a silent inclusion.
- Reworking `kubelab-maintenance.sh.j2` itself (the parallel shell
  implementation the timer actually runs) beyond what's needed to make the
  rollout safe — see Risks for the one behavior documented as an accepted
  consequence rather than fixed.
- ANSIBLE-030 (#858) — `dev_node`'s own housekeeping timers (git gc, language
  caches, agent workspace resets) are dev-workload hygiene on ace2 alone,
  adjacent but not overlapping with this fleet-generic disk hygiene.

## Risks / open questions

- **[RESOLVED, gate-var design]** Including `node_maintenance` in a provision
  playbook with its existing `tasks/main.yml` as-is would run the FULL
  cleanup pass (`apt-get clean`, `rm -rf /var/lib/apt/lists/*`, `docker image
  prune -af`, `docker builder prune -af`, `crictl rmi --prune`, rotated-log
  deletion, oversize-syslog truncation) synchronously on every single
  `make provision`, not just install the timer. Two concrete costs measured
  this session: (1) wiping `/var/lib/apt/lists` right after `base_system`'s
  "Update apt cache" task populates it would put every freshly provisioned
  node back into the exact empty-cache state that made rpi3's `CHECK=1`
  dry-run fail on a completely standard package (root-caused in this same
  session — see `docs/lessons.md` if already promoted, or PR #1059's
  evidence). (2) `docker image/builder prune -af` mid-provision would evict
  ace1's staging K3s image cache and beelink's CI build cache on every
  re-provision, not just weekly. Resolution: a new `maintenance_run_cleanup`
  boolean gates the cleanup tasks (default `true`); provision playbooks pass
  `false` so they only install-and-enable the timer. `maintain.yml` is
  unaffected — it already sets `maintenance_install_timer` explicitly via
  `install_timer | default(false)`, so its manual `TIMER=1` semantics don't
  change either way.
- **Accepted consequence, not fixed here**: `kubelab-maintenance.sh.j2` (the
  actual weekly payload, a second implementation independent of the Ansible
  tasks) also does `rm -rf /var/lib/apt/lists/*`. Once the timer is live
  fleet-wide, a `--check` dry-run run in the window between a timer firing
  and the next real `make provision`/`apt-get update` will hit the same
  vim-style false failure on ANY node, not just rpi3 — a known, understood
  check-mode artifact (root-caused this session), not a functional bug: a
  real run re-populates the cache and succeeds. Documented here rather than
  silently redesigning the script to auto-refresh the cache after wiping it.
- **[RESOLVED]** `OnFailure=` notify wiring: built in this pass, not
  deferred. First draft of this section wrongly assumed the target was
  Apprise directly — measured and corrected: `apprise.yaml` is explicit
  (`Cluster-internal only: no IngressRoute`), so nothing outside the K3s pod
  network can reach it. The real, documented NOTIFY-001 entry point is n8n's
  public webhook (`infra/n8n/workflows/README.md`): `POST
  https://<n8n-domain>/webhook/notify` with `Authorization: Bearer
  <webhook_secret>` and envelope `{domain, severity, title, body, source}`;
  n8n routes by `severity` (`page`→push, `log`→archive) and forwards to
  Apprise internally. A failed `kubelab-maintenance.service` triggers
  `OnFailure=kubelab-maintenance-notify.service`, a oneshot posting a `log`
  severity envelope (informational, not paging — consistent with the role's
  own many `ignore_errors: true` sub-tasks; only a hard script abort, e.g.
  `apt-get clean` or `journalctl --vacuum-size` failing outright under
  `set -euo pipefail`, reaches this path at all).

  **Target is prod n8n for all 7 nodes, not each node's own env** (measured
  and user-confirmed): `n8n.kubelab.live` is publicly reachable with a real
  ACME cert and correctly 403s unauthenticated POSTs (verified live); staging
  n8n needs VPN + accepts only a self-signed cert, and three of the seven
  nodes (beelink, ace1, ace2) run `deploy_env: staging` — routing their
  failure alerts through staging n8n would make the alert path depend on
  ace1 (which hosts staging n8n) being powered on, the exact "detection with
  nobody watching" shape (MON-002/#912) this ticket exists to close. Prod
  n8n is always-on per ADR-028.

  **Secret plumbing** (measured, not assumed): `apps.services.automation.notify.webhook_secret`
  holds *different* values in `staging.enc.yaml` and `prod.enc.yaml` (hash-compared,
  not read) — it's each n8n instance's own separately-configured Header Auth
  credential, absent from `common.enc.yaml`. Since every node's playbook
  already unconditionally decrypts `common.enc.yaml`, but only 2 of 7
  (vps, rpi4) currently also decrypt `prod.enc.yaml`, the prod value moves
  from `prod.enc.yaml` into `common.enc.yaml` under the same key path —
  mirroring the precedent already documented in `provision-aws1.yml` itself
  ("hub creds always in common.enc.yaml", lessons 2026-03-27/03-28). No new
  decrypt task needed on any of the 7 playbooks; staging n8n's own credential
  in `staging.enc.yaml` is untouched (env-overlay merge still gives staging
  its own value where declared, common everywhere else). `SecretSpec.envs`
  stays `("staging", "prod")` unchanged — that's an audit statement,
  independent of physical storage location, per the existing SSOT-014
  precedent. The `rotate_note` needs updating to state that rotating the
  prod value requires re-provisioning the fleet (static file per node,
  refreshed on next `make provision` — the same pattern already used for
  the CrowdSec bouncer key and Headscale pre-auth key; nodes never hold a
  SOPS decryption key themselves, only the plaintext Ansible already
  resolved).
- **Verification blast radius**: seven nodes across always-on (vps, aws1,
  rpi3) and on-demand (beelink, ace1, ace2, rpi4) hardware. Each node's
  rollout must be verified live (`systemctl list-timers` + an idempotent
  re-run showing the timer tasks converge to `ok`), not inferred from a
  green playbook exit code — per this lane's standing rule against claiming
  verification of hardware that wasn't actually measured. aws1 is the one
  node where the timer already exists; its acceptance criterion is that
  provisioning **restores/converges** the existing timer, not merely
  installs a new one — the whole motivation for this ticket is that a Spot
  replacement wipes it, so a fresh aws1 recreation needs to demonstrably
  come back with the timer intact via provisioning alone.

## Acceptance criteria

- [x] `maintenance_install_timer` defaults `true` in `roles/node_maintenance/defaults/main.yml`; a new `maintenance_run_cleanup` boolean (default `true`) gates the cleanup tasks so the two concerns can vary independently.
- [x] `node_maintenance` is included (role invocation, not just referenced) in the seven provisioning playbooks: `provision-vps.yml`, `provision-aws1.yml`, `provision-bee.yml`, `provision-rpi3.yml`, `provision-rpi4.yml`, `provision-ace1.yml`, `provision-ace2.yml`, each passing `maintenance_run_cleanup: false`.
- [x] `maintain.yml`'s existing `make maintain NODE=x TIMER=1` behavior is unchanged (still runs cleanup + optional timer install on demand); a regression check confirms no diff in its default invocation.
- [ ] Each of the seven nodes shows `kubelab-maintenance.timer` active via `systemctl list-timers` after a real (non-check) provisioning run, and a second real run of the same playbook converges to `changed: 0` for every `node_maintenance` task (idempotence, not just a green exit). **6/7 done** (vps, beelink, rpi3, rpi4, ace1, ace2) — aws1 was offline (Spot interruption) for this entire session; see verification.md's follow-up note.
- [x] `docs/runbooks/` gains a maintenance-timer entry (per the issue's own Scope section) covering what the timer does, how to check its status/logs, and how to temporarily disable it on a node.
- [x] `kubelab-maintenance.service` carries `OnFailure=kubelab-maintenance-notify.service`; the notify unit POSTs a `log`-severity envelope to `https://n8n.kubelab.live/webhook/notify` (all 7 nodes, same target, per the confirmed design) using a fleet-wide secret file resolved from a dedicated `common.enc.yaml` key.
- [x] The notify path is proven two ways without waiting a week for a real failure: (a) `systemctl start kubelab-maintenance-notify.service` directly delivers a message end-to-end; (b) a deliberate, reverted failure injection (e.g. a temporary `ExecStart=/bin/false` drop-in) on one node proves the `OnFailure=` linkage itself fires the notify unit.
- [ ] `secrets_manager.py`'s `rotate_note` for `apps.services.automation.notify.webhook_secret` is updated to state that rotating the prod value requires re-provisioning the fleet (static file per node).

## References

- Bitácora board: kubelab#928
- Related: #959 (Docker-published-port ufw gap, cited for the same "declared in git vs. actually true" pattern this ticket closes), #858 / ANSIBLE-030 (dev_node housekeeping, adjacent not overlapping)
- Role: `infra/ansible/roles/node_maintenance/`
- Playbook: `infra/ansible/playbooks/maintain.yml`
