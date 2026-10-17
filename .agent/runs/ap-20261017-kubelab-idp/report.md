# run ap-20261017-kubelab-idp (in progress, state checkpoint 2026-10-17 ~08:25Z)

## Waiting on you (irreversible first)
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

## Done
- #2406: root cause measured in `ubuntu:24.04`. A `config-files` package plus absent APT lists gives rc=100 `Can't select installed nor candidate version`. Fix in #2413, lesson-587.
- #1775 checklist reconciled; #2399 filed (dead web build args in `ci-pipeline.yml`).

## Evidence
- `maintain-prod-apply.log` beside this file (PLAY RECAP: failed=0 on all 7 hosts).
