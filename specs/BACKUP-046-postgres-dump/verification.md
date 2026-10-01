---
tags: [spec, verification]
created: "2026-10-01"
---

# Verification - BACKUP-046-postgres-dump

## Baseline: the emergency copy (2026-10-01)

Taken before any change, because prod Postgres had no backup:

- `kubectl exec -n kubelab deploy/postgres -c postgres -- sh -c 'pg_dumpall -U "$POSTGRES_USER"'` from the workstation, written with `umask 077` to `~/backups/kubelab-emergency/postgres-prod-20261001T065154Z.sql` (74 KB, 34 `CREATE TABLE`, databases `kubelab` and `vikunja`). The last line is `-- PostgreSQL database cluster dump complete`.
- Restored into a scratch `postgres:16-alpine` with `psql -f`, then compared with live:

| table | restored | live |
|---|---|---|
| users | 2 | 2 |
| projects | 2 | 2 |
| tasks | 7 | 7 |
| labels | 3 | 3 |
| task_comments | 0 | 0 |

The same read showed `pg_dumpall` authenticating over the container's local socket with no password, which the capture relies on.

## Acceptance criteria

### AC1: the VPS snapshot carries a whole dump (2026-10-01)

The role was deployed from `feat/backup-046-postgres-dump` before #1979 merged, so the watcher would never expect a tag nothing produced (PR-Agent finding on #1979):

- `make backup ENV=prod`: `changed=1` on `kubelab-vps` only (`Render capture script`), `failed=0` on beelink, kubelab-vps, rpi3 and rpi4.
- `make backup-node NODE=vps ENV=prod`: `ship complete` to `kubelab-vps`, snapshot `00b263a5` at 2026-10-01T08:40:08Z. Ship refuses a capture without its sentinel, so the snapshot holds every declared source, `postgres` and `crowdsec_db` included.
- The drill below read `/opt/node-backup/staging/postgres/pg_dumpall.sql` from `00b263a5`: 73875 bytes, ending with the completion trailer. The capture skips the claim's data directory for a `pg_dumpall` source (`tests/test_node_backup_capture_postgres.py`).

### AC5: the dump in R2 restores completely (2026-10-01)

`make backup-drill-postgres ENV=prod`, run from `feat/backup-046-drill`:

```
[INFO] drill: vps/postgres
[INFO] drill: snapshot 00b263a5 taken 2026-10-01T08:40:08.30578146Z
[SUCCESS] drill: /opt/node-backup/staging/postgres/pg_dumpall.sql carries its completion trailer (73875 bytes)
[INFO]      vikunja public.tasks: restored 7, live 7
[INFO]      vikunja public.users: restored 2, live 2
[INFO]      vikunja public.projects: restored 2, live 2
[INFO]      vikunja public.task_positions: restored 28, live 28
...
[SUCCESS] drill: snapshot 00b263a5 restores completely (34 tables)
```

All 34 tables match live, empty ones included.

**The first version of this check was wrong.** It read `docker ps -a --filter name=pgdrill` and called the teardown clean. The adversarial review found what that misses: the `postgres` image declares `VOLUME /var/lib/postgresql/data`, and `docker rm -f` without `-v` leaves that anonymous volume behind. Each run had left a full restored copy of prod, role password hashes included, in a dangling volume. Two were found on the workstation (from the emergency restore at 00:54Z and this drill at 02:55Z), identified by `PG_VERSION` in the volume, and removed. The teardown is now `docker rm -f -v`, run unconditionally in the `finally`. Four tests pin it, and each guard was mutated back and went red (`39daab08`).

Rerun at 09:20Z on the same snapshot: `restores completely (34 tables)`, rc 0, and no volume was created. Afterwards, the only dangling volumes holding a `PG_VERSION` are `auth_database` and `authentik_database`, named volumes from an unrelated stack dated 2025-12.

### AC2: a failed or truncated dump fails the capture (2026-10-01)

`tests/test_node_backup_capture_postgres.py` runs the rendered capture script against a fake `kubectl`. `test_a_truncated_dump_fails_the_capture_and_names_the_source` and `test_a_failed_exec_fails_the_capture_and_names_the_source` both exit non-zero, name the source, and leave no sentinel and no `.sql` behind.

### AC3: the static guard (2026-10-01)

`test_every_prod_claim_has_a_backup_ruling` was red on master with five unruled claims and is green after #1979. `test_every_exclusion_is_tier_3_with_a_reason`, mutated against the committed `common.yaml`:

- `beelink.act_runner_data` with `tier: 2`: `beelink.act_runner_data: tier 2, only tier 3 may be excluded`, 1 failed.
- the same entry with `reason:` renamed: `beelink.act_runner_data: no reason`, 1 failed.

### AC4: every live claim has a ruling (2026-10-01)

`make backup-coverage ENV=prod` at 08:45Z: all four nodes covered (vps newest 08:40Z), and "all 8 live claims on 'vps' have a backup ruling".

`tests/test_backup_live_claims.py` pins the other outcomes: an unruled claim fails and is named (`kube-system/traefik`); a missing kubeconfig, an unreadable cluster and an empty answer are each CANNOT CHECK.

### AC6: runbook and lesson

- `docs/runbooks/offsite-backup-restore.md`: "Postgres" under restoring (drill, whole-cluster loss, one damaged database) and "Adding a stateful service".
- `docs/lessons/storage-backup/lesson-495-a-backup-exclusion-with-a-trigger-is-a-promise-nobody-keeps.md` (merged in #1979).
