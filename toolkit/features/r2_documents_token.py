"""The product documents bucket's own R2 token (STOR-002, #2535).

The bucket and its lock are declared in `infra/terraform/r2/main.tf`. The token
is not: a token minted by Terraform would sit in clear in the root's state, the
reason BACKUP-057 Q1 mints through the Cloudflare API instead. This reuses that
machinery (`backup_node_credentials._mint_token`):

- Object Read & Write on `kubelab-product-documents` alone, so it can neither
  administer the bucket nor change its lock;
- verified by consequence before it is stored: it must list the documents
  bucket and get AccessDenied on the backups' shared bucket, or it is revoked;
- its S3 pair goes straight into `prod.enc.yaml` and is never printed. It
  reaches the product's operator through SOPS, never through a product's CI.

The bucket must exist first: run `make tf-r2-apply` before this.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

from toolkit.core.logging import logger
from toolkit.features import backup_node_credentials as bnc

# Mirrors `cloudflare_r2_bucket.documents` in infra/terraform/r2/main.tf
# (tests/test_r2_terraform.py compares the two).
DOCUMENTS_BUCKET = "kubelab-product-documents"
TOKEN_NAME = DOCUMENTS_BUCKET
ACCESS_KEY_PATH = "storage.product_documents.access_key_id"
SECRET_KEY_PATH = "storage.product_documents.secret_access_key"
# Production only: staging needs no evidence store (#2535).
SECRETS_ENV = "prod"


def mint(
    *,
    account_id: str,
    endpoint: str,
    refused_bucket: str,
    http: bnc.HttpFn,
    store: bnc.Store,
    run: bnc.RunFn,
    rotate: bool = False,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """Object Read & Write on the documents bucket only. Returns kept/minted/rotated."""

    def request() -> dict[str, Any]:
        group = bnc.permission_group_id(http, account_id, bnc.WRITE_GROUP)
        return bnc._token_body(TOKEN_NAME, [DOCUMENTS_BUCKET], account_id=account_id, group_id=group)

    return bnc._mint_token(
        "the product documents",
        request,
        paths=(ACCESS_KEY_PATH, SECRET_KEY_PATH),
        readable=[DOCUMENTS_BUCKET],
        refused=refused_bucket,
        account_id=account_id,
        endpoint=endpoint,
        http=http,
        store=store,
        run=run,
        rotate=rotate,
        sleep=sleep,
    )


class ProdStore(bnc.SopsStore):
    """Reads the merged prod config; writes to prod.enc.yaml.

    `SopsStore.write` routes by `sops_file_for`, which knows only backup keys.
    """

    def write(self, data: dict[str, str]) -> bool:
        return bool(self._cm.batch_update_secrets(data, secret_file_path=self._dir / f"{SECRETS_ENV}.enc.yaml"))


def mint_documents_token(rotate: bool = False, store: Optional[bnc.Store] = None) -> bool:
    """Mint (or with `rotate`, replace) the documents pair. True iff it is in SOPS."""
    from toolkit.features.backup_destination import _default_run

    sops = ProdStore()
    store = store or sops
    r2 = sops._cm.get_merged_config().get("backup", {}).get("r2", {})
    try:
        account_id, endpoint, refused = str(r2["account_id"]), str(r2["endpoint"]), str(r2["bucket"])
    except KeyError as exc:
        logger.error(f"backup.r2.{exc.args[0]} is missing from the config SSOT")
        return False

    minter = store.show(bnc.MINTER_KEY)
    if not minter:
        logger.error(f"{bnc.MINTER_KEY} is absent from SOPS; nothing can be minted.")
        return False

    try:
        outcome = mint(
            account_id=account_id,
            endpoint=endpoint,
            refused_bucket=refused,
            http=bnc.cloudflare_http(minter),
            store=store,
            run=_default_run,
            rotate=rotate,
        )
    except bnc.MintError as exc:
        logger.error(str(exc))
        return False
    logger.success(f"token {TOKEN_NAME}: {outcome}")
    return True
