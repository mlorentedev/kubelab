---
id: forge-console-operations
type: runbook
status: active
created: "2026-11-06"
updated: "2026-11-06"
owner: manu
---

# Forge console operations (CONSOLE-004)

> Rebuild the forge read model, restore it from backup, and rotate the
> credentials the console's API holds. Covers CONSOLE-004 AC7.

The console reads three tables in the API's Postgres tenant
(`apps/api/migrations/20261102000000_forge_read_model.sql`):

| Table | What it holds | Rebuildable from the forges |
|---|---|---|
| `forge_source` | per source: `as_of` (last successful read), reachability | yes |
| `forge_item` | the open and closed issues and pull requests read | yes |
| `forge_event` | webhook deliveries, projected or not | no: an unprojected delivery is lost, and the next read covers the change it carried |
| `console_usage` | one row per operator identity and UTC day the console page was opened (ADR-066 A8) | no: not read model, kept only by the nightly `pg_dumpall` of the VPS backup; never truncate it with the forge tables |

Read the A8 gate with `make console-usage ENV=prod`: for each identity, the best window of 14 consecutive UTC days, how many of them have a row, and whether 5 of 14 holds. It fails, rather than reporting no use, when the table cannot be read.

## Rebuild from the forges

The read model is a cache. A source with no `forge_source` row reads as never
read, so the reconciler asks that forge for everything (`since` zero) on its
next cycle, at API start and every `forge.ReconcilePeriod` (10 minutes). Emptied
tables therefore come back by themselves within one cycle, with the same queue:
`TestReadModelRebuildsFromTheForgesAlone` (`apps/api/src/internal/store/forge_rebuild_test.go`)
empties all three tables and compares the queue before and after.

When the tables are gone (a fresh database, a failed restore): do nothing but
wait one cycle, then open `https://console.kubelab.live/console/` and check each
source shows reachable with a recent read time.

There is no command that empties the tables on purpose, and none is needed for
the cases above. Never empty them by hand on a live cluster: that is a manual
change to prod data.

## Restore from backup

The tables live in the prod Postgres, which `pg_dumpall` captures with every
other tenant (`docs/runbooks/offsite-backup-restore.md`, section Postgres;
drill with `make backup-drill-postgres ENV=prod`). Restore the whole dump as that
runbook says; there is no per-table restore.

After a restore the console may be older than the forges: `as_of` is the dump's,
so the next cycle reads only what changed since then. Deliveries received after
the dump and not in it are lost, and that same read covers them.

If the restore is not worth it for the console alone, rebuilding (above) gives
the same queue without it.

## Which repositories are read

`infra.forge.sources` names Gitea repositories one by one and GitHub as
`github:mlorentedev/*`: every repository of the personal account, listed each
reconcile cycle (`GET /installation/repositories`, no forks, no archived). A
repository created on GitHub is read from the next cycle, within
`ReconcilePeriod` (10 minutes), with no change to the declaration.

That holds only while the `kubelab-console` App is installed with
**All repositories**: with "Only select repositories" the listing returns those
alone and new repositories never appear. Check it at
GitHub > Settings > Applications > Installed GitHub Apps > kubelab-console >
Repository access.

A listing that fails keeps the last set it had; at a pod start, the set is
seeded from `forge_source`, so the console still shows what it read before. A
seed that fails at start (`forge view: seed from the store:` in the log) is asked
again on every reconcile cycle while a wildcard has no listing, and logged as
`forge reconcile: seed from the store:` if it fails again (#3247). With
nothing listed and nothing in the store (a first deploy, or the App without
access), the console shows the wildcard itself (`github:mlorentedev/*`) as
unreachable and never read, not an empty GitHub. A
failed listing appears in the API's log as `forge reconcile: listing:`. If it
keeps failing (a revoked key), the reads fail on the same credential: every
GitHub source shows unreachable in the console and its `as_of` stops moving. The
Grafana alert on that bound is still to build (AC6 in the spec), so until then the
console's reachability column is the signal.

## Rotate the credentials

Each value's `rotate_note` in `SECRET_CATALOG` (`toolkit/features/secrets_manager.py`)
is the procedure; this table only says which ones the console depends on.
`make apply-secrets ENV=prod` restarts the API whenever its Secret changes (#1804).

| Key | What it is | Expiry |
|---|---|---|
| `apps.services.core.github_app.private_key` (common) | signs the `kubelab-console` App's installation tokens | none (GitHub App keys do not expire) |
| `apps.services.core.gitea.issue_reader_token` (prod, staging) | reads Gitea issues and pull requests; a token per env, `kubelab-issue-reader` and `kubelab-issue-reader-staging` | none (Gitea tokens carry no expiry) |
| `apps.platform.api.forge_github_webhook_secret` (prod) | GitHub signs deliveries with it | none (random, ours) |
| `apps.platform.api.forge_gitea_webhook_secret` (prod) | Gitea signs deliveries with it | none (random, ours) |

After rotating `forge_github_webhook_secret`, send it to the App's hook:
`make forge-github-hook APPLY=1 SECRET=1`. GitHub cannot show the secret it
holds, so the proof is a delivery: the App's Advanced tab lists each delivery's
status, and a 401 there means the API and GitHub disagree.

Gitea has no webhook to the API yet (the registration is open work on #2570),
so `forge_gitea_webhook_secret` is held by the API alone and rotates with
`apply-secrets` only. Once the webhook is declared, add its delivery step here.

Staging reads the same Gitea as prod, with its own token (#3267), so a Gitea
read is exercised there first. Both tokens are minted by the Beelink's Gitea and
rotated through it, so the rotation always runs with `ENV=prod`:
`make gitea-rotate-token TOKEN=issue_reader_staging ENV=prod APPLY=1` revokes
staging's token and clears the key in `staging.enc.yaml`, then
`make provision NODE=bee ENV=prod TAGS=gitea` re-mints it and
`make apply-secrets ENV=staging` delivers it. Staging reaches Gitea through the
`gitea` Service in `overlays/staging/gitea.yaml`, which has no route: the forge
keeps one public name.

The installation tokens the API mints from the App key last one hour and are
renewed by the API; nothing to rotate.

## Read the events

The API writes one JSON line per forge event, with a stable `event` field, next
to its text log (#3342). Query them in Grafana's Loki datasource:

| Event | Written | LogQL |
|---|---|---|
| `forge_source_freshness` | per source, after each read attempt: `source`, `reachable`, `as_of`, `age_seconds` (no `as_of` for a source never read), `error` | `{namespace="kubelab", container="api"} \| json \| event="forge_source_freshness" \| reachable="false"` |
| `forge_reconcile_cycle` | per pass: `scope` (`full`, or `retry` for the failed sources alone), `sources`, `failed`, `duration_ms` | `{namespace="kubelab", container="api"} \| json \| event="forge_reconcile_cycle" \| line_format "{{.scope}} {{.duration_ms}}ms {{.failed}}/{{.sources}}"` |
| `forge_webhook_failure` | per refused or unprojected delivery: `forge`, `reason` (`signature`, `sources`, `store`, `unreadable`, `projection`), `delivery`, `status`, `error` | `sum by (reason) (count_over_time({namespace="kubelab", container="api"} \| json \| event="forge_webhook_failure" [1h]))` |

A `signature` failure carries no `delivery`: the caller was not authenticated and
chose every header. The oldest source, for an alert on staleness:
`max by (source) (max_over_time({namespace="kubelab", container="api"} | json | event="forge_source_freshness" | unwrap age_seconds [20m]))`.

## Verify

```bash
make secrets-audit             # each key above present for prod
```

Then open the console and check every declared source reads reachable.
