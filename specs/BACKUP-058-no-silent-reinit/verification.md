---
tags: [spec, verification, templates]
created: "2026-09-29"
---

# Verification - BACKUP-058-no-silent-reinit

## Evidence

### AC1: restic 0.19.1 exit codes on R2 (2026-09-30, staging)

Setup: two throwaway Jobs created from `cronjob/r2-backup-watcher` in staging (`bk058-measure`, `bk058-measure2`), with `ownerReferences` stripped so the CronJob's history limit could not prune them before they were read (lesson-470). Both ran the pinned `restic/restic:0.19.1` image with the watcher's read-only R2 token and the repository password from the existing Secret. Only the container command was replaced. The Secret and the bucket were not touched, and both Jobs were deleted afterwards.

| Case | Command (`--no-lock --no-cache` on every call) | rc | First/last stderr line |
|---|---|---|---|
| missing repository | `snapshots -q` on `<prefix>/backup-058-does-not-exist` | **10** | `Fatal: repository does not exist: unable to open config file: Stat: The specified key does not exist.` |
| wrong password | `snapshots -q` on `beelink`, `RESTIC_PASSWORD` overridden | **12** | `Fatal: wrong password or no key found` |
| invalid credential | `snapshots -q` on `beelink`, `AWS_ACCESS_KEY_ID` overridden | none (hung) | Run 1, no stuck timeout: still running at the Job's 600 s deadline. Run 2, `--stuck-request-timeout 45s` inside `timeout 400`: killed at 400 s (rc 130), no Fatal line. Filed as #1939 (BACKUP-061). |
| `cat config --json`, all four repositories | read-only token | **0** ×4 | ids below |

- **R1 resolved:** R2 returns 10 for a missing repository, the same code as the local backend (measured 2026-09-29, restic 0.18.1). The design holds. An invalid credential never returns 10, so it can never reach `init`, which is the property AC3 needs; its slowness is #1939, not this spec.
- **R2 resolved:** `cat config` works with the read-only token under `--no-lock --no-cache`.
- **What this does and does not prove for the node.** Exit 10 was measured on the watcher's path (read-only token, `--no-lock --no-cache`). The node ships with its write credential and takes locks. restic finds a missing repository when it reads `config`, before any lock, so 10 should hold there too. No live node will exercise that branch, though, until a genuinely new node's first ship: the four existing nodes all take the adoption branch (exit 0, no marker). If the node ever got a different code, the result would be loud (no `init`, non-zero exit), so the design does not depend on it.

Repository IDs read on 2026-09-30 (not secrets; PR2 declares them in `backup.r2.repository_ids`):

| node | repository | id |
|---|---|---|
| beelink | `beelink` | `69e70ca8307994ac6076171f9dd7ce7b6681de24ad7c941b5be76b29a51133fa` |
| rpi3 | `rpi3` | `5ccc440d50e7b601cad0d292d366a32347a63998eca91fb78d910c4081e6641d` |
| rpi4 | `rpi4` | `a35c05eb848b35e6e8073d6d9df4feb16c8617caa46edb6ade46fe2c34cf9177` |
| vps | `kubelab-vps` | `2e9148a2db7f0881caba395c2d8f1308d9ef71f48cc8c1acfb950d40c9878409` |

This hand-built Job was a one-off: the only way to measure restic's exit codes against R2 was to call restic there directly. After PR2 the watcher prints each `repository_id` on every run, so reading the IDs again never needs a Job like this.

### AC2-AC4: the ship script (PR1, #1938)

`tests/test_node_backup_ship_script.py` renders `node-backup-ship.sh.j2` with every path under `tmp_path` and runs it under bash against a fake restic that logs each subcommand. The eight cases, all green:

