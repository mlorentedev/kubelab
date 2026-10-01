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

All 34 tables match live, empty ones included. Afterwards `docker ps -a --filter name=pgdrill` is empty and no `pgdrill-*` temp dir remains.

### Coverage (AC4, AC6)

`make backup-coverage ENV=prod` at 08:45Z: all four nodes covered (vps newest 08:40Z), and "all 8 live claims on 'vps' have a backup ruling".
