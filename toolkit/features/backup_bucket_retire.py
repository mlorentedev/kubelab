"""Retire an R2 bucket nothing reads: empty it, delete it, prove it gone (BACKUP-057 close-out, #1920).

R2 refuses to delete a bucket that holds an object, and emptying one is an S3
operation, so two credentials meet here:

- an S3 pair with delete rights on the bucket (`--pair`, read from SOPS, never
  printed), which removes every object;
- the Cloudflare R2 admin token (`terraform_state_bootstrap.ADMIN_KEY`), which deletes the
  empty bucket. That token never reaches a node.

The order matters for the pair: it must still exist when the bucket is emptied,
so the bucket is retired BEFORE `make backup-revoke-r2-pair` revokes it.

Refused outright: a bucket any `backup.sources` node writes, and a bucket the
merged config still names. Something reads a bucket the config names, so the
config change lands first and the deletion follows it.

Without `apply` the command only reports what it would delete. With it, the
bucket is emptied, deleted, and then read back: only a 404 counts as gone.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Iterator, Optional

from toolkit.core.logging import logger
from toolkit.features.backup_node_credentials import (
    MintError,
    _s3_env,
    cloudflare_http,
    node_bucket,
)

# Emptying a bucket that held four nodes' history is thousands of DELETEs, far
# past the 60 s the read-only probes allow.
_EMPTY_TIMEOUT = 1800

RunFn = Callable[[list[str], dict[str, str]], "tuple[int, str, str]"]
HttpFn = Callable[[str, str, Optional[dict[str, Any]]], Any]

_TOTAL_OBJECTS = re.compile(r"Total Objects:\s*(\d+)")
_TOTAL_SIZE = re.compile(r"Total Size:\s*(\d+)")


class RetireError(RuntimeError):
    """The bucket was not retired. The message names the step, never a credential."""


def _leaves(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        for item in value.values():
            yield from _leaves(item)
    elif isinstance(value, list):
        for item in value:
            yield from _leaves(item)
    elif isinstance(value, str):
        yield value


def config_names(config: dict[str, Any], bucket: str) -> bool:
    """True if any string in the merged config names `bucket` (as a whole name, URLs included)."""
    pattern = re.compile(rf"(?<![\w-]){re.escape(bucket)}(?![\w-])")
    return any(pattern.search(leaf) for leaf in _leaves(config))


def refusal(config: dict[str, Any], bucket: str) -> Optional[str]:
    """Why `bucket` must not be retired, or None."""
    nodes = sorted((config.get("backup") or {}).get("sources") or {})
    if bucket in {node_bucket(n) for n in nodes}:
        return f"{bucket} is a backup.sources node's bucket"
    if config_names(config, bucket):
        return f"the config still names {bucket}; remove that first, then retire the bucket"
    return None


def inventory(run: RunFn, endpoint: str, bucket: str, env: dict[str, str]) -> tuple[int, int]:
    """(objects, bytes) in `bucket`, listed with the S3 pair."""
    argv = ["aws", "--endpoint-url", endpoint, "s3", "ls", f"s3://{bucket}", "--recursive", "--summarize"]
    rc, out, err = run(argv, env)
    if rc != 0:
        raise RetireError(f"listing {bucket} failed (rc {rc}): {err.strip()[:200]}")
    objects, size = _TOTAL_OBJECTS.search(out), _TOTAL_SIZE.search(out)
    if not objects or not size:
        raise RetireError(f"listing {bucket} printed no totals; `aws s3 ls --summarize` output changed?")
    return int(objects.group(1)), int(size.group(1))


def _exists(http: HttpFn, account_id: str, bucket: str) -> bool:
    try:
        http("GET", f"/accounts/{account_id}/r2/buckets/{bucket}", None)
    except MintError as exc:
        if exc.status == 404:
            return False
        raise RetireError(f"reading {bucket}: {exc}") from None
    return True


def retire_bucket(
    bucket: str,
    *,
    config: dict[str, Any],
    account_id: str,
    endpoint: str,
    pair: tuple[str, str],
    http: HttpFn,
    run: RunFn,
    apply: bool = False,
) -> str:
    """Return "absent", "planned" or "retired". Raise RetireError on a refusal or a failed step."""
    why = refusal(config, bucket)
    if why:
        raise RetireError(why)
    if not _exists(http, account_id, bucket):
        return "absent"

    env = _s3_env(*pair)
    objects, size = inventory(run, endpoint, bucket, env)
    logger.info(f"{bucket}: {objects} objects, {size} bytes")
    if not apply:
        logger.info(f"{bucket}: dry run, nothing deleted. APPLY=1 empties and deletes it.")
        return "planned"

    if objects:
        rc, _, err = run(["aws", "--endpoint-url", endpoint, "s3", "rm", f"s3://{bucket}", "--recursive"], env)
        if rc != 0:
            raise RetireError(f"emptying {bucket} failed (rc {rc}): {err.strip()[:200]}")
        left, _ = inventory(run, endpoint, bucket, env)
        if left:
            raise RetireError(f"{bucket} still holds {left} objects after the delete; the bucket was kept")

    try:
        http("DELETE", f"/accounts/{account_id}/r2/buckets/{bucket}", None)
    except MintError as exc:
        raise RetireError(f"deleting {bucket}: {exc}") from None
    if _exists(http, account_id, bucket):
        raise RetireError(f"{bucket} still answers after its DELETE")
    return "retired"


def retire_bucket_cmd(bucket: str, *, pair_prefix: str, apply: bool) -> bool:
    """The CLI entry point: real SOPS, the real admin token, the aws CLI. True iff it completed."""
    from toolkit.features.backup_destination import _default_run
    from toolkit.features.backup_token_revoke import pair_paths
    from toolkit.features.configuration import ConfigurationManager
    from toolkit.features.terraform_state_bootstrap import ADMIN_KEY

    cm = ConfigurationManager("prod")
    config = cm.get_merged_config()
    r2 = (config.get("backup") or {}).get("r2") or {}
    account_id, endpoint = str(r2.get("account_id") or ""), str(r2.get("endpoint") or "")
    access_path, secret_path = pair_paths(pair_prefix)
    access, secret, admin = (cm.get_secret_by_path(p) for p in (access_path, secret_path, ADMIN_KEY))
    missing = [p for p, v in ((access_path, access), (secret_path, secret), (ADMIN_KEY, admin)) if not v]
    if not account_id or not endpoint or missing:
        logger.error(f"needed and absent: {', '.join(missing or ['backup.r2.account_id/endpoint'])}")
        return False
    try:
        outcome = retire_bucket(
            bucket,
            config=config,
            account_id=account_id,
            endpoint=endpoint,
            pair=(str(access), str(secret)),
            http=cloudflare_http(str(admin)),
            run=lambda argv, env: _default_run(argv, env, timeout=_EMPTY_TIMEOUT),
            apply=apply,
        )
    except RetireError as exc:
        logger.error(f"{bucket}: {exc}")
        return False
    if outcome == "absent":
        logger.success(f"{bucket} does not exist; nothing to do")
    elif outcome == "retired":
        logger.success(f"{bucket}: emptied, deleted, and GET now answers 404")
    return True
