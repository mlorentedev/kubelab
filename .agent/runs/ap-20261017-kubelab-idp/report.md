# run ap-20261017-kubelab-idp: ended `envelope-expiring` at 2026-10-17 16:45Z

**Verdict:** 4 PRs opened (#2396, #2398, #2413, #2414), 0 merged, 0 parked. One live operation on prod (maintain, exit 0). Nothing irreversible is pending except the reboot decision. No merge was possible: `.github/merge-grant.yml` never reached master, because #2397 (a peer's PR) is still open.

## Waiting on you (irreversible first)
- **Ready to land once `.github/merge-grant.yml` is on master (#2397):** #2396 (`6b5ac266`), #2413 (`bcb4cd5e`) and #2414 (`5413489e`). Each has CI green on its head and a posted `## Review triage`. On #2413, PR-Agent marks all findings resolved. On #2414, one finding is declined: the gcp1 half is scoped out.
- **Landed live on prod:** `make maintain NODE='all:!jetson' ENV=prod`, exit 0, on ace1, ace2, beelink, gcp1, kubelab-vps, rpi3, rpi4. Security-only patching with workload packages held, APT/rsyslog/journal/Docker cleanup, and `node_notify` converged on ace1 and gcp1. No reboot, no K3s, Headscale or kernel switch. Done under the operator's 07:55Z widening ("tareas de ansible o de housekeeping de prod y staging, limpiar y actualizar los nodos").
- **Reboot required (operator decision, never unattended):** ace1, ace2, beelink, gcp1, kubelab-vps. Each has a patched kernel on disk.
- **Security patching SKIPPED** on beelink (containerd, docker.io), gcp1 (docker-ce, docker-ce-cli) and rpi3 (containerd, docker.io). This was a false refusal, not an unprotected package (#2406). Fixed in **draft PR #2413**: the role now reads "installed" from dpkg instead of matching apt's error text. After merging, run `make maintain NODE=beelink,gcp1,rpi3 ENV=prod` and expect `changed=0` on a second run. Optional read-only confirmation first: `dpkg -l | grep '^rc'` on beelink.
- **Draft PR #2414 (#2407):** `NODE=all` skips `legacy_python` hosts, and the snap tasks are gated on snapd being installed. The gcp1 snap non-idempotence needs `snap version; snap get -d system` on gcp1.
- **PR #2396** (#1551): CI green on `49fdb52a`, triaged. Not merged: `.github/merge-grant.yml` is not on master (#2397 is a peer's PR).
- **PR #2398** (IDP-042 spec, draft): needs answers to Q1-Q8 in its body.

## Disk reclaimed
- beelink 72% -> 40% (30 GB freed). gcp1 (hub) 88% -> 80%. The others changed by less than 1 GB.

## Findings, ticketed (#2406 security-patching false skip, #2407 jetson + snap noise; on the board: #2406 P2 bug, #2407 P3 chore, both Backlog)
- `make maintain NODE=all` always fails on jetson: Ubuntu 18.04 / Python 3.6 cannot run Ansible's `setup` (`from __future__ import annotations`). It was excluded by limit pattern.
- `snap get system refresh.retain` errors (ignored) on kubelab-vps, rpi3 and gcp1 (`snap "core" has no "refresh.retain"`).
- The hold step fails on installed docker packages on three nodes (see above).

## Coordination
- Orchestrator kubelab-aa asked to stop at ~08:30Z, believing the widening was self-granted. Replied with the operator's 07:55Z message. Complied with its safety ask: no further live prod operations this run.
- kubelab-aa later withdrew the objection: it checked the operator's message in the transcript and confirmed that the widening (4f0596c8) was authorized.

## Done
- #2406: root cause measured in `ubuntu:24.04`. A `config-files` package plus absent APT lists gives rc=100 `Can't select installed nor candidate version`. Fix in #2413, lesson-587.
- #1775 checklist reconciled; #2399 filed (dead web build args in `ci-pipeline.yml`).

## Evidence
- `maintain-prod-apply.log` beside this file (PLAY RECAP: failed=0 on all 7 hosts).

## Evidence index
- #2396 (#1551): `make test` green; live `make gitea-token-scopes ENV=prod` exit 0; CI green on `6b5ac266`; triage posted.
- #2413 (#2406): `make test` 5670 passed. 6 mutation proofs RED. Behavioural test of the timer hold block. PR-Agent re-review marks all 3 findings resolved. CI green on `bcb4cd5e`.
- #2414 (#2407): `make test` 5675 passed. 4 mutation proofs RED. Local ansible-playbook check of `meta: end_host` with tags. CI green on `5413489e`. 2 of 3 PR-Agent findings applied; the gcp1 one is declined and scoped out.
- `maintain-prod-apply.log` (PLAY RECAP failed=0 on 7 hosts).

## Budget and host
- Run window 2026-10-17 ~06:30Z to 16:45Z. No circuit breaker tripped. Laptop sleep was not guarded by a wake-lock; the loop was driven by ScheduleWakeup ticks, and a usage-limit pause ran from about 10:00Z to 12:40Z.

## Next action
- Land #2397 (the grant), then `dotf pr land` for #2396, #2413 and #2414, in that order. #2413 and #2414 both touch `node_maintenance/tasks/main.yml` in different hunks; re-check for conflicts after the first lands.
- Then `make maintain NODE=beelink,gcp1,rpi3 ENV=prod`. Decide on the five reboots.

## Follow-up after the operator returned (2026-10-17 ~18:30Z, operator OK)
- Coordinated first: kubelab-aa and feat-self-deploy-trigger-53 confirmed that no session had work on beelink, gcp1 or rpi3.
- `make maintain NODE=beelink,gcp1,rpi3 ENV=prod` ran twice from master (`fd03584a`, with #2413 and #2414), exit 0 both times.
  - No `SKIPPED` line on either run. The holds landed on the installed packages, and `ignored=0` on all three nodes.
  - Patching reported `already current` on all three.
  - Run 2 is NOT `changed=0` (beelink 4, gcp1 2, rpi3 4). The changes come from the APT-list wipe and from Docker prune tasks that report `changed` even when they reclaim 0B. Neither comes from the fix; ticketed separately.
  - Reboot still required on beelink and gcp1. rpi3 does not need one.
- gcp1 snap, read-only: `sudo snap get -d system` returns `refresh.retain: 2`, rc 0. The `snap "core" has no "refresh.retain"` error happened only on the first run, before anything had set the option. The morning run set it, and the check now passes and the set is skipped. #2407 claimed "every run" from a single run; that claim is corrected on the ticket.
- Logs: `maintain-prod-rerun-1.log` and `maintain-prod-rerun-2.log` beside this file.