| Case | `snapshots` rc | marker before | Asserted |
|---|---|---|---|
| first ship | 10 | none | `init` once, exit 0, marker = the new id |
| adoption | 0 | none | no `init`, exit 0, marker = the existing id |
| matching | 0 | same id | no `init`, `backup` runs, marker unchanged |
| transient | 1 | none | no `init`, no `backup`, non-zero, no marker |
| gone after prior ships | 10 | present | no `init`, no `backup`, non-zero, stderr names `r2`, the id and `make backup-repo-reinit` |
| replaced | 0, other id | present | no `init`, no `backup`, non-zero, stderr names both ids and the override |
| retention fails on a first ship | 10, then `forget` 1 | none | non-zero, marker = the new id, and a following exit 10 is refused (review on #1938) |
| no temp file left | 0 | none | only the marker remains in the directory (`mktemp`, review on #1938) |

`tests/test_node_backup_role.py::test_init_is_gated_on_restic_exit_code_10_only` asserts on the rendered template: `init` appears only inside the `10)` branch.

Mutation test, 2026-09-30, from a committed clean tree, restored with `git checkout HEAD --` after each run:

| Mutation | Red tests |
|---|---|
| `init` on any `snapshots` failure (the old behaviour) | 2 |
| no comparison against the recorded id | 1 |
| marker never written | 2 |
| `init` despite a recorded id | 1 |

- [x] AC2 -> first ship and adoption cases, plus the render assertion
- [x] AC3 -> the gone, replaced and transient cases
- [x] AC4 -> the six cases above

### AC7: the override (PR1)

`tests/test_backup_repo_reinit.py` (6 tests) pins these properties:

- the marker path comes from the role's own defaults;
- there is no `ignore_unreachable`;
- `DEST` is asserted against a declared map, and one host is asserted, both before removal;
- the id is read, then journaled with `logger`, then the file is removed, in that order;
- the recipe refuses an empty `NODE` or `DEST`, `NODE=all` and a non-fleet `ENV`, generates the inventory first, and keeps `$(_CHECK)`.

Dry run against prod, 2026-09-30, `CHECK=1`:

| Invocation | rc | Result |
|---|---|---|
| `NODE=rpi3 DEST=r2` | 0 | `rpi3/r2: no repository is recorded; nothing to remove` (the new script is not deployed yet) |
| `NODE=rpi3 DEST=bogus` | 2 | `DEST=bogus is not a backup destination. Known: r2.` |
| `NODE=vps,rpi3 DEST=r2` | 2 | `backup-repo-reinit acts on exactly one node, and this run matched 2: kubelab-vps, rpi3.` |
| `NODE=all DEST=r2` | 2 | `backup-repo-reinit takes exactly one node, never NODE=all` |
| `NODE=rpi3` (no `DEST`) | 2 | `Usage: ...` |
| no `ENV` (defaults to `dev`) | 2 | `backup-repo-reinit needs ENV=staging or ENV=prod, got 'dev'` |

An unreachable node is covered statically (no `ignore_unreachable`), not by a live run. The runbook section is in PR1. The watcher's reason strings join it in PR2.

### AC5: the watcher pins the id (PR2)

`tests/test_r2_backup_watcher_probe.py`, under `sh` and `busybox sh`: `repository replaced` (`cat config` reports another id) and `repository id not declared` (`-` in the targets) each make the node `healthy:0` with that `reason`, the fleet `healthy:0`, and leave the neighbour healthy. The healthy fleet prints each node's `repository_id`. The fake restic parses every argument the way `restic_read` emits them (`-r <repo> --no-lock --no-cache cat config --json`), and `test_the_probe_never_takes_a_lock` still passes with the new call.

`tests/test_r2_watcher_targets.py`: every node in `backup.sources` has a 64-hex id in `backup.r2.repository_ids`, the render carries it as the third column, an undeclared node renders `-` with its sources unshifted, and the committed `targets.txt` matches the SSOT.

Mutation test, 2026-09-30, from a committed clean tree:

| Mutation of `probe.sh` | Red tests |
|---|---|
| no comparison with the declared id | 2 |
| `-` accepted as declared | 2 |
| identity check skipped | 6 |
| `repository_id` not printed | 4 |

Live, 2026-09-30, staging: the branch was deployed with `make deploy-k8s ENV=staging` (ADR-037 flow), then one Job was run from `cronjob/r2-backup-watcher` (the runbook's manual re-check), with the read-only token and the `r2-backup-watcher-probe-6t7m555bt7` ConfigMap:

```
{"metric":"r2_backup_node",...,"node":"beelink",...,"repository_id":"69e70ca8...133fa","healthy":1,"reason":""}
{"metric":"r2_backup_node",...,"node":"rpi3",...,"repository_id":"5ccc440d...e6641d","healthy":1,"reason":""}
{"metric":"r2_backup_node",...,"node":"rpi4",...,"repository_id":"a35c05eb...cf9177","healthy":1,"reason":""}
{"metric":"r2_backup_node",...,"node":"vps",...,"repository_id":"2e9148a2...878409","healthy":1,"reason":""}
{"metric":"r2_backup_health","namespace":"kubelab","nodes":4,"unhealthy":0,"healthy":1,"error":""}
```

Every id matches its declaration, and `cat config` works under the read-only token in the pod as it did in the AC1 Job. The Job was deleted afterwards.

### AC6: prod deploy and markers (PR1 on prod, 2026-09-30)

The node role from #1938 (`84d37387`), deployed from master:

| Step | Result |
|---|---|
| `make backup ENV=prod` | rc 0 |
| same, re-run | rc 0, `changed=0` on beelink, kubelab-vps, rpi3, rpi4 |
| `make backup-node NODE=all ENV=prod` | `ship complete` + coverage heartbeat on all four backup nodes; rc 2 from the four nodes without the role, filed as #1943 (BACKUP-062) |

All four nodes were up, so `beelink` and `rpi4` got their markers in the same run instead of at a later power-on. Each marker read through the override's dry run (`make backup-repo-reinit NODE=<n> DEST=r2 ENV=prod CHECK=1`, which slurps the file and removes nothing under `--check`):

| Node | Recorded id | Declared in `backup.r2.repository_ids` |
|---|---|---|
| beelink | `69e70ca8...133fa` | match |
| kubelab-vps | `2e9148a2...878409` | match |
| rpi3 | `5ccc440d...e6641d` | match |
| rpi4 | `a35c05eb...cf9177` | match |

Prod watcher, after #1942 merged (`9c26f522`) and Argo CD synced (2026-09-30, one run started from the CronJob at 07:32Z instead of waiting for the 12:00Z schedule; see the follow-up below):

- `toolkit obs logs -e prod` over Loki: four `r2_backup_node` lines, each `healthy:1` with an empty reason and the declared `repository_id`, and `r2_backup_health` `{"nodes":4,"unhealthy":0,"healthy":1}`.
- `make backup-coverage ENV=prod`: all four nodes covered, newest snapshots 06:23Z-07:26Z.
- `make alerts`: no firing or pending alerts, so `obs015-r2-backup-health` is Normal.


- [x] AC5 -> the probe and targets tests, the mutations above, and the live run
- [x] AC6 -> role deployed, all four markers hold the declared id, and the prod watcher reports four healthy nodes
- [x] AC7 -> the override and the runbook (PR1); the watcher reason strings in the runbook's alert table (PR2)

## Test status

- Test suite: `<command> -> <output / coverage %>`
- Manual smoke test: what was exercised, what was observed
- No regressions in existing test suite: yes / no (if no, document)

## Decisions made during implementation

Brief log of non-obvious trade-offs or course corrections taken during the work. Routine choices belong in commit messages, not here.

-
-

## Promotion candidates

Answer each line `yes: <path>`, naming the file you promoted, or `no: <reason>`. `dotf spec archive` refuses a line left unanswered, a `no` without a reason, and a `yes` whose file does not exist; a `00_meta/` path is looked up in the vault.

- [ ] Lesson for the repo's `docs/lessons/`? <yes: path / no: reason>
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? <yes: path / no: reason>
- [ ] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. <yes: path / no: reason>

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/BACKUP-058-no-silent-reinit/` -> `specs/archive/BACKUP-058-no-silent-reinit/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
