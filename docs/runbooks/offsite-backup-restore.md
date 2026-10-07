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

It then reads every PersistentVolumeClaim on the prod cluster and fails on any
claim that is in neither `backup.sources.<node>` nor `backup.excluded.<node>`
(BACKUP-046). That includes claims nothing in git declares, such as
`kube-system/traefik` from K3s's own chart. A cluster it cannot read is
`CANNOT CHECK` and fails, never a pass:

```
[SUCCESS] claims: all 8 live claims on 'vps' have a backup ruling
```

## R2 backup alert

`obs015-r2-backup-health` reads the in-cluster watcher (BACKUP-055): a CronJob in
each cluster that, every 6h, asks R2 the same question `backup-coverage` asks,
with a **read-only** token. For every node in `backup.sources` it checks that the
repository opens, holds a snapshot, contains every declared source under the
staging dir, and contains the capture sentinel (`.capture-complete`), which the
node writes last and refuses to ship without. It **measures** age and
reachability and judges neither here: the Uptime Kuma coverage monitor judges
always-on nodes, and [On-demand backup stale](#on-demand-backup-stale) judges the
rest. One exception: an always-on node it cannot reach fails the probe, because
that node is never off.

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
| `snapshot time unreadable` | restic answered with a `time` the probe cannot parse, so the node's age is unknown and the freshness rule is blind for it | A restic upgrade changed the format: compare one `restic snapshots --json --latest 1` with `epoch_of` in `probe.sh` |
| `probe cannot reach an always-on node` | A TCP connect from the watcher pod to the node's tailnet address and probe port failed. An always-on node is never off, so the probe is what broke, and every on-demand node would read "off" through it | Check the node is up on the tailnet, then the port in `targets.txt` (22 unless `backup.watcher.reachability_ports` says otherwise), then the Headscale ACL |

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

## On-demand backup stale

`backup032-on-demand-freshness` fires when an **on-demand** node (beelink, rpi4)
answered the watcher on two consecutive probes and its newest snapshot is older
than 3 hours. Such a node ships hourly while it is up, so it is up and not
shipping. Nothing else catches that: the ship's failure hook needs the ship to
run, and the node's Uptime Kuma heartbeat is muted for the `on-demand` tag.

It never fires for a node that is off, which is that node's normal state
(ADR-028). The rule multiplies the age by `reachable`, so an off node is 0.

1. Read the node's lines: `newest_snapshot`, `snapshot_age_seconds`, `reachable`.

   ```bash
   toolkit obs logs --env prod -q '{namespace="kubelab"} |= "r2_backup_node"' --since 24h
   ```

2. On the node, ask systemd why the ship has not run:
   `systemctl list-timers 'node-backup*'` and
   `journalctl -u node-backup-ship.service --since -6h`. A disabled timer, a unit
   that never started and a capture stuck before the ship are the usual three.
3. Ship once by hand and confirm: `make backup-node NODE=<node> ENV=prod`, then
   `make watcher-run NAME=r2-backup-watcher ENV=prod`.

If every node looks fine and the alert still fires, it is the **no data** case:
the watcher stopped (the health rule above is then paging too), or no node in
`targets.txt` is on-demand. Start with [R2 backup alert](#r2-backup-alert).

## R2 backup shrank

`backup032-r2-backup-shrink` fires when a node's repository (`stored_bytes`, every
object under its prefix) is less than half the size it was one probe earlier (operator decision, 2026-10-02).
Data does not halve by itself: a `forget`/`prune` that removed snapshots it should
have kept, or a source that started capturing an empty directory, are the causes
to rule out. Act before the next `forget` removes the older snapshots, which are
the ones that still hold the data.

1. Compare the node's two most recent `r2_backup_node` lines (command above).
2. List the newest snapshots and their sizes from the workstation, as in
   [Restoring — normal case](#restoring--normal-case) step 3, and look at the
   source that shrank: `restic ls latest /opt/node-backup/staging/<source>`.
3. If a source captured nothing, fix the capture on the node and ship again. If
   the repository lost snapshots, see
   [Repository missing or replaced](#repository-missing-or-replaced).

It resolves by itself once the earlier probe leaves its 9 h window, so read it
when it fires. With no data at all (no node reported a size), the watcher
stopped: see [R2 backup alert](#r2-backup-alert).

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

### Postgres

Prod Postgres (the task board's database, among others) is captured by
`pg_dumpall` into `postgres/pg_dumpall.sql` in the VPS repository, never as a
copy of its data directory. **Prove the snapshot before you use it:**

```bash
make backup-drill-postgres ENV=prod
```

It restores the newest dump into a throwaway container on this machine, running
the image live runs. It passes only if the dump ends with pg_dumpall's
completion trailer, every live database and table exists in the restore, and no
table with rows live came back empty. It prints names and counts, never rows
(the dump also holds role password hashes), and removes the container, its data
volume and the file on every exit path, then confirms with docker that the
container and its volume are gone. If they are not, the drill fails even when the
restore was complete, and prints the `docker rm -f -v` to run. Counts lower than
live are expected: the snapshot is up to four hours old.

**Whole cluster lost** (the claim is gone, the Deployment starts on an empty
volume). Load the whole dump into the fresh server:

```bash
D=$(mktemp -d) && chmod 700 "$D"          # private: the dump holds password hashes
restic -r "$REPO" dump latest /opt/node-backup/staging/postgres/pg_dumpall.sql > "$D/dump.sql"
tail -n 3 "$D/dump.sql"                   # must show: -- PostgreSQL database cluster dump complete
kubectl --kubeconfig ~/.kube/kubelab-prod-config -n kubelab exec -i deploy/postgres -c postgres -- \
  sh -c 'psql -U "$POSTGRES_USER" -d postgres -q -o /dev/null' < "$D/dump.sql"
rm -rf "$D"
```

Expect `role ... already exists` for the server's own superuser; nothing else.
Then restart the apps that use it, because they hold pooled connections to the
empty server.

**One database damaged, the rest fine.** Do not load `pg_dumpall` into the live
server: it carries `CREATE DATABASE` for every database and fails on each one
that exists. Restore the whole dump into a scratch container, take that one
database out with `pg_dump -Fc <db>`, and `pg_restore --clean --if-exists -d <db>`
it into live while that app is stopped by a restore window: open it with
`make restore-window APP=<app> ENV=prod` before `pg_restore` and close it with
`END=1` after (see "Taking an app offline for a restore" below). Build the scratch container the way the
drill does (`docker run -d -e POSTGRES_HOST_AUTH_METHOD=trust <live image>`, no
published port) and remove it with `docker rm -f -v`. Without `-v` the restored
database stays on this machine in an anonymous volume, because the image
declares one for its data directory.

### Gitea

The Beelink capture stages Gitea's whole `/data` at `/opt/node-backup/staging/gitea`
in the Beelink repository: the bare repositories, `gitea.db` (copied with
`sqlite3 .backup`), `app.ini` and the SSH host keys. **Prove the snapshot before
you use it:**

```bash
make backup-drill-gitea ENV=prod
```

It restores the newest snapshot into a private temp directory on this machine and
runs `git fsck --full` on every repository. Then it starts the Gitea image pinned
in `common.yaml` on the restored data with `--network none`, so the restored server
cannot reach live services, mirrors or webhooks. It mints a read-only token inside
that container and lists every repository and branch through the API. It passes
only if every repository live lists is restored on disk and in the database, none
that has branches live came back with none, and every restored branch head is a
commit live knows. A branch count different from live is expected: the snapshot
can be hours old. It prints names and counts only (the restore holds `app.ini`
secrets and password hashes), and on every exit path removes the container and
the directory, then confirms with docker that they are gone. Measured 2026-10-01:
5 repositories, 17 s from the start of the restore to a complete check.

**Restoring it for real** (the Beelink lost `/opt/gitea/data`, or it is corrupt).
Use the snapshot the drill just passed, and run this on the Beelink with the
restic environment from "Restoring — normal case" loaded:

```bash
# As root, so restic gives back the owners it recorded (1000:1000, Gitea's `git` user).
# If sudoers does not keep the environment for -E, run these lines in `sudo -s`
# and load the restic environment there.
sudo -E restic -r "$REPO" restore <snapshot-id> \
  --include /opt/node-backup/staging/gitea --target /tmp/gitea-restore
sudo docker compose -f /opt/kubelab/compose.yml stop gitea
sudo mv /opt/gitea/data "/opt/gitea/data.broken-$(date +%F)"
sudo mv /tmp/gitea-restore/opt/node-backup/staging/gitea /opt/gitea/data
stat -c '%u:%g %n' /opt/gitea/data /opt/gitea/data/gitea/gitea.db   # expect 1000:1000
sudo docker compose -f /opt/kubelab/compose.yml start gitea
```

Then check it the way the drill does, against the live server: every repository
listed, and `git fsck` clean on a fresh clone of the one you care most about.
Keep `data.broken-*` until you have. Pushes made after the snapshot are lost on
the server; anyone who still has them in a clone pushes them again.

### Headscale

The VPS capture stages the `headscale_headscale_data` volume at
`/opt/node-backup/staging/headscale` in the VPS repository: `db.sqlite` (copied with
`sqlite3 .backup`), `noise_private.key` and `derp_server_private.key`. The keys are the
server's identity: a node trusts the server by the noise key, so a restore with the
same keys lets every node reconnect without registering again. The ACL policy is not
in the capture; Ansible renders it from git. **Prove the snapshot before you use it:**

```bash
make backup-drill-headscale ENV=prod
```

It reads live first, over SSH to the VPS: the node and user lists, and a SHA-256 of
each live key file (`sudo -n` there). Then it restores the newest snapshot into a
private temp directory on this machine, runs `PRAGMA integrity_check` on the restored
database, and compares the restored keys with live by hash. It starts the Headscale
image pinned in `common.yaml` on the restored data with `--network none` and a
drill-only config, running as you so that everything it writes is yours to delete.
It passes only if every node live had when the snapshot was taken is restored under
the same id with the same machine key, and every user likewise. A node registered
since, or deleted since, is reported and is not a failure. Nodes are matched by id,
because a node that registers again keeps its name and gets a new id. It prints names
and ids only, never a key or a hash, and on every exit path removes the container and
the directory, then confirms that both are gone. Measured 2026-10-01: 12 nodes,
4 users, both keys matching, 2 s from the start of the restore to a server that
answers.

**Restoring it for real** (the volume is lost or the database is corrupt). Use the
snapshot the drill just passed. Run this on the VPS over its public IP, never the
tailnet (the tailnet is what you are restoring), with the restic environment from
"Restoring — normal case" loaded. If the VPS itself is new, run
`make deploy TARGET=vps ENV=prod` first so the volume and the compose file exist.

```bash
# As root, so restic gives back the owners it recorded (0:0, as live).
# If sudoers does not keep the environment for -E, run these lines in `sudo -s`.
sudo -E restic -r "$REPO" restore <snapshot-id> \
  --include /opt/node-backup/staging/headscale --target /tmp/headscale-restore
cd /opt/headscale && sudo docker compose stop headscale
v=$(sudo docker volume inspect -f '{{.Mountpoint}}' headscale_headscale_data)
sudo cp -a "$v" "/root/headscale-data.broken-$(date +%F)"
# Empty it completely: a db.sqlite-wal left from the broken database would be
# replayed onto the restored one when Headscale opens it.
sudo find "$v" -mindepth 1 -delete
sudo cp -a /tmp/headscale-restore/opt/node-backup/staging/headscale/. "$v"/
sudo docker compose start headscale
sudo docker exec headscale headscale nodes list
```

Nodes reconnect on their own within a few minutes. A node registered after the
snapshot is unknown to the restored server and registers again with a pre-auth key.
Keep `/root/headscale-data.broken-*` until every node you need is back online, then
delete it and `/tmp/headscale-restore`: both hold the private keys.

### Authelia and n8n

Both are PVCs on the VPS (`local-path`), captured as single files with `sqlite3
.backup`: Authelia's `db.sqlite3` and n8n's `database.sqlite`, plus the rest of n8n's
data directory, including its `config`. Both keep encrypted data: Authelia's storage
under `apps.services.security.authelia.storage_encryption_key`, n8n's credentials under
`apps.services.automation.n8n.encryption_key`. An intact file that key cannot open is
not a backup. **Prove the snapshot before you use it:**

```bash
make backup-drill-apps ENV=prod
```

For each service it reads live first, from the database file on the VPS with `sudo -n
sqlite3 -readonly` over SSH, never through the app's CLI in its pod: every `n8n` command
starts a second n8n under the pod's memory limit (OPS-033), and answers nothing at the
pod's log level (lesson-500). It restores the newest snapshot into a private temp
directory on this machine, and passes only if:

- `PRAGMA integrity_check` answers `ok`;
- every durable row live had when the snapshot was taken is in the restore, by id:
  Authelia's opaque identifiers (the `sub` each OIDC client knows a user by, which
  must also come back unchanged), preferences, TOTP and WebAuthn registrations; n8n's
  workflows and credentials. Rows created since or deleted since are reported, not
  failed. Sessions, tokens and logs are not compared;
- the image the live Deployment runs opens the restore with the SOPS key, with
  `--network none`, as you. For Authelia, `storage encryption check` prints SUCCESS
  (it exits 0 on FAILURE too, so the drill reads the text) and the server answers
  `/api/health`. For n8n, the server starts (a key that is not the data's aborts it
  with "Mismatching encryption keys", which the drill names) and `export:credentials
  --all --decrypted` writes to `/dev/null` and exits 0.

The key reaches the container only as a `0600` file named by its `*_FILE` variable. The
drill prints table names, row ids and counts, never a row, and removes each container
and its directory on every exit path, then confirms that both are gone. The restored
n8n activates its workflows on start; with no network a schedule can run only against
the scratch database. Measured 2026-10-01 on snapshot `a59acffe`: Authelia 4 opaque
identifiers, schema 23 on both sides, 3 s to a healthy server; n8n 4 workflows and
2 credentials, 18 s. With a random key in place of each SOPS key, both fail and say why.

**Restoring it for real** (the claim's data is lost or corrupt). Use the snapshot the
drill just passed, on the VPS, with the restic environment from "Restoring — normal
case" loaded. The app must not run while its files are replaced, so open a restore
window first and close it once the files are in place (see "Taking an app offline for a
restore" below).

```bash
SVC=n8n                                   # or authelia
DB=database.sqlite                        # authelia: db.sqlite3
OWNER=1000:1000                           # authelia: 0:0 (as live; check with stat)
# The claim's directory on the VPS: resolved, never typed (local-path embeds the claim's UID).
P=$(kubectl --kubeconfig ~/.kube/kubelab-prod-config get pv -o \
  jsonpath='{range .items[?(@.spec.claimRef.namespace=="kubelab")]}{.spec.claimRef.name}{"\t"}{.spec.local.path}{"\n"}{end}' \
  | awk -F'\t' -v c="$SVC-data" '$1==c{print $2}')
sudo -E restic -r "$REPO" restore <snapshot-id> \
  --include "/opt/node-backup/staging/$SVC" --target "/tmp/$SVC-restore"
sqlite3 "/tmp/$SVC-restore/opt/node-backup/staging/$SVC/$DB" 'PRAGMA integrity_check;'
# On the workstation first: make restore-window APP=$SVC ENV=prod
sudo cp -a "$P" "/root/$SVC-data.broken-$(date +%F)"
# Empty it completely: a -wal left from the broken database would be replayed
# onto the restored one when the app opens it.
sudo find "$P" -mindepth 1 -delete
sudo cp -a "/tmp/$SVC-restore/opt/node-backup/staging/$SVC/." "$P"/
sudo chown -R "$OWNER" "$P"/*
```

Bring the app back by closing the window from the workstation,
`make restore-window APP=$SVC ENV=prod END=1`, then check it from outside:
`make test-e2e ENV=prod` and a login.
Keep `/root/<svc>-data.broken-*` until the app is confirmed whole, then delete it and
`/tmp/<svc>-restore`: both hold encrypted secrets, and n8n's `config` holds its key.

### Taking an app offline for a restore

A prod Deployment cannot be stopped by scaling it by hand: Argo CD runs `selfHeal: true`
there and puts the replicas back within seconds, onto data that is half replaced. On
staging a hand scale holds only until master moves (lesson-330). A restore
window pauses the env's auto-sync for the length of the restore (BACKUP-070):

```bash
make restore-window APP=n8n ENV=prod          # open: pause, scale to zero, wait for the pods
# ... replace the data ...
make restore-window APP=n8n ENV=prod END=1    # close: git's sync policy, one sync, wait
```

- **Open** sets `automated.enabled: false` on `kubelab-<env>`, writes a holder
  annotation (`kubelab.live/restore-window`: the app, who, since when), scales the
  Deployment to zero and returns only once no pod runs or mounts its claims. It prints
  the sync policy it replaced.
- **While it is open, that env receives no merges**: Argo CD has no per-resource
  switch, so the whole Application is paused. A second open is refused and names the
  holder, and `make deploy-apps` refuses too, because re-applying git would end the
  pause in the middle of the restore. Close the window as soon as the data is in place.
- **Close** restores the sync policy declared in `infra/k8s/argocd/applications/`
  (never a copy taken at open), removes the annotation, triggers one sync, and exits 0
  only once the Application is Synced/Healthy and the app's replicas are ready. If it
  times out, the window is already closed: read what it saw, then `make check-apps`.
  Closing with no window open says so and exits 0, so it is safe to run twice.

### Running a drill on ace2

The Gitea and Headscale drills can run on ace2 instead of this machine
(BACKUP-071). The evidence then says the backup restores on a host other than
the one the operator works from:

```bash
git push                                       # the run refuses an unpushed commit
make backup-drill-gitea HOST=ace2 ENV=prod
make backup-drill-headscale HOST=ace2 ENV=prod
```

- **The commit, not master.** ace2 keeps its own checkout at
  `~/.local/share/kubelab-drill` (provisioned by `dev_node`, `make provision
  NODE=ace2 ENV=prod TAGS=drill`). Each run fetches it, detaches it at this tree's
  `HEAD` and runs `make worktree-init`. A dirty tree, untracked files included, or
  a commit no `origin/*` branch contains refuses with CANNOT CHECK before anything
  is sent. That check reads this clone's remote-tracking refs, not the forge: if
  `origin/*` is stale, a pushed commit is refused too. `git fetch origin` and rerun. A branch can prove itself on ace2 before it merges.
- **What travels.** This machine opens SOPS and builds one JSON payload: the
  restic repository and environment (R2 keys, restic password), the image, the
  staging directory, and the Gitea admin token for the Gitea drill. It goes on the
  ssh session's stdin, so it is never in argv (`ps`), in an environment
  assignment, or in a file on ace2. ace2 reads it into memory and never prints it,
  and a malformed payload is reported by its error class only.
- **What does not travel.** ace2 has no SOPS age key and never builds the
  config. Headscale's live reads (node and user lists, hashes of the live key
  files) need ssh and `sudo -n` on the VPS, so this machine does them and sends
  the result. ace2 gets no VPS credential and no forwarded agent.
- **Reading a failure.** `could not reach` is ssh (exit 255), `the drill checkout
  could not be prepared` is the fetch, the checkout or `make worktree-init` on
  ace2 (the lines above it say which), and anything else is the drill's own
  verdict, printed by the drill as it would print it locally.

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

Since BACKUP-075 the R2 watcher measures what R2 **stores**, which is what it
bills, by listing objects rather than with `restic stats`. `stats --mode
raw-data` walked every snapshot's tree, so its cost followed the snapshot count:
it passed its 600 s budget on the Beelink on 2026-10-04 and doubled on every
other node in three days, while it counted only referenced blobs, not the
unreferenced packs, index and snapshot files R2 also bills.

The watcher's init container `r2-size` runs `size.sh` in the pinned rclone image
(`backup.watcher.size_image`) and lists each bucket once at its root and each
node's prefix. The probe then reports `stored_bytes`: the node's prefix on each
`r2_backup_node` line, and the sum of the bucket roots on the `r2_backup_health`
line, which includes anything outside a node's prefix. The Grafana rule
`backup057-r2-backup-size` pages when that sum passes 80% of
`backup.r2.free_tier_bytes` (`common.yaml`), **or when no size arrived for a
day**. A `null` means a listing failed, and the fleet is `null` whenever any
bucket is, so an unmeasured fleet is never read as a small one. A listing never
fails the pod: `size.sh` always exits 0, so the health probe still runs. When it
fires:

1. Read the watcher's lines, both containers (`toolkit obs logs --env prod -q
   '{container=~"r2-backup-watcher|r2-size"}' --since 24h`). Loki labels a
   container's logs with that container's name, so the reason a listing failed
   (for example an `AccessDenied`) is in the `r2-size` stream, on a `size
   unknown:` line; the probe's own stream only says the size is unknown. `size
   listing took Ns` says how long each listing ran against `SIZE_TIMEOUT`.
2. If the size is real, find the node that grew and check its retention ran
   (the first item below) before raising anything.

Two things that would break this, in order of likelihood:

1. **Retention not running.** Without `forget --prune`, storage grows without
   bound. This is also why the R2 token must keep its delete permission — a
   read-write token without delete lets backups look healthy for weeks and fails
   the first time space is reclaimed.
2. **Storage class drift.** The free tier does **not** apply to Infrequent
   Access. The cheaper-looking class is the more expensive one at this volume.

## Adding a stateful service

Anything that keeps state on disk gets a backup ruling **in the same PR that
creates it**: a database, a Docker volume, a PVC, a bind mount. There is no
third option, and "not yet" is not one. Prod Postgres went unbacked for five
weeks because its exclusion said "joins this list the day something writes to
it", and nothing watches a sentence (lesson-495).

1. **Pick the tier** from epic #1923. Tier 1 and 2 are backed up; tier 3
   ("rebuilt from git", "re-downloaded from upstream") is excluded.
2. **Backed up:** declare it in `backup.sources.<node>` in `common.yaml` with a
   capture that is consistent for its engine:
   - `sqlite: [files]` for SQLite (online `.backup`, never a file copy);
   - `pg_dumpall: {deployment, container}` with `pvc:` for Postgres;
   - `path:`, `volume:` or `pvc:` alone only for files nothing writes while the capture runs.
3. **Excluded:** declare it in `backup.excluded.<node>` with `reason:` and
   `tier: 3`. A reason that names a condition ("until", "once", "for now") is a
   deferral, so back it up instead. If the database is still empty, backing it
   up costs nothing.
4. `make sync-r2-watcher-targets`, then `make test`. `test_backup_pvc_coverage`
   and `test_backup_volume_coverage` fail on anything left without a ruling.
5. After merge: `make backup ENV=prod`, then `make backup-node NODE=<node> ENV=prod`.
6. **Prove it once:** `make backup-coverage ENV=prod`, then restore it. For
   Postgres that is `make backup-drill-postgres ENV=prod`; for SQLite, the
   `integrity_check` above. Until a restore has been seen, it is a hypothesis.

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
