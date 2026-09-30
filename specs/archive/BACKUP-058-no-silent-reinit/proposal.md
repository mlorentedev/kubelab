---
id: "BACKUP-058-no-silent-reinit"
type: spec
status: archived # draft | implementing | verifying | archived
created: "2026-09-29"
issue: "mlorentedev/kubelab#1921"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
---

# BACKUP-058: a deleted repository must not re-initialise silently

## Why

<!-- from issue #1921: BACKUP-058: node backup re-initialises a missing repository, so a deleted history heals silently -->

`node-backup-ship.sh.j2:78-81` runs `restic init` whenever `restic snapshots` fails, for any reason. If a node's repository is deleted (by mistake, by a compromised credential, or by a bucket operation), the next scheduled run creates a fresh repository holding one snapshot. `r2-backup-watcher` then reports that node healthy, because it checks that a complete newest snapshot exists, not that the history behind it is the same history. Every restore point before the deletion is gone, and nothing pages. The restore-readiness epic (#1923) puts protecting the copies before proving the restores, and this is the cheapest of those protections: a restore test proves little while the history it restores from can be replaced without anyone noticing.

## What

Two independent layers, one on the node and one outside it, both keyed to the **restic repository ID** (`restic cat config --json` → `id`), which is new for every `restic init` and never changes otherwise.

1. **The node refuses to re-initialise a repository it has shipped to before.**
   - After a successful ship, the node records the repository's ID in `/var/lib/node-backup/<destination>.repository-id` (`r2.repository-id` today; `storagebox.repository-id` arrives with #471). One file per destination, not one per node, so a second destination's first ship is a first ship.
   - `restic snapshots` exits 10 ("repository does not exist") and there is no marker: this is a first ship. The node runs `init`, ships, and writes the marker.
   - Exit 10 with a marker present: the node fails loudly, with no `init`. The message names the destination, the expected ID and the override. `OnFailure=` pages through `node_notify`.
   - Exit 0, but the repository's ID differs from the marker: the repository was replaced. The node fails loudly the same way.
   - Any other exit code (wrong password, bad credential, network): the node exits non-zero with restic's error and never runs `init`.
   - The ID is compared on **every** ship, not only the first: a replaced repository answers `snapshots` with exit 0, so the comparison is the only thing that sees it. It costs one small `cat config` read per run and must not be optimised away.
2. **The watcher pins each repository's identity.**
   - The expected repository ID per node is declared in `common.yaml` as `backup.r2.repository_ids: {<node>: <id>}`, next to `repo_prefix`. It is not a secret. It is per destination, so the Storage Box leg gets its own `backup.storagebox.repository_ids`.
   - `make sync-r2-watcher-targets` carries the ID into `targets.txt` as a fixed third column (`<node> <repository URL> <repository id> <declared source>...`). The sources slurp the rest of the line, so the column can never be empty: a node with no declared ID gets the token `-`.
   - The probe compares the declared ID with the ID it reads from R2 (`cat config`, read-only, `--no-lock --no-cache`), and prints the ID it read on the `r2_backup_node` line (`"repository_id":"…"`). The field is additive, since the rule reads only the fleet line, and it makes the onboarding page actionable: the ID to declare is in the alert. A mismatch (`reason: repository id changed`) or a missing declaration (`reason: repository id not declared`) makes the node unhealthy. That turns the fleet line to `healthy:0`, so the existing `obs015-r2-backup-health` rule fires. No new rule is added and no threshold is involved.
   - The watcher also catches the case the node cannot see: an OS reinstall loses the marker *and* the repository is gone.
3. **A deliberate, recorded override.**
   - `make backup-repo-reinit NODE=<node> DEST=r2 ENV=<env>` removes that destination's marker on the node, through the toolkit/Ansible path. The next ship then initialises a new repository. It:
     - reads and logs the marker's current ID before removing it (the "recorded" half of deliberate and recorded);
     - validates `DEST` against the known destinations and refuses anything else, never removing a path built from raw input;
     - takes exactly one `NODE`, never `all`;
     - fails when the node is unreachable (no `ignore_unreachable`, unlike `backup-node.yml`), because an operator needs to know the override did not happen.
   - The operator then updates the declared ID in `common.yaml` through a PR. Accepting a new history is therefore a reviewed change, never a side effect.
   - `docs/runbooks/offsite-backup-restore.md` gains a section, "Repository missing or replaced", covering what the node does, what the watcher reports, and the two steps above.

