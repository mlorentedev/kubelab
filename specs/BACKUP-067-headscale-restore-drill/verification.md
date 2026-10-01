---
tags: [spec, verification]
created: "2026-10-01"
---

# Verification - BACKUP-067-headscale-restore-drill

## Evidence

- [x] AC1 -> `test_a_capture_missing_a_file_fails_names_it_and_never_starts_a_server` (3 cases), `test_a_corrupt_database_fails_and_never_starts_a_server`, `test_a_key_that_differs_from_live_fails` (noise, DERP); prod run below.
- [x] AC2 -> `test_the_restored_server_has_no_network_runs_as_the_caller_and_the_pinned_image`, `test_a_node_live_had_at_snapshot_time_must_come_back_unchanged` (missing, machine key), `test_a_node_reregistered_under_the_same_name_is_matched_by_id_not_name`, `test_a_missing_user_fails_and_a_newer_one_is_reported`, `test_a_node_missing_from_the_restore_fails_and_is_named`.
- [x] AC3 -> `test_live_that_cannot_be_read_is_cannot_check` (unreachable, empty, hashes unreadable), `test_no_readable_snapshot_is_cannot_check`.
- [x] AC4 -> `_torn_down` asserted on every failing path; `test_a_complete_restore_that_leaves_its_container_behind_fails`, `test_a_complete_restore_that_leaves_the_keys_on_disk_fails`; prod run left nothing.
- [x] AC5 -> `docs/runbooks/offsite-backup-restore.md` "### Headscale" (drill and real restore); prod transcript below.

### Prod run, 2026-10-01, from the workstation

```text
headscale restore drill — newest capture in R2 into a scratch container (prod)
[INFO] drill: snapshot 46f892f1 taken 2026-10-01T12:04:45.886043275Z
[SUCCESS] drill: restored /opt/node-backup/staging/headscale in 2s
[SUCCESS] drill: db.sqlite integrity_check ok
[SUCCESS] drill: noise key: match
[SUCCESS] drill: DERP key: match
[INFO] ok 12 nodes, 4 users restored
[INFO] drill: RTO 2s from download to a server that answers
[SUCCESS] drill: snapshot 46f892f1 restores Headscale completely
rc=0
```

Afterwards: `docker ps -a --filter name=hsdrill` empty, no `hsdrill-*` directory under the temp dir.

### Mutation check

Each guard was broken in turn on a committed tree, the suite run, and the file restored with `git checkout HEAD --`.

| Mutation | Result |
|---|---|
| every live entry treated as newer than the snapshot | 4 failed |
| a missing node not failed | 3 failed |
| machine key not compared | 1 failed |
| machine-key mismatch logged but `ok` kept | 1 failed |
| missing `created_at` read as "newest" instead of 0 | 1 failed |
| unreadable live hashes accepted | 1 failed |
| empty live list accepted | 2 failed |
| missing capture file accepted | 2 failed |
| `integrity_check` skipped | 1 failed |
| key mismatch accepted | 2 failed |
| failed `docker run` accepted | 1 failed |
| ready deadline never reached | 1 failed |
| `--network none` → `bridge` | 1 failed |
| teardown result ignored (container) | 1 failed |
| teardown result ignored (directory) | 1 failed |
| container removal skipped | 10 failed |

## Test status

- `poetry run pytest -q -p no:cacheprovider --no-cov tests/test_headscale_drill.py` → 25 passed.
- `make test` on `5b092e38`: 3274 passed, 1 failed (`test_the_table_covers_every_site`: the new target was missing from `ENV_TARGETS`), fixed in `bf893de1`; that file then 75 passed.

## Decisions made during implementation

- **The container runs as the invoking user.** The image is distroless, so the Gitea drill's wipe from inside a container is impossible. Running as the caller makes every file Headscale writes removable by `rmtree` on any host. The Unix socket moves into the data directory, because the caller cannot write `/var/run`.
- **Policy mode `database` in the drill config.** The live policy is a file rendered from git and is not in the capture; the drill checks the restore, not the policy.
- **Keys compared by hash over SSH**, not through the public `/key` endpoint, because that endpoint shows only the noise key and the DERP key is identity too.
- **Spike first.** A manual run on prod data (torn down) settled the config before any test was written: v0.28.0 starts with no DERP map and no network.

## Promotion candidates

- [x] Lesson for the repo's `docs/lessons/`? no: the drill found no defect, and the two traps it met (a distroless image cannot wipe its bind mount; a leftover `db.sqlite-wal` would replay onto a restored database) are written where they are used, in the module docstring and the runbook's restore steps.
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? no: it applies the drill pattern of BACKUP-046 and BACKUP-040 to a third source.
- [x] New pattern candidate for `00_meta/patterns/`? no: single project.

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/BACKUP-067-headscale-restore-drill/` -> `specs/archive/BACKUP-067-headscale-restore-drill/`
