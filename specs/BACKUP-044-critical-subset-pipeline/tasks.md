---
tags: [spec, tasks]
created: "2026-08-15"
---

# Tasks - BACKUP-044-critical-subset-pipeline

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers:**
> - `[P]` — no dependency on another unchecked task, safe to run in parallel.
> - `[AC<n>]` — helps satisfy acceptance criterion #`<n>` from `proposal.md`.

> **Read [kubelab#1090](https://github.com/mlorentedev/kubelab/issues/1090) first** — it holds the sequencing, the ticket dispositions and the RPO reasoning this list implements. Part 0 is closed; its transcripts are in `verification.md` and several of its answers **contradict what `proposal.md` originally assumed**. Do not implement against the proposal's first draft of R-C or AC4.

## Setup

- [x] Branch created from origin/master: `docs/backup-044-gating-risks` (Part 0 record + this list; implementation branches come later, one per part) ✓ 2026-08-15
- [x] `proposal.md` is complete and acceptance criteria are testable ✓ 2026-08-15 — AC4 corrected on the same date, see Part 0
- [x] No open questions left in `proposal.md` "Risks / open questions" ✓ 2026-08-15 — all three gating risks settled by on-device measurement

## Implementation

### Part 0 — settle the gating risks against live nodes, before any config

Nothing here changed backup state. Each task turned a guess into a recorded fact, and two of them invalidated tasks that would otherwise have been written below. Full transcripts in `verification.md`.

- [x] [P] **R-C — is a boot snapshot orderable before Gitea's first write?** ✓ 2026-08-15 — **yes, but not against the unit the proposal named.** Measured on the Beelink: dockerd starts at +10s, `kubelab-compose.service` at +33s, and Gitea starts at +33.5s — *with the compose unit*, because its `ExecStop` marks containers explicitly stopped and `unless-stopped` honours that. On a power cut `ExecStop` never runs and dockerd resurrects Gitea at +10s, so `Before=kubelab-compose.service` is 23 seconds too late in exactly the scenario an on-demand node exists to survive. **Correct constraint: `Before=docker.service`**, which also makes the snapshot quiescent.
- [x] [P] **R-B — does restic fit in the RPi3's 1GB?** ✓ 2026-08-15 — **yes, with a measured cap.** A 974MiB / 24,668-file backup and a `check` over a 399M repo completed on the 906MB node without an OOM, ~40x the real workload; the streaming fallback is not needed. The cap required fixing a prerequisite first (see below) and then measured out at a floor between 16M and 24M. **Deploy at `MemoryMax=128M` with `MemorySwapMax=0`.**
- [x] **R-B prerequisite — the RPi3 could not enforce any memory limit.** ✓ 2026-08-15 — the memory cgroup controller was absent, so every `MemoryMax` was a silent no-op and two measurement attempts produced nothing. Filed and fixed as **ANSIBLE-040 (#1101, PR #1103)**: new `rpi_boot` role, controller now present, control experiment inverts. Discovered *because* Part 0 measured instead of assuming.
- [x] [P] **R-A — where does the restic repository password live?** ✓ 2026-08-15 — **independent escrow in Bitwarden, decided by the operator.** A password stored only in SOPS is decrypted by an age key a disaster destroys (#479), so recovery would depend on the artefact being recovered from. Bitwarden is hosted and independent of both the age key and the site.
- [x] Record all three answers in `verification.md` with the commands and their output ✓ 2026-08-15 — including the two failed measurement attempts, because the second one nearly shipped a false result.

### Part 1 — the SSOT allow-list, before anything writes a backup

The substrate. #1092's AC3 changes the model from "enumerate volumes minus an exclude list" to "back up exactly what is declared", and Part 0 found the concrete reason it cannot stay volume-shaped.

- [ ] [AC6] Add a test that fails when a declared backup source does not exist on disk, **and** when a path exists on a covered node but is absent from the SSOT. Demonstrate both red first. The second half is the one that matters: an allow-list that only validates what it declares cannot report an omission, which is the failure mode #1092 exists to prevent.
- [ ] [AC6] Add a `backup.sources` block to `common.yaml`, keyed per node, **enumerating paths rather than Docker volumes**. Part 0's decisive evidence: on the Beelink, Gitea is `bind src=/opt/gitea/data` and MinIO is `bind src=/opt/minio/data` — neither is a Docker volume, so `docker volume ls` returns only buildx caches and the runner toolcache. A volume-shaped allow-list would archive rebuildable junk, miss Gitea and MinIO entirely, and report success.
- [ ] [AC6] Name the RPi3's Uptime Kuma source as the **volume mountpoint of `uptime_kuma_data`**, and record the discriminator in a comment. The orphan `uptime-kuma_uptime_kuma_data` is *larger* (26M vs 22M) and its name looks more canonical; three signals agree on which is live (mtime, size, and `docker inspect uptime-kuma` reporting `volume uptime_kuma_data -> /app/data`). #1092 instance 1 need not be deleted first, but it must not be silently selected.
- [ ] [AC1] Cover all four nodes in the block: Beelink (Gitea), VPS (Headscale SQLite, Authelia, Postgres), RPi3 (Uptime Kuma), RPi4 (Pi-hole `pihole-FTL.db`). Today `common.yaml` has a `backup` block for the VPS only — six of seven nodes are uncovered, which is the headline of #449.
- [ ] Leave the existing `roles/backup` untouched in this part. It still serves the VPS's local copy; replacing it is Part 2's job and must not happen in the same commit as introducing the SSOT.

### Part 2 — credentials and the destination, before the role that uses them

- [ ] [P] Create the Cloudflare R2 bucket and access credentials. R2 needs no provisioning of its own, which is part of why the critical subset goes first (ADR-049 D3).
- [ ] [AC1] Register the R2 access key and secret in `SECRET_CATALOG` (`toolkit/features/secrets_manager.py`). **Check `envs` against the ANSIBLE-033 failure mode**: a tuple matching no real env makes the secret vanish from every audit silently, and a backup credential silently absent from the audit is the worst possible thing to have silently absent. Confirm with `make secrets-audit` that the count rises.
- [ ] [AC1] Escrow the restic repository password in **Bitwarden, not SOPS** (Part 0 / R-A). Document in the runbook exactly which artefact lives where — R2 access credentials in SOPS because they are operational and rotatable, the repository password in Bitwarden because it is the one thing whose loss is unrecoverable and it must not depend on the age key. A split nobody wrote down becomes its own failure mode. Coordinate the vault item with the dotfiles lane (taxonomy changed in dotfiles#982).
- [ ] [P] Decide and record how restic is installed per node. Part 0 measured with a throwaway static binary deliberately, so the install path is an open choice: distro package (absent from the RPi3's apt candidates), pinned static binary, or container. Whichever wins needs a version pin in `common.yaml` like every other image, not a floating download.

### Part 3 — the backup role: capture and ship, split deliberately

- [ ] [AC2] Write the capture step: `sqlite3 .backup` for all four live SQLite databases (Headscale, Gitea, Uptime Kuma, Pi-hole FTL) into a staging directory, then everything else by path from the Part 1 allow-list. All four were measured with continuously-updating mtimes; a file copy of a live SQLite is not a consistent snapshot. Part 0 demonstrated this by accident — the payload measured 21.6 MiB before the RPi3 reboot and 17.6 MiB after, because the restart checkpointed the WAL.
- [ ] [AC7] Write the ship step: restic to R2, one repository per node, with a retention policy and `restic check` inside the scheduled run rather than as a separate audit.
- [ ] **Keep capture and ship as two units, not one.** Capture must be ordered against `docker.service` (Part 4) and must be fast, because it delays every boot. Ship needs the network and must never sit on the boot path — ordering an R2 upload before dockerd would put a network round-trip in front of Gitea starting on every power-on.
- [ ] [AC7] Run restic under `MemoryMax=128M` and `MemorySwapMax=0` on the RPi3 (Part 0 / R-B: floor between 16M and 24M, so this is >5x headroom and ~14% of the node's RAM). The swap setting is not decoration — the node has ~900MB of swap and a restic that swaps will thrash the monitoring of record instead of failing cleanly. **This is only enforceable because ANSIBLE-040 landed**; assert the controller is present rather than assuming it.
- [ ] Replace the VPS's use of `roles/backup` with the new role, and delete the exclude-list enumeration. Its ~306M of dead pre-K3s volumes stop being backed up as a side effect, which is the point.

### Part 4 — trigger models, asymmetric on purpose

- [ ] [AC1] Always-on nodes (VPS, RPi3): a plain wall-clock `OnCalendar` timer. RPO from the ratified tiers (#452): Tier 1 <6h, Tier 2 <24h.
- [ ] [AC5] On-demand nodes (Beelink, RPi4): fire **on boot, hourly while up, and on graceful shutdown**. An interval at or above the session length never fires at all, because the homelab runs in 3-4 hour bursts — an RPO trigger is bounded by session length, not by the RPO number (#1090).
- [ ] [AC5] Order the boot capture `Before=docker.service`, **not** `Before=kubelab-compose.service` (Part 0 / R-C). Do not take the shortcut the proposal originally implied: `Persistent=true` is not an ordering primitive, and the compose unit is not the writer's real start trigger on the path that matters.
- [ ] [AC5] Handle the shutdown snapshot's ordering explicitly. systemd stops units in reverse dependency order, so a capture ordered `After=` the compose unit stops **first**, while Gitea is still running — a live-database snapshot, which is what `sqlite3 .backup` is for. Decide and document which of the two orderings is wanted rather than inheriting one by accident.
- [ ] This asymmetry is deliberate and must not be generalised fleet-wide. Say so in the role's defaults, where the next person changing it will read it.

### Part 5 — failure is observable, silence is not

- [ ] [AC4] Post a failure envelope to the **NOTIFY-001 fabric** — `POST https://<n8n>/webhook/notify`, the same envelope `roles/node_maintenance` already posts from bare metal — at severity **`log`** (decided 2026-08-15). **Correction carried from Part 0:** `proposal.md` originally said "the #686 path". No such path exists; `overlays/prod/backup.yaml` has no failure notification at all, only `failedJobsHistoryLimit: 3`, and #686 is the still-open ticket to create routing for minor sources. #686 is related, not blocking.
- [ ] [AC4] A window missed because an on-demand node was powered off must produce **no** alert. Alerting on the homelab being off trains the operator to ignore the channel, which is the same reasoning `common.yaml` already applies to staging probes.
- [ ] [AC4] Demonstrate both halves by **injecting a failure** (bad credential, unreachable bucket) and by a **real power cycle** — not by configuration review.
- [ ] Reuse `node_maintenance`'s hardening rather than re-deriving it: bounded curl timeouts, UTF-8-safe truncation, and the token passed so it is not visible in `ps` (ANSIBLE-038, #1088).

### Part 6 — a backup that has never been restored is a hypothesis

- [ ] [AC3] Restore Gitea end-to-end into an **ephemeral instance**, never over the live `/opt/gitea/data`. Restoring over the thing being protected to prove the backup works risks exactly what the backup exists for. Doubles as the #492 DR drill; do not expand scope to close #492.
- [ ] [AC2] Restore one SQLite database and run an integrity check **on the restored copy** — content verified, not exit codes.
- [ ] [AC3] Restore at least one always-on consumer into a scratch location, with the transcript in `verification.md`.
- [ ] [AC1] Verify every ratified Tier 1 and Tier 2 item is present, by listing snapshots **from a machine that is not the source node**. Reading the playbook is not verification.
- [ ] [AC8] Confirm this spec introduced no new consumer of `minio:9000`, the guarantee #1056's original AC2 was reaching for. Note that closing this does **not** release #972 on its own — other PVCs still target MinIO, and #1056's "blocked by #972" was backwards.

## Follow-ups, not this spec

- [ ] Unblock #1076 (repos into Gitea) once AC3 is green — #1090's step [4] gates it on an exercised restore, and populating the forge first makes the first repository the first thing with no recovery path.
- [ ] #1092's orphan cleanup stays separate; this spec only has to name the live source unambiguously.
- [ ] The bulk tier (Hetzner Storage Box + Borg, #471/#473) is a different pipeline with its own provisioning.
