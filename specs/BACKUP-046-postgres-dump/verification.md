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

To be filled per PR.
