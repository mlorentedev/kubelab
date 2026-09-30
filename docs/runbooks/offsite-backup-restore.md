---
id: "kubelab-runbook-offsite-backup-restore"
type: runbook
status: active
tags: [runbook, kubelab, backup, restore, restic, r2, disaster-recovery, sops]
created: "2026-08-16"
last_tested: "2026-08-16"
owner: manu
---
# Offsite backups — what exists, how to restore, and how to recover when nothing else is left

> The operational reference for the critical-subset backup pipeline (BACKUP-044,
> #1056; doctrine in ADR-049 D3). It lives here rather than in the spec on
> purpose: a recovery procedure has to be findable on the worst day of the year,
> not archived under `specs/archive/` months after anyone last read it.

## What exists

| Piece | Where |
|---|---|
| Destination | Cloudflare R2, bucket `kubelab-backups` |
| Non-secret config | `backup.r2` in `infra/config/values/common.yaml` |
| S3 credentials | SOPS `backup.r2.access_key_id` / `backup.r2.secret_access_key` |
| Repository password | SOPS `backup.restic_password` |
| **Offsite escrow** | **A Bitwarden Secure Note holding all of the above** |
| Repository layout | One restic repository per node: `<bucket>/<node>` |

**One repository per node** so a compromised node cannot rewrite another node's
history, and so a restore only needs the material for the node being restored.

restic encrypts **client-side**. Cloudflare stores ciphertext and nothing else —
not the data, not the filenames, not the source directory structure. Nobody at
Cloudflare can help you recover anything. The repository password is the only key
that exists.

## Before you trust any of it

```bash
make backup-verify-destination ENV=prod   # the bucket works
make backup-verify-restic ENV=prod        # restic works in the bucket
```

These are two different claims and the second is the one backups depend on. Both
are safe against the live destination — they write a throwaway object under
`_smoketest/` and remove it.

## Is everything actually backed up?

```bash
make backup-coverage ENV=prod
```

Reads the newest snapshot for every node in `backup.sources` **from R2**, not
from the nodes. That is the point rather than an implementation detail: every
other control here runs on the node it checks, so it shares that node's fate.
This one answers with the homelab powered off, which is exactly when half the
fleet cannot answer for itself.

```
[SUCCESS] beelink    covered — newest 2026-08-22 03:25Z (0.3h ago), 1 path(s)
[SUCCESS] rpi3       covered — newest 2026-08-22 02:59Z (0.7h ago), 1 path(s)
[SUCCESS] rpi4       covered — newest 2026-08-22 03:24Z (0.3h ago), 1 path(s)
[SUCCESS] vps        covered — newest 2026-08-22 01:00Z (0.7h ago), 1 path(s)
```

Non-zero exit when any declared node has no repository or no snapshot. It prints
the age and does **not** judge it — an on-demand node is legitimately hours or
days stale, and that judgement belongs to the coverage monitor in Uptime Kuma
(AC9), which knows the node's class. Two controls, one opinion each.

## R2 backup alert

`obs015-r2-backup-health` reads the in-cluster watcher (BACKUP-055): a CronJob in
each cluster that, every 6h, asks R2 the same question `backup-coverage` asks,
with a **read-only** token. For every node in `backup.sources` it checks that the
repository opens, holds a snapshot, contains every declared source under the
staging dir, and contains the capture sentinel (`.capture-complete`), which the
node writes last and refuses to ship without. It does **not** judge age; the
Uptime Kuma coverage monitor owns that.

The rule fires in two cases, and the first step tells them apart:

```bash
toolkit obs logs --env prod -q '{namespace="kubelab"} |= "r2_backup_"' --since 24h
```

- **No lines at all**: the watcher is not running, so coverage is *unknown*.
  Check `kubectl get cronjob,jobs -n kubelab | grep r2-backup-watcher`: a Job that
  never started (image pull, missing `r2-backup-watcher-secrets`) or a CronJob
  that was never deployed.
- **Lines**: one `r2_backup_node` per node, then one `r2_backup_health` for the
  fleet. The fleet line is healthy only if every node is. Find the node with
  `"healthy":0` and read its `reason`:

| `reason` | Meaning | First move |
|---|---|---|
| `unreadable: ... AccessDenied` / `403` | The read-only token was revoked or expired | Rotate it (below) |
| `unreadable: ... wrong password` | `backup.restic_password` in the cluster Secret differs from the repository's | `make apply-secrets ENV=<env>`; if it persists, see [Rotation](#rotation--the-ordering-matters) |
| `unreadable: ... does not exist` | The node's repository is missing | [Repository missing or replaced](#repository-missing-or-replaced) |
| `no snapshots` | The repository exists and is empty | The node has never shipped: `make backup-node NODE=<node> ENV=prod` |
| `missing sources` (`missing:[...]`) | The newest snapshot lacks a declared service | The capture on that node skipped it; read `node-backup-capture.service` there |
| `no capture sentinel` | A snapshot shipped without the capture finishing | The ship guard regressed; treat the snapshot as incomplete |
| `listing failed: ...` | The snapshot opened but its listing did not | Usually transient; the next run is in 6h |
| `repository id changed` | The repository at the node's path is not the history declared in `backup.r2.repository_ids`: it was deleted and re-created, or replaced. `repository_id` on the line is the id R2 holds now | [Repository missing or replaced](#repository-missing-or-replaced) |
| `repository id not declared` | The node has no entry in `backup.r2.repository_ids` | A new node, or one after `backup-repo-reinit`: declare the `repository_id` from this line in a PR, after checking it is the history you mean to accept |
| `config unreadable: ...` / `repository id unreadable` | `restic cat config` failed after `snapshots` succeeded | Usually transient; if it persists, read the repository with the node's credentials |

A fleet line with `"error":"terminated by signal"` or `"probe stopped before
checking every node"` means the Job hit its deadline. The per-node lines printed
before it are still valid.

A line from one run is one verdict: the Job never retries. To re-check now instead
of waiting for the next run:

```bash
make watcher-run NAME=r2-backup-watcher ENV=prod
```

It prints the Job's log, deletes the Job, and exits non-zero when the probe
reports an unhealthy node. Do not use `kubectl create job --from=cronjob/...`:
that Job is owned by the CronJob, whose controller can prune a failed one,
log included, before you read it.

### Rotating the read-only token

The watcher's token is `kubelab-r2-watcher`. It is separate from the nodes' write
token on purpose: it can list and read objects in `kubelab-backups` and nothing
else, so a leak from the cluster cannot delete or rewrite a backup.

1. Cloudflare dashboard → **R2 Object Storage** → **Manage API tokens** (top
   right of the R2 overview) → **Create Account API token**.
2. **Token name**: `kubelab-r2-watcher`.
3. **Permissions**: **Object Read only**.
4. **Specify bucket(s)**: **Apply to specific buckets only** → `kubelab-backups`.
5. **TTL**: Forever. **Client IP Address Filtering**: leave empty (the cluster's
   egress address is not stable).
6. **Create API Token**. The page shows the **Access Key ID** and the **Secret
   Access Key** once; keep the tab open for the next step.
7. Store both halves, each from stdin so neither reaches shell history:

   ```bash
   toolkit secrets set backup.r2.readonly_access_key_id --env common --stdin
   toolkit secrets set backup.r2.readonly_secret_access_key --env common --stdin
   ```

8. Push them to both clusters and re-check:

   ```bash
   make apply-secrets ENV=staging
   make apply-secrets ENV=prod
   ```

   Then run the manual Job above in each. Four `"healthy":1` node lines and a
   fleet `"healthy":1` mean the new token works.
9. Only then delete the old token in the dashboard (same **Manage API tokens**
   page → the old row → **Delete**).

In the dashboard's own terms, this is the account token scope
"Workers R2 Storage Bucket Item Read" on `kubelab-backups`.

## Repository missing or replaced

A node never re-creates a repository it has shipped to (BACKUP-058). The first
time a ship completes, the node records the restic repository id in
`/var/lib/node-backup/r2.repository-id`. That id is new for every `restic init`
and never changes otherwise. From then on, `node-backup-ship.service` **fails**
with one of these messages instead of healing:

- `the r2 repository this node has shipped to (<id>) no longer exists`: the
  repository is gone. restic answered exit 10.
- `the r2 repository was replaced: this node has shipped to <old>, the
  repository there now is <new>`: something else is at the node's path.

The failure is the point. Before this change, both cases came back as a fresh
repository with one snapshot, the watcher called it healthy, and every earlier
restore point was lost without a page (lesson-485).

**1. Find out what happened before touching anything.** A missing repository
means something with write access to `kubelab-backups` deleted objects:

```bash
make backup-coverage ENV=prod    # which nodes are affected, and each one's newest snapshot
```

The message itself arrives through `OnFailure=kubelab-notify@`, which quotes the
unit's journal tail. Node journals do not reach Loki, so the notification and the
node's own journal (`node-backup-ship.service`) are the record.

Check the R2 bucket's lifecycle rules and recent API tokens in the Cloudflare
dashboard. If a replaced repository appears, find out who initialised it and
whether it holds anything you need, and read it before anything writes to it.

**2. If the history is recoverable, restore it; do not reinit.** Point the
node back at the original repository (a mistaken `backup.r2` path, or objects
you can restore from elsewhere). The next ship matches the recorded id and
carries on.

**3. If starting over is the decision,** remove the record on that one node:

```bash
make backup-repo-reinit NODE=rpi3 DEST=r2 ENV=prod CHECK=1   # shows the id it would forget
make backup-repo-reinit NODE=rpi3 DEST=r2 ENV=prod
make backup-node NODE=rpi3 ENV=prod                          # initialises and records a new id
```

The target writes the forgotten id to the node's journal (`logger` tag
`node-backup`) before it removes the file, so the old history stays traceable
after the marker is gone. It acts on exactly one node, refuses `NODE=all`, a
host pattern that matches more than one node, and an unknown `DEST`, and fails
on an unreachable node rather than skipping it. If it fails partway (the id is
journaled but the node dropped before the file was removed), run it again: it
reads the same marker, journals it again and removes it. Never delete the file
by hand; the journal line is the only record that outlives it.

