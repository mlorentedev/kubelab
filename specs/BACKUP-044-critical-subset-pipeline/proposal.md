---
id: "BACKUP-044-critical-subset-pipeline"
type: spec
status: draft # draft | implementing | verifying | archived
created: "2026-08-15"
issue: "kubelab#1056"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
---

# BACKUP-044: the critical-subset backup pipeline

> Step [3] of the backup epic (**kubelab#1090**). Read #1090 first — it holds the sequencing, the ticket dispositions and the reasoning that produced this scope.

## Why

<!-- from issue #1056: BACKUP-044: Gitea loses its backup path when it moves off K3s -->

ADR-061 moved Gitea to the Beelink and the prod PVC backup CronJob did not follow it. That is the ticket. Measuring the fleet to size the fix (#449, all seven nodes, 2026-08-15) found the ticket was describing one symptom of something wider:

**One node of seven has any backup at all, and its copy never leaves that node.** `common.yaml` defines a `backup` block for the VPS only, writing to `/opt/backups` with retention 3. Confirmed on disk. Headscale's SQLite — the VPN control plane, ratified Tier 1 — is covered by exactly that local-only copy. Uptime Kuma on the RPi3, which per ADR-028 is the *monitoring of record* for prod, has no backup at all. Neither does Pi-hole's query history, nor Gitea.

The direction has been settled since June and never built. [ADR-049](../../docs/adr/adr-049-edge-object-storage-placement-doctrine.md) D3 assigns the critical subset to Cloudflare R2, and ADR-061:96 names the consequence of that gap precisely:

> `infra/k8s/overlays/prod/backup.yaml` targets `http://minio:9000`, which makes the in-cluster MinIO **the only backup destination that currently exists**. So MinIO's location is not free — it is *coerced* to always-on by a dependency that ADR-049 D3 has already superseded **by decision but not by implementation**. Same-cluster storage was never an offsite copy.

So this is not "add a backup for Gitea". It is the first real implementation of a doctrine that exists on paper, and the reason #972 cannot be decided today.

## What

An offsite backup pipeline for the ratified critical subset (#452, 2026-08-15): **restic to Cloudflare R2**, driven from Ansible, covering four nodes with two trigger models.

| Node | Consumers | Trigger model |
|---|---|---|
| Beelink (on-demand) | Gitea repos + SQLite | uptime-bounded |
| VPS (always-on) | Headscale SQLite, Authelia, Postgres | wall-clock |
| RPi3 (always-on) | Uptime Kuma SQLite | wall-clock |
| RPi4 (on-demand) | Pi-hole `pihole-FTL.db` | uptime-bounded |

Observable changes:

1. **An Ansible role** rendering a systemd service + timer per node. On always-on nodes the timer is a plain schedule. On on-demand nodes it fires **on boot, hourly while up, and on graceful shutdown** — because the homelab runs in 3-4 hour bursts, a threshold at or above the session length never fires at all (#1090). This asymmetry is deliberate and must not be generalised fleet-wide.
2. **Backup sources declared as an SSOT allow-list**, not by excluding known-dead volumes. The current `backup` role enumerates every Docker volume minus an exclude list, which is why the VPS backs up ~306M of dead pre-K3s volumes while six other nodes are uncovered (#1092). An allow-list inverts the failure direction: a new dead volume is ignored by default, and a new *live* one is a visible omission.
3. **`sqlite3 .backup` before archiving**, for all four live SQLite databases — Headscale, Gitea, Uptime Kuma, Pi-hole FTL. All four were measured with continuously-updating mtimes; a file copy of a live SQLite is not a consistent snapshot.
4. **One restic repository per node in R2**, with a retention policy and `restic check` as part of the run rather than a separate audit.
5. **Failure is observable** on the same path as the existing PVC-backup failures (#686). A failed run while the node is up alerts; a window missed because the node was off does not, and must not.
6. **A restore exercised at least once**, with the transcript captured. A backup that has never been restored is a hypothesis.

## Out of scope

- **The bulk tier.** ADR-049 D3's other leg is Hetzner Storage Box + Borg (#471, #473). It has its own provisioning, and the Storage Box does not appear to exist yet. R2 needs no provisioning of its own, which is part of why the critical subset goes first.
- **Migrating the prod PVC CronJob off in-cluster MinIO.** It keeps working. Moving its remaining consumers is what eventually releases #972, and it is a later phase of #1090 — this spec must simply not add a *new* consumer of `minio:9000`.
- **Tier 3 items** (Loki, CrowdSec config, `gravity.db`, MinIO, the rebuildable caches). Ratified as not needing backup; `gravity.db` is regenerated in full by `pihole -g`.
- **Velero.** ADR-024's Phase 5 names it, and the 2026-07-02 platform audit calls the 17-ticket Borg/StorageBox plan heavier than external consensus. This spec builds the doctrine that exists.
- **Cleaning up the orphans in #1092.** A prerequisite, not this spec's work — but see the risks: the RPi3 instance has to be resolved or explicitly disambiguated before its backup is written.
- **Getting repositories into Gitea** (#1076). Gated on this spec's restore being exercised, per #1090's step [4].
- **The SOPS age key's own offsite copy** (#479). Related and separately tracked; see the circularity risk below.

## Risks / open questions

- **The restic repository password is a secret whose loss makes every backup unrecoverable — and storing it only in SOPS is circular.** SOPS secrets are decrypted by an age key that is itself part of what a disaster destroys (#479). If the R2 repo password lives only in `common.enc.yaml`, then recovering from a total loss requires the age key, which is exactly the artefact the operator confirmed lives on a laptop and an encrypted USB — both in one physical location. **This needs an answer before implementation, not after:** either the repo password is escrowed independently of SOPS, or the recovery procedure explicitly depends on the USB and says so in the runbook. Settling it is a Part 0 task, not an implementation detail.
- **R2 credentials and bucket do not exist yet.** New SOPS keys plus `SECRET_CATALOG` registration. **Check `envs` against the ANSIBLE-033 failure mode**: a tuple matching no real env makes the secret vanish from every audit silently, and a backup credential missing from the audit is the worst possible thing to have silently absent.
- **restic's memory footprint on the RPi3, which has 1GB of RAM.** restic's index is held in memory and scales with repository size, not with the size of the current snapshot. The payload here is small (18M), but this must be *measured* on the device rather than assumed from the payload — the RPi3 is the monitoring of record, and OOM-killing it to back it up would be an own goal. If it does not fit, the fallback is streaming the snapshot to a node that can run restic, which changes this node's design.
- **"Backup on power-on, before the service accepts its first write" is an ordering claim, and systemd's `Persistent=true` does not quite make it.** `Persistent=true` runs a missed timer shortly after boot, which is close but neither ordered against the container's start nor guaranteed to precede the first write. Getting this wrong means the on-boot snapshot captures a database that the new session has already modified — still useful, but no longer the clean "previous session" restore point the design claims. Needs an explicit `Before=`/`After=` relationship with the compose unit, verified across a real power cycle.
- **The RPi3 has two Uptime Kuma volumes and the orphan's name looks more canonical.** Live is `uptime_kuma_data`; the 26M orphan is `uptime-kuma_uptime_kuma_data`, frozen since 2026-03-28 (#1092 instance 1). A backup written against the wrong name would capture 18M of healthy-looking data the service does not read, and would pass any check asserting only that a non-empty backup exists. The allow-list must name the live volume explicitly, and the discriminator recorded, even if the orphan is not deleted first.
- **A restore has to be tested somewhere that is not the source.** Restoring Gitea over the live `/opt/gitea/data` to prove the backup works would risk the thing being protected. The 2026-08-10 Gitea research proposes restoring into an ephemeral instance instead, which doubles as the #492 DR drill. Worth reusing; not worth expanding this spec to close #492.

## Acceptance criteria

- [ ] Every ratified Tier 1 and Tier 2 item is present in its node's R2 restic repository, verified by listing snapshots from a machine that is not the source node — not by reading the playbook.
- [ ] Each of the four live SQLite databases is snapshotted with `sqlite3 .backup`, demonstrated by restoring one and passing an integrity check on the restored copy.
- [ ] A restore is exercised end-to-end for Gitea and for at least one always-on consumer, into a scratch location, with the transcript captured in `verification.md`. Content is verified, not just exit codes.
- [ ] A failed backup raises an alert on the #686 path — demonstrated by injecting a failure, not by configuration review. A window missed because an on-demand node was powered off produces **no** alert, demonstrated across a real power cycle.
- [ ] The on-demand trigger model is exercised across a real power cycle on the Beelink: a snapshot exists from before the shutdown and another from shortly after the next boot, and the boot-time snapshot is ordered before Gitea accepts writes.
- [ ] Backup sources are enumerated from an SSOT allow-list: adding a new stateful path requires editing `common.yaml` and nothing else, and a path present on disk but absent from the SSOT is reported rather than silently included or silently skipped.
- [ ] `restic check` passes on every repository as part of the scheduled run.
- [ ] This spec introduces no new consumer of the in-cluster MinIO (`minio:9000`) — the guarantee #1056's original AC2 was reaching for.

## References

- Bitácora board: **kubelab#1056** (see the `issue:` frontmatter field)
- **kubelab#1090** — the backup epic: sequencing, dispositions, the RPO/trigger reasoning.
- **kubelab#452** — the ratified tiers (closed 2026-08-15). Defines exactly what this spec covers.
- **kubelab#449** — the measured catalog, all seven nodes.
- **kubelab#1092** — orphaned state; its AC3 (SSOT allow-list) is this spec's substrate, and its instance 1 is a prerequisite for the RPi3.
- **kubelab#596** — restic to R2, the mechanism decision. **kubelab#479** — the age key, and the circularity above.
- [ADR-049](../../docs/adr/adr-049-edge-object-storage-placement-doctrine.md) D3 (amended 2026-08-15 to restic), [ADR-061](../../docs/adr/adr-061-stateful-service-placement.md), [ADR-024](../../docs/adr/adr-024-pvc-backup-strategy.md), [ADR-028](../../docs/adr/adr-028-operational-topology.md).