Idempotence: the marker is written by the ship script at run time, never by the Ansible role, so re-running the role (`changed=0`) cannot create, overwrite or remove it. Only a ship and `make backup-repo-reinit` touch it.

Rollout: nodes have no marker today. The first ship after deploy finds the existing repository (exit 0) and writes its ID, so existing history is adopted without any `init`. The four current IDs are read from R2 and declared in the same PR.

## Out of scope

- #1920 (per-node credentials, R2 bucket lock): immutability is what stops a deletion. This change only makes a deletion loud.
- #485 (freshness and size per repository): age stays with each node's Uptime Kuma push monitor.
- #471 (the Storage Box leg itself). Only the per-destination *shape* of the marker lands here, so that #471 does not have to reopen it.
- Any change to `restic check` or to retention.

## Risks / open questions

- **R1 (resolved 2026-09-30: R2 returns 10; see `verification.md`): exit 10 on R2 was unmeasured.**
  - Measured locally on 2026-09-29 (restic 0.18.1, local backend): missing repository → 10, wrong password → 12. The fleet runs 0.19.1 against R2 over S3, where a missing `config` object could surface as a generic 1 (403, NoSuchBucket) instead.
  - Task 1 measures it with a throwaway Job from `cronjob/r2-backup-watcher` (the BACKUP-055 AC3 pattern), pointed at a prefix that does not exist, using the read-only credential. It records the exit codes for a missing repository, a wrong password and a bad credential in `verification.md`.
  - If R2 does not return 10, the design must change before any code is written.
- **R2 (resolved 2026-09-30): `restic cat config` under the watcher's read-only token.** It works with `--no-lock --no-cache`. An invalid credential does not return 10 either: it hangs, which is filed as #1939, not this spec.
- **R3: the node and its marker can be lost together.** A reinstalled node with its repository gone looks like a first ship and initialises. That is accepted on the node side, because a fresh node must be able to start. The watcher's pinned ID is the control for it, and it sits outside the node's failure domain on purpose.
- **R4: a new node pages until its ID is declared.** This is fail-closed by decision (operator, 2026-09-29). Onboarding a node is rare, and the page is the reminder to declare the ID.

## Acceptance criteria

- [x] AC1: the exit codes restic 0.19.1 returns on R2 for a missing repository, a wrong password and a bad credential, and `cat config` working read-only, are measured and recorded in `verification.md` before the ship script changes.
- [ ] AC2: the ship script runs `init` only when `restic snapshots` exits 10 and the destination has no marker. After the first successful ship it writes the repository ID to `/var/lib/node-backup/r2.repository-id`.
- [ ] AC3: with a marker present, a missing repository (exit 10) or a repository whose ID differs from the marker makes the ship exit non-zero without `init`, with a message naming the destination, the expected ID and `make backup-repo-reinit`. Any other `snapshots` failure also exits non-zero without `init`.
- [ ] AC4: tests execute the rendered ship script against a fake restic and cover: first run (init + marker), a transient error (no init, non-zero), the repository gone after prior runs (no init, non-zero), a replaced repository (no init, non-zero), and adoption of an existing repository (no init, marker written).
- [ ] AC5: the watcher marks a node unhealthy, and the fleet line `healthy:0`, when the repository ID read from R2 differs from the declared one or none is declared. Covered by probe tests; the declared IDs come from `backup.r2.repository_ids` in `common.yaml` through `make sync-r2-watcher-targets`.
- [ ] AC6: the four current repository IDs are declared, and after deploy prod shows four `r2_backup_node` lines with `healthy:1`. Markers appear only after a post-deploy ship: `vps` and `rpi3` are forced with `make backup-node NODE=<n> ENV=prod` and their markers hold the declared ID; `beelink` and `rpi4` (on-demand) get theirs at their next power-on, recorded in `verification.md` when it happens.
- [ ] AC7: `make backup-repo-reinit NODE=<node> DEST=r2 ENV=<env>` logs the marker's ID and removes only that marker; it refuses an unknown `DEST`, `NODE=all`, and an unreachable node. The runbook section "Repository missing or replaced" documents the node's behaviour, the watcher's reason strings and the override.

## References

- Bitácora board: #1921, part of epic #1923 (restore-readiness, P0)
- Related ADR: `docs/adr/adr-049-*` (D3, offsite placement)
- Related specs: `specs/archive/BACKUP-044-critical-subset-pipeline`, `specs/archive/BACKUP-055-r2-watcher-probe`
- Runbook: `docs/runbooks/offsite-backup-restore.md`