**4. Declare the new id** in `backup.r2.repository_ids` in `common.yaml` through
a PR, then `make sync-r2-watcher-targets`. Take the id from the watcher's
`r2_backup_node` line (`repository_id`) or from the node's marker. Until that
lands, the watcher reports the node `repository id changed` on purpose: accepting
a new history is a reviewed change, not a side effect of a ship.

## Backing up on demand

The timers cover the schedule. This is for the moment before you do something
risky, when the last snapshot is up to four hours old:

```bash
make backup-node NODE=vps ENV=prod        # one node
make backup-node NODE=all ENV=prod        # the whole fleet
make backup-node NODE=rpi3 ENV=prod CHECK=1   # rehearse, change nothing
```

**`make backup` and `make backup-node` are different commands.** The first
DEPLOYS the pipeline — roles, units, timers, credentials. The second makes a
backup happen now. Reaching for `make backup` to get a snapshot re-runs a
deployment against every node, which is not what you wanted and is not idempotent
in the way you were assuming.

It starts `node-backup-ship.service`, which pulls capture in via `Wants=` and
orders it first — the same path the timer takes, so it also posts the coverage
heartbeat. That is how you make a heartbeat arrive without waiting for a window:

```
ship complete: s3:.../kubelab-backups/rpi3
coverage heartbeat posted
```

