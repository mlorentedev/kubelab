---
id: "BACKUP-067-headscale-restore-drill"
type: spec
status: implementing # draft | implementing | verifying | archived
created: "2026-10-01"
issue: "mlorentedev/kubelab#1994"
tags: [spec, proposal, backup, headscale]
template_version: "1.0"
---

# BACKUP-067: Headscale restore drill

## Why

<!-- from issue #1994: BACKUP-067: Headscale restore drill -->

Headscale is the mesh's control plane and a bootstrap dependency (ADR-015): every node reaches the cluster through it. Epic #1923 puts it in tier 1 (RPO 4h, RTO 4h), and its R2 backup (`backup.sources.vps.headscale`) has never been restored. If the restored database is unreadable, or the restored server keys differ from live, every node has to re-register by hand, one machine at a time, several of them on-demand hardware that is powered off. This is the epic's item "#433 OPS-003: Headscale volume restored, nodes reconnect without re-registration".

## What

`make backup-drill-headscale ENV=prod` restores the newest VPS snapshot's Headscale capture from R2 into a private temp directory on the machine running it. It passes only if the restore brings the control plane back whole:

1. **The database is intact.** `PRAGMA integrity_check` on the restored `db.sqlite`, read-only and in-process, before anything opens it for writing.
2. **The server identity is the live one.** The restored `noise_private.key` and `derp_server_private.key` hash the same as live's, read over SSH with `sudo -n sha256sum` on the volume's mountpoint. Only `match` or `mismatch` is printed. A client trusts the server by the noise key's public half, so a matching key is what lets a node reconnect to a restored server without re-registering.
3. **The restored server starts and knows the mesh.** The image pinned in `common.yaml` starts on the restored data with `--network none`, as the invoking user, with a drill-only config (no DERP map download, no listener outside the container). Its CLI lists nodes and users.
4. **The restore is complete against live.** Live is read with the same CLI over SSH:
   - every live node created before the snapshot is in the restore under the same id with the same machine key (a node that re-registered under the same name gets a new id, so names are never the key);
   - every live user created before the snapshot is in the restore;
   - a node or user newer than the snapshot, or deleted since, is reported, not failed.

   A live read that fails or answers empty is CANNOT CHECK, never a pass.
5. **It leaves nothing behind.** The container is removed and read back as gone (`remove_scratch_container`, lesson-498), and the temp directory is removed and checked, on every exit path. The restore holds both private keys.

The drill prints the measured RTO (download, then time until the CLI answers).

## Out of scope

- Restoring into live Headscale. The drill never writes to the VPS; the real restore is a runbook section.
- A real client reconnecting to the scratch server. With `--network none` nothing can reach it; the keys are the proof (Q2).
- The ACL policy. It is rendered from git (`policy.hujson.j2`), not backed up.
- Scheduling the drill (#1211).

## Risks / open questions

- **Q1 [AGENT-DRAFT — review before archive]:** where the drill runs. Same question as BACKUP-040's Q1, answered the same way: the workstation, because the command is host-agnostic.
- **Q2 [AGENT-DRAFT — review before archive]:** what proves "nodes reconnect without re-registration". Proposed answer: identical noise and DERP keys plus every node present under its id and machine key. A client re-handshakes with a server that holds the same noise key and finds its machine key registered. The scratch server proves this through the keys and the database, not through an actual reconnect.
- The drill reads two private-key hashes from live. A SHA-256 of a 32-byte random key reveals nothing usable, and the drill does not print it anyway.
- The headscale image is distroless (no shell), so the teardown cannot wipe files from inside a container as the Gitea drill does. Running the container as the invoking user means everything it writes belongs to that user, so a plain `rmtree` removes it on any host, rootless or not.

## Acceptance criteria

- [x] AC1: `make backup-drill-headscale ENV=prod` restores the newest VPS snapshot, fails when `db.sqlite` or either key is missing or `integrity_check` is not `ok`, and fails when either restored key differs from live.
- [x] AC2: The pinned image starts on the restored data with no network. The drill fails and names the node or user when a live node created before the snapshot is missing or carries a different machine key, or a live user created before the snapshot is missing.
- [x] AC3: The drill is CANNOT CHECK, never a pass, when live nodes, live users or live key hashes cannot be read or come back empty, and when no snapshot is readable.
- [x] AC4: On every exit path the container and the temp directory are gone, read back. Tests pin it; `verification.md` shows it measured.
- [x] AC5: `docs/runbooks/offsite-backup-restore.md` documents the drill and the real restore onto the VPS. `verification.md` records the prod transcript and measured RTO.

## References

- Epic #1923; #433 (OPS-003, restore half moved here); #1211 (scheduling)
- `toolkit/features/postgres_drill.py` (BACKUP-046), `toolkit/features/gitea_drill.py` (BACKUP-040)
- `toolkit/features/headscale_nodes.py` (the live CLI over SSH)
- ADR-015 (Headscale outside K3s), lesson-498, lesson-416
