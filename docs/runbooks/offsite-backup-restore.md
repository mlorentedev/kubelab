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
- **ADR-049 D3** — storage doctrine; **ADR-061:96** — why in-cluster MinIO was
  never an offsite copy