An on-demand node that is powered off is skipped, not failed. Measured on the
always-on pair, 2026-08-22: rpi3 in ~10s, VPS in ~2s, both with the heartbeat
landing in Uptime Kuma.

## Restoring — normal case

You have the repo checked out and the SOPS age key works.

```bash
# 1. Load credentials into this shell only.
export AWS_ACCESS_KEY_ID=$(make -s secrets-show KEY=backup.r2.access_key_id SECRETS_ENV=common)
export AWS_SECRET_ACCESS_KEY=$(make -s secrets-show KEY=backup.r2.secret_access_key SECRETS_ENV=common)
export RESTIC_PASSWORD=$(make -s secrets-show KEY=backup.restic_password SECRETS_ENV=common)
export AWS_DEFAULT_REGION=auto

# 2. Point at the node's repository (endpoint from backup.r2).
REPO="s3:https://<account_id>.r2.cloudflarestorage.com/kubelab-backups/<node>"

# 3. See what you have BEFORE restoring anything.
restic -r "$REPO" snapshots

# 4. Restore into a scratch directory — never over the live path.
restic -r "$REPO" restore <snapshot-id> --target /tmp/restore-check
```

**Restore to a scratch location and inspect, then move.** Restoring straight over
a live data directory risks the thing you are trying to protect, and if the
snapshot turns out to be the wrong one you have destroyed the evidence.

For SQLite consumers (Headscale, Gitea, Uptime Kuma, Pi-hole FTL), verify the
restored file before putting it in place:

```bash
sqlite3 /tmp/restore-check/path/to/db 'PRAGMA integrity_check;'
```

## Restoring — the disaster case

**This is the scenario the escrow exists for.** The laptop and the USB stick are
both gone, so the SOPS age key is gone, so `secrets-show` cannot decrypt
anything. The repository is intact and, without the escrow, permanently
unreadable.

