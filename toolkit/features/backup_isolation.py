"""Prove by consequence that no node reaches another's history, and that none can erase its own (BACKUP-057 AC1, AC3).

Every other check passes against the shared bucket, because they read
configuration. This one sends the requests a stolen node credential would send,
and fails on any that R2 accepts:

  - for every ordered pair of nodes (A, B), A's pair lists B's bucket and
    deletes an object in it, and both must be refused with AccessDenied;
  - each node's own pair deletes the youngest object under its bucket's
    `data/`, and that must be refused by the bucket lock.

A refusal counts only for the right reason. A network error or a missing bucket
also fails a request, and a probe that read the exit code alone would report
isolation it never measured. For the same reason an empty `data/` is a failure:
there is nothing for the lock to refuse.

The cross delete names a key that does not exist, so even with both the scope
and the lock broken it cannot remove a pack. The own delete has to name a real
one, since a lock only guards what exists. It names the youngest, which is
inside the retention window whatever the cadence; if it is accepted, the probe
says which pack it removed.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Optional

from toolkit.core.logging import logger
from toolkit.features.backup_destination import RunFn
from toolkit.features.backup_node_credentials import _s3_env, access_key_path, secret_key_path
from toolkit.features.r2_tfvars import node_bucket

DENIED = "AccessDenied"
LOCKED = "ObjectLockedByBucketPolicy"
# A key no restic repository writes: `data/` holds packs named by their hash.
PROBE_KEY = "data/kubelab-isolation-probe-{node}"


def _aws(endpoint: str, *args: str) -> list[str]:
    return ["aws", "--endpoint-url", endpoint, "s3api", *args]


def _youngest_pack(run: RunFn, endpoint: str, bucket: str, env: dict[str, str]) -> tuple[Optional[str], str]:
    """The key of the newest object under `data/`, or None with the reason."""
    rc, out, err = run(
        _aws(endpoint, "list-objects-v2", "--bucket", bucket, "--prefix", "data/", "--output", "json"), env
    )
    if rc != 0:
        return None, f"its own pair cannot list it: {err.strip()}"
    contents: list[dict[str, Any]] = (json.loads(out or "{}") or {}).get("Contents") or []
    if not contents:
        return None, "it holds nothing under data/, so there is no object for the lock to refuse a delete of"
    return str(max(contents, key=lambda o: str(o["LastModified"]))["Key"]), ""


def _refused(rc: int, err: str, reason: str) -> bool:
    return rc != 0 and reason in err


def probe(
    nodes: list[str],
    *,
    declared: list[str] | frozenset[str],
    endpoint: str,
    secret: Callable[[str], Optional[str]],
    run: RunFn,
) -> bool:
    """True iff every request that must be refused was refused, for the right reason."""
    problems: list[str] = []
    refused = 0
    for node in nodes:
        if node not in declared:
            problems.append(f"{node} is not in backup.r2.own_bucket_nodes: it still ships to the shared bucket")

    pairs: dict[str, dict[str, str]] = {}
    for node in nodes:
        access, key = secret(access_key_path(node)), secret(secret_key_path(node))
        if not access or not key:
            problems.append(f"{node}'s R2 pair is missing from SOPS; mint it with `make backup-mint-node-tokens`")
            continue
        pairs[node] = _s3_env(str(access).strip(), str(key).strip())

    for owner in nodes:
        bucket = node_bucket(owner)
        for other, env in pairs.items():
            if other == owner:
                continue
            rc, _, err = run(_aws(endpoint, "list-objects-v2", "--bucket", bucket, "--max-keys", "1"), env)
            if rc == 0:
                problems.append(f"{other}'s pair LISTED {bucket}")
            elif not _refused(rc, err, DENIED):
                problems.append(f"{other}'s pair failed to list {bucket} without {DENIED}: {err.strip()}")
            else:
                refused += 1
            key = PROBE_KEY.format(node=other)
            rc, _, err = run(_aws(endpoint, "delete-object", "--bucket", bucket, "--key", key), env)
            if rc == 0:
                problems.append(f"{other}'s pair was ALLOWED to delete in {bucket}")
            elif not _refused(rc, err, DENIED):
                problems.append(f"{other}'s pair failed to delete in {bucket} without {DENIED}: {err.strip()}")
            else:
                refused += 1

        if owner not in pairs:
            continue
        youngest, why = _youngest_pack(run, endpoint, bucket, pairs[owner])
        if youngest is None:
            problems.append(f"{bucket}: {why}")
            continue
        rc, _, err = run(_aws(endpoint, "delete-object", "--bucket", bucket, "--key", youngest), pairs[owner])
        if rc == 0:
            problems.append(
                f"{bucket} is NOT locked: {owner}'s own pair deleted {youngest}. "
                "Its newest snapshot now lacks that pack: see 'Proving isolation' in offsite-backup-restore.md"
            )
        elif not _refused(rc, err, LOCKED):
            problems.append(
                f"deleting {youngest} in {bucket} failed without {LOCKED}, so the lock is unproven: {err.strip()}"
            )
        else:
            logger.info(f"{bucket}: {owner}'s own delete of the youngest pack was refused by the lock")

    # Reported either way: before the migration the cross half can already pass.
    logger.info(f"{refused} of {len(pairs) * (len(nodes) - 1) * 2} cross-node requests refused with {DENIED}")
    if problems:
        for problem in problems:
            logger.error(problem)
        return False
    logger.success(f"every cross-node request and all {len(nodes)} own deletes were refused")
    return True


def probe_fleet(env: str, *, cm: Any = None, run: Optional[RunFn] = None) -> bool:
    """`probe` over `backup.sources`, with the pairs from SOPS."""
    logger.section("backup isolation probe")
    if env != "prod":
        logger.error(f"the node buckets are prod's; refusing --env {env}")
        return False
    if cm is None:
        from toolkit.features.configuration import ConfigurationManager

        cm = ConfigurationManager(env)
    from toolkit.features.backup_destination import _default_run, own_bucket_nodes

    config = cm.get_merged_config()
    backup = config.get("backup", {}) or {}
    return probe(
        sorted(backup.get("sources", {}) or {}),
        declared=own_bucket_nodes(config),
        endpoint=str(backup["r2"]["endpoint"]).rstrip("/"),
        secret=cm.get_secret_by_path,
        run=run or _default_run,
    )
