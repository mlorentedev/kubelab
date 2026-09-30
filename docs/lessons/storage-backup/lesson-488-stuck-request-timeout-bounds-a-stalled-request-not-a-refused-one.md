---
id: lesson-488-stuck-request-timeout-bounds-a-stalled-request-not-a-refused-one
type: lesson
status: active
created: "2026-09-30"
owner: manu
category: storage-backup
tags: [kubelab, storage-backup, restic, r2, backup-061]
---

# restic's `--stuck-request-timeout` bounds a stalled request, not a refused one, and R2's credential refusals are retried for 15 minutes

**Context**: The node backup ship script passes `--stuck-request-timeout 45s` to restic. Its comment said this lets restic "reach its own error path and SAY what went wrong" on an invalid credential, well inside the unit's `TimeoutStartSec=600`. BACKUP-058 found otherwise and filed #1939.

**Problem**: measured on 2026-09-30 from a workstation with `restic/restic:0.19.1` against the fleet's R2 bucket. The key was invented, so no real credential was involved:

```text
AWS_ACCESS_KEY_ID=<32 hex, not a key>  -> R2: HTTP 401 <Code>Unauthorized</Code>
  Stat(<config/>) returned error, retrying after 875ms: Stat: Unauthorized
  ... retrying after 40s ... retrying after 1m4s ...   (killed at 150 s, rc 124)
AWS_ACCESS_KEY_ID=invalid              -> R2: HTTP 400 <Code>InvalidArgument</Code>
  Stat: Credential access key has length 7, should be 32   (same retry loop)
```

The cause is in restic v0.19.1's source. `internal/backend/s3/s3.go` `IsPermanentError` treats only a missing object, `InvalidRange` and `AccessDenied` as permanent. AWS answers a bad key with 403 `InvalidAccessKeyId`/`AccessDenied`, but R2 answers `Unauthorized` or `InvalidArgument`, so restic retries it. `internal/global/global.go` gives the retry backend `15*time.Minute`, which is longer than the unit lives. `--stuck-request-timeout` never applies: it restarts a request that makes no progress, and these requests fail at once.

The run therefore does not end silently; each retry line names R2's reason. It ends as systemd's `Result=timeout`, and no line in the journal says the credential is the problem.

**Solution**: #1939 (BACKUP-061). The ship script's first R2 call, `restic snapshots`, runs under its own `timeout -k 10 {{ node_backup_probe_timeout }}` (120 s: above one 45 s stuck request, a quarter of the unit). Its stderr is captured and replayed to the journal. On exit 124 or 137, the script reports the last retry reason as the verdict, adds a credential hint when that reason is an auth refusal, and otherwise reports "no answer". `backup`, `forget` and `check` stay unbounded, because they legitimately run long. The in-cluster watcher already names the cause: `RESTIC_TIMEOUT` ends the call, and `reason_from_stderr` takes the first stderr line, which is the first retry line. A test pins both behaviours with a fake restic that prints the retry line forever.

**Rule**:

- **A client's timeout flag names one failure shape. Check which one before trusting it for another.** A stalled request and a refused request are different shapes, and a retrying client can turn the second into an indefinite wait.
- **"Permanent error" is decided per backend, from the provider's error codes.** An S3-compatible store that answers auth failures with non-AWS codes gets them retried. Measure the provider's actual response (`curl --aws-sigv4` with a made-up key costs nothing) rather than assume AWS's.
- **When the operation cannot be made to fail fast, bound it from outside and turn its last diagnostic into the verdict.**

**Tags**: `#restic` `#r2` `#s3` `#timeouts` `#issue-1939` `#backup-061`