1. Log in to Bitwarden from any machine with the master password.
2. Open the Secure Note holding the R2 credentials and `restic_password`.
3. Export them by hand into the environment as above.
4. Install restic (`aarch64` / any platform — it is a single static binary).
5. Restore as in the normal case.

You need nothing from this repository to do that: no checkout, no toolkit, no
`bw serve`, no age key. That independence is the entire design and is why the
escrow is a plain Bitwarden item rather than a registry entry in the dotfiles
secret tooling — that tooling is age-backed today, which is the trust root the
disaster just destroyed.

**If the escrow is missing or stale, there is no recovery.** Check it after every
credential rotation.

## Rotation — the ordering matters

**`restic key add` runs BEFORE the password changes, always.** restic derives the
key that unlocks an internal master key, so adding a second password is cheap —
but replacing the stored value first locks you out of every snapshot already
taken, permanently.

```bash
# 1. Add the new password to EVERY repository, using the current one.
restic -r "$REPO" key add

# 2. Only then update SOPS.
toolkit secrets set backup.restic_password --env common --stdin

# 3. Update the Bitwarden escrow in the same sitting, or recovery
#    silently regresses to the old password while operation uses the new one.
```

For the R2 credentials: issue the new Account API token first and keep the old
one valid until every node has the new one. A node still holding the revoked
credential stops backing up and says nothing.

## Cost and quota

R2's free tier is 10 GB-month of Standard storage, 1M Class A operations and 10M
Class B. **Overage is billed, not blocked** — there is no hard stop, and the
pricing page does not promise a notification, so configure one in Cloudflare
Notifications rather than assuming it.

Measured, 2026-08-16:

| Dimension | Projected use | Free tier |
|---|---|---|
| Storage | ~21 MB of source across all nodes | 10 GB |
| Class A ops | ~63,000/month | 1,000,000 |
| Class B ops | negligible | 10,000,000 |

Class A per operation: `backup` 110, `check` 80, `snapshots` 60. The projection
assumes backup every 4h on always-on nodes and `check` weekly.

Measured again 2026-09-30, as stored bytes rather than source: **187 MB** across
the four repositories (beelink 61, rpi3 53, rpi4 66, vps 7 MB), from `restic
stats --mode raw-data` (BACKUP-057).

The R2 watcher now reports that figure on every run: `raw_bytes` on each
`r2_backup_node` line, and the sum on the `r2_backup_health` line. The Grafana
rule `backup057-r2-backup-size` pages when the sum passes 80% of
`backup.r2.free_tier_bytes` (`common.yaml`), **or when no size arrived for a
day**. A `null` size means that node's `stats` failed, and the fleet sum is
`null` whenever any node's is, so an unmeasured fleet is never read as a small
one. When it fires:

1. Read the watcher's lines (`toolkit obs logs --env prod -q
   '{container="r2-backup-watcher"}' --since 24h`). A `null` comes with a
   `size unknown:` line naming the reason, and `stats took Ns` says how close
   the call ran to `STATS_TIMEOUT`.
2. If the size is real, find the node that grew and check its retention ran
   (the first item below) before raising anything.

Two things that would break this, in order of likelihood:

1. **Retention not running.** Without `forget --prune`, storage grows without
   bound. This is also why the R2 token must keep its delete permission — a
   read-write token without delete lets backups look healthy for weeks and fails
   the first time space is reclaimed.
2. **Storage class drift.** The free tier does **not** apply to Infrequent
   Access. The cheaper-looking class is the more expensive one at this volume.

## Gotchas

- **The RPi3's orphaned volume is the bigger one.** Live is `uptime_kuma_data`
  (19M); the frozen orphan is `uptime-kuma_uptime_kuma_data` (26M, dead since
  2026-03-28, #1092). Size, name plausibility and apparent completeness all point
  at the wrong one — only the running container's mount and the mtime discriminate.
- **`make secrets-show` reads `SECRETS_ENV`, not `ENV`.** `ENV=common` is silently
  ignored and you get "key not found".
- **A copy that never left the node is not a backup.** Before this pipeline, one
  node of seven had any backup at all and its copy stayed on the node.
- **A backup that has never been restored is a hypothesis.** Exercise the restore
  on a schedule, not only after an incident.

## References

- `specs/BACKUP-044-critical-subset-pipeline/` — the spec, its measurements and
  the reasoning behind each decision
- **#1090** — the backup epic: sequencing and dispositions
- **#452** — the ratified tiers (Tier 1 RPO < 6h)
- **ADR-049 D3** — storage doctrine; **ADR-061:96** — why the retired in-cluster object
  store was never an offsite copy
