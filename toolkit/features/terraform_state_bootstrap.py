"""Create the Terraform state bucket and the credential that reaches it (TF-007).

Three things exist before any root can keep its state in R2, and none of them
can be declared in a root: the state of the root that created them would live
in the bucket it creates. So they are made here, idempotently, through the
Cloudflare API:

1. the bucket, `terraform.state.bucket`;
2. its lock rule: everything under `terraform.state.history_prefix` is retained
   for `history_retention_days`, so a copy of a state can be neither replaced
   nor deleted in that time (R2 has no object versioning);
3. a token with Object Read & Write on that bucket alone, minted by BACKUP-057's
   machinery and verified by consequence: it must list the state bucket and be
   refused on the backups' bucket. Its S3 pair goes to `common.enc.yaml`, the
   file the runner's `common` config merges.

Each step reads first and writes only what differs, so a second run changes
nothing. `rotate` replaces the token and revokes the old one.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Any, Optional

from toolkit.core.logging import logger
from toolkit.features import backup_node_credentials as bnc

ACCESS_KEY_PATH = "terraform.state.access_key_id"
SECRET_KEY_PATH = "terraform.state.secret_access_key"
LOCK_RULE_ID = "terraform-state-history"
TOKEN_NAME = "kubelab-tfstate"
# The bucket and lock rule are bucket configuration, which the R2 admin token
# edits. Minting a token needs the minter, which nothing else may hold.
ADMIN_KEY = "cloudflare.r2_admin_token"


def lock_rule(prefix: str, days: int) -> dict[str, Any]:
    return {
        "id": LOCK_RULE_ID,
        "enabled": True,
        "prefix": prefix,
        "condition": {"type": "Age", "maxAgeSeconds": days * 86400},
    }


def _same_rule(have: Mapping[str, Any], want: Mapping[str, Any]) -> bool:
    """Compared field by field: the API may return more than it was sent."""
    condition = have.get("condition") or {}
    return (
        have.get("id") == want["id"]
        and bool(have.get("enabled")) == want["enabled"]
        and have.get("prefix") == want["prefix"]
        and condition.get("type") == want["condition"]["type"]
        and int(condition.get("maxAgeSeconds") or 0) == want["condition"]["maxAgeSeconds"]
    )


def ensure_bucket(http: bnc.HttpFn, account_id: str, bucket: str) -> str:
    listed = http("GET", f"/accounts/{account_id}/r2/buckets?name_contains={bucket}", None) or {}
    if any(b.get("name") == bucket for b in listed.get("buckets") or []):
        return "kept"
    http("POST", f"/accounts/{account_id}/r2/buckets", {"name": bucket})
    return "created"


def ensure_lock(http: bnc.HttpFn, account_id: str, bucket: str, rule: dict[str, Any]) -> str:
    """Our rule present and exact; rules with other ids are kept as they are."""
    path = f"/accounts/{account_id}/r2/buckets/{bucket}/lock"
    rules = list((http("GET", path, None) or {}).get("rules") or [])
    ours = [r for r in rules if r.get("id") == LOCK_RULE_ID]
    if len(ours) == 1 and _same_rule(ours[0], rule):
        return "kept"
    others = [r for r in rules if r.get("id") != LOCK_RULE_ID]
    http("PUT", path, {"rules": [*others, rule]})
    return "set"


def mint_state_token(
    *,
    account_id: str,
    endpoint: str,
    bucket: str,
    refused_bucket: str,
    http: bnc.HttpFn,
    store: bnc.Store,
    run: bnc.RunFn,
    rotate: bool = False,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """Object Read & Write on `bucket` only; refused on `refused_bucket`. Returns kept/minted/rotated."""

    def request() -> dict[str, Any]:
        group = bnc.permission_group_id(http, account_id, bnc.WRITE_GROUP)
        return bnc._token_body(TOKEN_NAME, [bucket], account_id=account_id, group_id=group)

    return bnc._mint_token(
        "the Terraform state",
        request,
        paths=(ACCESS_KEY_PATH, SECRET_KEY_PATH),
        readable=[bucket],
        refused=refused_bucket,
        account_id=account_id,
        endpoint=endpoint,
        http=http,
        store=store,
        run=run,
        rotate=rotate,
        sleep=sleep,
    )


class CommonStore(bnc.SopsStore):
    """Reads the merged config; writes to common.enc.yaml, which the runner reads."""

    def write(self, data: dict[str, str]) -> bool:
        return bool(self._cm.batch_update_secrets(data, secret_file_path=self._dir / "common.enc.yaml"))


def bootstrap(rotate: bool = False, store: Optional[bnc.Store] = None) -> bool:
    """Bucket, lock rule and token, each created only if absent. True iff all three hold."""
    from toolkit.features.backup_destination import _default_run

    sops = CommonStore()
    store = store or sops
    config = sops._cm.get_merged_config()
    try:
        r2 = config["backup"]["r2"]
        state = config["terraform"]["state"]
        account_id, endpoint, refused = str(r2["account_id"]), str(r2["endpoint"]), str(r2["bucket"])
        bucket, prefix, days = str(state["bucket"]), str(state["history_prefix"]), int(state["history_retention_days"])
    except KeyError as exc:
        logger.error(f"{exc.args[0]} is missing from the config SSOT (backup.r2, terraform.state)")
        return False

    tokens = {path: store.show(path) for path in (ADMIN_KEY, bnc.MINTER_KEY)}
    absent = [path for path, value in tokens.items() if not value]
    if absent:
        logger.error(f"{', '.join(absent)} absent from SOPS; the state bucket cannot be bootstrapped.")
        return False

    try:
        admin_http = bnc.cloudflare_http(str(tokens[ADMIN_KEY]))
        logger.info(f"bucket {bucket}: {ensure_bucket(admin_http, account_id, bucket)}")
        locked = ensure_lock(admin_http, account_id, bucket, lock_rule(prefix, days))
        logger.info(f"lock rule {LOCK_RULE_ID} on {prefix}: {locked}")
        outcome = mint_state_token(
            account_id=account_id,
            endpoint=endpoint,
            bucket=bucket,
            refused_bucket=refused,
            http=bnc.cloudflare_http(str(tokens[bnc.MINTER_KEY])),
            store=store,
            run=_default_run,
            rotate=rotate,
        )
        logger.info(f"token {TOKEN_NAME}: {outcome}")
    except bnc.MintError as exc:
        logger.error(str(exc))
        return False
    return True
