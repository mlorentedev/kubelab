---
id: lesson-529-restic-copy-reads-both-repositories-with-one-s3-credential
type: lesson
status: active
created: "2026-10-07"
owner: manu
category: storage-backup
tags: [kubelab, storage-backup, restic, r2, credentials]
---

# `restic copy` reads both repositories with one S3 credential, so per-bucket tokens cannot copy between buckets

**Context**: BACKUP-057 moves each node's restic history from `kubelab-backups/<node>` into `kubelab-backup-<node>`. Each bucket has its own least-privilege token: the shared pair writes `kubelab-backups` only, and each node's pair writes its own bucket only.

**Problem**: `restic copy --from-repo` takes a separate password for the source (`RESTIC_FROM_PASSWORD`, `--from-password-file`) but no separate backend credential. Both repositories are opened with the one `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` in the environment (`restic help copy`, 0.18.1: every `--from-*` flag is about the password or the location). Any pair that is correctly scoped to one bucket fails the copy. Isolation is the point of those tokens, so no standing credential can make this copy.

**Solution**: `make backup-migrate` mints a temporary account token for the copy: Object Read on the source bucket, Object Read & Write on the destination, two policies in one token. It is proven by consequence before use (it lists both, and is refused on a third bucket) and revoked in a `finally` once the copy is compared. It is never written to SOPS. Measured on local repositories with restic 0.18.1:
- `RESTIC_FROM_PASSWORD` is honoured;
- each copy's `original` is the source's id, or the source's own `original` when the source was itself a copy;
- a second `copy` duplicates nothing;
- `init --copy-chunker-params` on an existing repository fails with `config file already exists`.

**Rule**: When a tool moves data between two stores, check first whether it takes one credential or two. If it takes one and your credentials are scoped per store, the copy needs a credential made for it: as narrow as both ends together, short-lived, and revoked whatever the outcome. Widening a standing token for a one-off copy leaves it wide.

**Tags**: `#restic` `#r2` `#least-privilege` `#backup-057`
