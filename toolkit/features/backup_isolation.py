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
one, since a lock only guards what exists, so it is attempted only where it
can only be refused: the bucket's lock rules are read first and must hold
`data/` by age for at least R, and the youngest pack must be more than a day
inside R. Otherwise the probe fails without deleting. What is left is a rule
that reads right and is not enforced; then the delete is accepted, and the
probe says which pack it removed.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from toolkit.core.logging import logger
from toolkit.features.backup_destination import RunFn
from toolkit.features.backup_node_credentials import _s3_env, access_key_path, secret_key_path
from toolkit.features.r2_tfvars import node_bucket

DENIED = "AccessDenied"
LOCKED = "ObjectLockedByBucketPolicy"
# The token Terraform manages the buckets and their locks with; read-only use here.
ADMIN_TOKEN_KEY = "cloudflare.r2_admin_token"
# A key no restic repository writes: `data/` holds packs named by their hash.
PROBE_KEY = "data/kubelab-isolation-probe-{node}"
# The newest pack must be at least this far inside R, so the clock and a slow
# run cannot carry it past the window between the listing and the delete.
SAFETY_S = 86400


def _aws(endpoint: str, *args: str) -> list[str]:
    return ["aws", "--endpoint-url", endpoint, "s3api", *args]


def _missing_lock(lock_rules: Callable[[str], list[dict[str, Any]]], bucket: str, retention_s: int) -> str:
    """Why `bucket` has no enabled `data/` rule holding objects for at least R, or "" when it has one."""
    try:
        rules = lock_rules(bucket)
    except Exception as exc:  # noqa: BLE001 - any failure leaves the lock unread
        return f"its lock rules could not be read ({exc})"
    # Only an `Age` condition carries maxAgeSeconds, so this also requires the
    # type Terraform declares; `Indefinite` or `Date` reads as missing.
    for rule in rules:
        condition = rule.get("condition") or {}
        if (
            rule.get("enabled")
            and rule.get("prefix") == "data/"
            and int(condition.get("maxAgeSeconds") or 0) >= retention_s
        ):
            return ""
    return f"no enabled lock rule holds data/ for {retention_s // 86400} days"


def _youngest_pack(
    run: RunFn, endpoint: str, bucket: str, env: dict[str, str], now: datetime, retention_s: int
) -> tuple[Optional[str], str]:
    """The key of the newest object under `data/`, or None with the reason.

    The CLI pages through the whole listing. The age check is a second guard:
    a pack older than R is deletable by design, so deleting it proves nothing
    and loses it.
    """
    rc, out, err = run(
        _aws(endpoint, "list-objects-v2", "--bucket", bucket, "--prefix", "data/", "--output", "json"), env
    )
    if rc != 0:
        return None, f"its own pair cannot list it: {err.strip()}"
    contents: list[dict[str, Any]] = (json.loads(out or "{}") or {}).get("Contents") or []
    if not contents:
        return None, "it holds nothing under data/, so there is no object for the lock to refuse a delete of"
    newest = max(contents, key=lambda o: datetime.fromisoformat(str(o["LastModified"]).replace("Z", "+00:00")))
    age = now - datetime.fromisoformat(str(newest["LastModified"]).replace("Z", "+00:00"))
    if age.total_seconds() >= retention_s - SAFETY_S:
        return None, f"its newest pack is {age.days} days old, too close to R for a delete to prove the lock"
    return str(newest["Key"]), ""


def _refused(rc: int, err: str, reason: str) -> bool:
    return rc != 0 and reason in err


def probe(
    nodes: list[str],
    *,
    declared: list[str] | frozenset[str],
    endpoint: str,
    secret: Callable[[str], Optional[str]],
    run: RunFn,
    lock_rules: Callable[[str], list[dict[str, Any]]],
    retention_s: int,
    now: datetime,
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
        # The delete below is only safe when the lock is configured: if it is
        # not, the probe would destroy the pack it set out to protect. So a
        # missing rule is caught by reading it, and nothing is deleted.
        why = _missing_lock(lock_rules, bucket, retention_s)
        if why:
            problems.append(f"{bucket}: {why}; no delete was attempted")
            continue
        youngest, why = _youngest_pack(run, endpoint, bucket, pairs[owner], now, retention_s)
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
    from toolkit.features.backup_node_credentials import cloudflare_http

    config = cm.get_merged_config()
    backup = config.get("backup", {}) or {}
    r2 = backup["r2"]
    admin = cm.get_secret_by_path(ADMIN_TOKEN_KEY)
    if not admin:
        logger.error(f"{ADMIN_TOKEN_KEY} is absent from SOPS; the lock rules cannot be read")
        return False
    http = cloudflare_http(str(admin))
    account = str(r2["account_id"])
    return probe(
        sorted(backup.get("sources", {}) or {}),
        declared=own_bucket_nodes(config),
        endpoint=str(r2["endpoint"]).rstrip("/"),
        secret=cm.get_secret_by_path,
        run=run or _default_run,
        lock_rules=lambda bucket: list(
            (http("GET", f"/accounts/{account}/r2/buckets/{bucket}/lock", None) or {}).get("rules") or []
        ),
        retention_s=int(r2["lock_retention_days"]) * 86400,
        now=datetime.now(timezone.utc),
    )
